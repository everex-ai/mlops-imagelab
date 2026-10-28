// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import {
    useCallback, useEffect, useRef, useState,
} from 'react';

import { getCore, JobNotification } from 'cvat-core-wrapper';

import { shouldNotifyInBrowser, showBrowserNotification } from './browser-notifications';

const core = getCore();

export const POLL_INTERVAL_MS = 30 * 1000;

export interface JobInbox {
    unreadCount: number;
    items: JobNotification[] | null;
    loading: boolean;
    failed: boolean;
    reload(): void;
    markRead(item: JobNotification): Promise<'ok' | 'gone'>;
    markAllRead(): Promise<void>;
}

interface Options {
    open: boolean;
    unreadOnly: boolean;
    onBrowserNotificationClick(item: JobNotification): void;
}

/**
 * Header bell state (R20-R25). Polls the cheap summary every 30s and refetches the
 * list only when the newest id changes or while the dropdown is open, so that a
 * rejection's target frame reflects issues resolved since (R17).
 */
export function useJobInbox({ open, unreadOnly, onBrowserNotificationClick }: Options): JobInbox {
    const [unreadCount, setUnreadCount] = useState(0);
    const [items, setItems] = useState<JobNotification[] | null>(null);
    const [loading, setLoading] = useState(false);
    const [failed, setFailed] = useState(false);

    // Everything with an id at or below this existed before this page load, or was
    // already announced: no OS notification for it (R23).
    const announcedUpToRef = useRef<number | null>(null);
    const latestIdRef = useRef<number | null | undefined>(undefined);
    const openRef = useRef(open);
    const unreadOnlyRef = useRef(unreadOnly);
    const onClickRef = useRef(onBrowserNotificationClick);
    const listRequestRef = useRef(0);
    openRef.current = open;
    unreadOnlyRef.current = unreadOnly;
    onClickRef.current = onBrowserNotificationClick;

    const announce = useCallback((list: JobNotification[]): void => {
        const baseline = announcedUpToRef.current;
        if (baseline === null) return;
        const fresh = list.filter((item) => item.id > baseline);
        if (!fresh.length) return;
        announcedUpToRef.current = Math.max(baseline, ...fresh.map((item) => item.id));
        fresh.filter(shouldNotifyInBrowser).reverse().forEach((item) => {
            showBrowserNotification(item, () => onClickRef.current(item));
        });
    }, []);

    const fetchList = useCallback(async (): Promise<void> => {
        const requestId = ++listRequestRef.current;
        setLoading(true);
        try {
            const list = await core.jobInbox.list({ unreadOnly: unreadOnlyRef.current });
            if (requestId !== listRequestRef.current) return; // a newer request superseded this one
            setItems(list);
            setFailed(false);
            announce(list);
        } catch {
            if (requestId === listRequestRef.current) setFailed(true);
        } finally {
            if (requestId === listRequestRef.current) setLoading(false);
        }
    }, [announce]);

    const poll = useCallback(async (): Promise<void> => {
        let summary;
        try {
            summary = await core.jobInbox.summary();
        } catch {
            return; // silently retried on the next tick
        }

        setUnreadCount(summary.unreadCount);
        const latestId = summary.latestId ?? 0;
        if (announcedUpToRef.current === null) {
            announcedUpToRef.current = latestId;
        }

        const changed = latestIdRef.current !== undefined && latestIdRef.current !== latestId;
        latestIdRef.current = latestId;
        if (openRef.current || (changed && latestId > (announcedUpToRef.current ?? 0))) {
            await fetchList();
        } else if (changed) {
            // Something disappeared or was replaced (e.g. access lost): keep a cached list honest.
            setItems(null);
        }
    }, [fetchList]);

    useEffect(() => {
        poll();
        const timer = window.setInterval(poll, POLL_INTERVAL_MS);
        return () => window.clearInterval(timer);
    }, [poll]);

    // Opening the dropdown or switching the filter always fetches a fresh list.
    useEffect(() => {
        if (open) fetchList();
    }, [open, unreadOnly]);

    const markRead = useCallback(async (item: JobNotification): Promise<'ok' | 'gone'> => {
        if (!item.isRead) {
            setItems((prev) => prev && prev.map((i) => (i.id === item.id ? { ...i, isRead: true } : i)));
            setUnreadCount((count) => Math.max(0, count - 1));
        }
        try {
            await core.jobInbox.markRead(item.id);
        } catch (error: any) {
            if (error?.code === 404) {
                setItems((prev) => prev && prev.filter((i) => i.id !== item.id));
                return 'gone';
            }
            // Network failure: navigate anyway, the next summary corrects the badge.
        }
        return 'ok';
    }, []);

    const markAllRead = useCallback(async (): Promise<void> => {
        setItems((prev) => prev && prev.map((i) => ({ ...i, isRead: true })));
        setUnreadCount(0);
        try {
            await core.jobInbox.markAllRead();
        } finally {
            poll();
        }
    }, [poll]);

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
