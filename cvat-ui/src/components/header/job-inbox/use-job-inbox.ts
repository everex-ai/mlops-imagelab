// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import {
    useCallback, useEffect, useRef, useState,
} from 'react';

import { getCore, JobNotification, ServerError } from 'cvat-core-wrapper';

import {
    shouldNotifyInBrowser, showBrowserNotification, showBrowserNotificationsDigest,
} from './browser-notifications';

const core = getCore();

export const POLL_INTERVAL_MS = 10 * 1000;

// A bulk state change can create dozens of notifications at once: show a few
// individually and fold the rest into one digest.
const MAX_INDIVIDUAL_BROWSER_NOTIFICATIONS = 3;

export interface JobInbox {
    unreadCount: number;
    items: JobNotification[] | null;
    loading: boolean;
    failed: boolean;
    reload(): void;
    markRead(item: JobNotification): Promise<'ok' | 'gone'>;
    markAllRead(): Promise<boolean>;
}

interface Options {
    open: boolean;
    unreadOnly: boolean;
    onBrowserNotificationClick(item: JobNotification): void;
    onBrowserDigestClick(): void;
}

/**
 * Header bell state (R20-R25). Polls the cheap summary every 10s and refetches the
 * list while there are unannounced notifications or while the dropdown is open, so
 * that a rejection's target frame reflects issues resolved since (R17).
 */
export function useJobInbox({
    open, unreadOnly, onBrowserNotificationClick, onBrowserDigestClick,
}: Options): JobInbox {
    const [unreadCount, setUnreadCount] = useState(0);
    const [items, setItems] = useState<JobNotification[] | null>(null);
    const [loading, setLoading] = useState(false);
    const [failed, setFailed] = useState(false);

    // Everything with an id at or below this existed before this page load, or was
    // already announced: no OS notification for it (R23).
    const announcedUpToRef = useRef<number | null>(null);
    const latestIdRef = useRef<number | null>(null);
    // Ids this tab marked read; guards the badge against double decrements (e.g. an OS
    // notification clicked after the same item was opened from the list).
    const readIdsRef = useRef(new Set<number>());
    const aliveRef = useRef(true);
    const pollingRef = useRef(false);
    // Bumped by every local read mutation: a summary requested before it is stale.
    const mutationRef = useRef(0);
    const listRequestRef = useRef(0);
    const openRef = useRef(open);
    const unreadOnlyRef = useRef(unreadOnly);
    const onClickRef = useRef(onBrowserNotificationClick);
    const onDigestClickRef = useRef(onBrowserDigestClick);
    openRef.current = open;
    unreadOnlyRef.current = unreadOnly;
    onClickRef.current = onBrowserNotificationClick;
    onDigestClickRef.current = onBrowserDigestClick;

    const announce = useCallback((list: JobNotification[]): void => {
        const baseline = announcedUpToRef.current;
        if (baseline === null) return;
        const fresh = list.filter((item) => item.id > baseline);
        if (!fresh.length) return;
        announcedUpToRef.current = Math.max(baseline, ...fresh.map((item) => item.id));

        const toShow = fresh.filter(shouldNotifyInBrowser).reverse(); // oldest first
        if (toShow.length > MAX_INDIVIDUAL_BROWSER_NOTIFICATIONS) {
            showBrowserNotificationsDigest(toShow.length, () => onDigestClickRef.current());
            return;
        }
        toShow.forEach((item) => {
            showBrowserNotification(item, () => onClickRef.current(item));
        });
    }, []);

    const fetchList = useCallback(async (): Promise<void> => {
        const requestId = ++listRequestRef.current;
        setLoading(true);
        try {
            const list = await core.jobInbox.list({ unreadOnly: unreadOnlyRef.current });
            // A newer request superseded this one, or the header is gone.
            if (!aliveRef.current || requestId !== listRequestRef.current) return;
            setItems(list.map((item) => (readIdsRef.current.has(item.id) ? { ...item, isRead: true } : item)));
            setFailed(false);
            announce(list);
        } catch {
            if (aliveRef.current && requestId === listRequestRef.current) setFailed(true);
        } finally {
            if (aliveRef.current && requestId === listRequestRef.current) setLoading(false);
        }
    }, [announce]);

    const poll = useCallback(async (): Promise<void> => {
        if (pollingRef.current) return; // a slow server: never stack summary requests
        pollingRef.current = true;
        const mutation = mutationRef.current;
        try {
            let summary;
            try {
                summary = await core.jobInbox.summary();
            } catch {
                return; // silently retried on the next tick
            }
            if (!aliveRef.current) return;

            const latestId = summary.latestId ?? 0;
            if (mutation === mutationRef.current) {
                setUnreadCount(summary.unreadCount);
            }
            if (announcedUpToRef.current === null) {
                announcedUpToRef.current = latestId;
            }

            const shrunk = latestIdRef.current !== null && latestId < latestIdRef.current;
            latestIdRef.current = latestId;
            // Keep refetching until the newest notification is announced, so a failed
            // list request is retried on the next tick rather than forgotten.
            if (openRef.current || latestId > (announcedUpToRef.current ?? 0)) {
                await fetchList();
            } else if (shrunk) {
                // Something disappeared (e.g. access lost): keep a cached list honest.
                setItems(null);
            }
        } finally {
            pollingRef.current = false;
        }
    }, [fetchList]);

    useEffect(() => {
        aliveRef.current = true;
        poll();
        const timer = window.setInterval(poll, POLL_INTERVAL_MS);
        return () => {
            aliveRef.current = false;
            window.clearInterval(timer);
        };
    }, [poll]);

    // Opening the dropdown or switching the filter always fetches a fresh list.
    useEffect(() => {
        if (open) fetchList();
    }, [open, unreadOnly, fetchList]);

    const markRead = useCallback(async (item: JobNotification): Promise<'ok' | 'gone'> => {
        if (!item.isRead && !readIdsRef.current.has(item.id)) {
            mutationRef.current++;
            setUnreadCount((count) => Math.max(0, count - 1));
        }
        readIdsRef.current.add(item.id);
        setItems((prev) => prev && prev.map((i) => (i.id === item.id ? { ...i, isRead: true } : i)));
        try {
            await core.jobInbox.markRead(item.id);
        } catch (error: unknown) {
            if (error instanceof ServerError && error.code === 404) {
                if (aliveRef.current) setItems((prev) => prev && prev.filter((i) => i.id !== item.id));
                return 'gone';
            }
            // Network failure: navigate anyway, the next summary corrects the badge.
        }
        return 'ok';
    }, []);

    const markAllRead = useCallback(async (): Promise<boolean> => {
        mutationRef.current++;
        setItems((prev) => prev && prev.map((i) => ({ ...i, isRead: true })));
        setUnreadCount(0);
        let ok = true;
        try {
            await core.jobInbox.markAllRead();
        } catch {
            ok = false;
        }
        // Resync either way; on failure this restores the real unread state.
        mutationRef.current++;
        await poll();
        if (!ok) await fetchList();
        return ok;
    }, [poll, fetchList]);

    return {
        unreadCount,
        items,
        loading,
        failed,
        reload: fetchList,
        markRead,
        markAllRead,
    };
}
