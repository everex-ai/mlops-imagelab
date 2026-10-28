// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { JobNotification, JobNotificationEvent } from 'cvat-core-wrapper';

import { EVENT_LABELS, actorName } from './labels';

// OS notifications while an ImageLab tab is open (R21-R25). No Service Worker:
// with every tab closed nothing is shown, the bell catches up on the next visit.

// 가정 Q2(사용자 확인 대기): only the events that ask the recipient to act next.
const OS_NOTIFIED_EVENTS = new Set<JobNotificationEvent>([
    JobNotificationEvent.REJECTED,
    JobNotificationEvent.SUBMITTED,
]);

export function browserNotificationsSupported(): boolean {
    // The Notification API only exists in secure contexts (https, localhost). Users on the
    // plain-http LAN address get the badge and the list only.
    return typeof window !== 'undefined' && 'Notification' in window && window.isSecureContext;
}

// 가정 Q3(사용자 확인 대기): asked once, on the first bell click (a user gesture).
// A denied permission is never asked again: the browser keeps it as 'denied'.
export function requestBrowserNotificationPermission(): void {
    if (browserNotificationsSupported() && Notification.permission === 'default') {
        Notification.requestPermission().catch(() => {});
    }
}

export function shouldNotifyInBrowser(item: JobNotification): boolean {
    return !item.isRead && OS_NOTIFIED_EVENTS.has(item.event);
}

export function showBrowserNotification(item: JobNotification, onClick: () => void): void {
    if (!browserNotificationsSupported() || Notification.permission !== 'granted') {
        return;
    }

    const body = item.event === JobNotificationEvent.SUBMITTED && item.actor ?
        `${item.taskName} · ${actorName(item.actor)}` : item.taskName;

    try {
        // The same tag in every open tab: the OS shows one notification, not one per tab (R24).
        const notification = new Notification(`${EVENT_LABELS[item.event]} · Job #${item.jobId}`, {
            body,
            tag: `imagelab-job-notification-${item.id}`,
        });
        notification.onclick = () => {
            window.focus();
            notification.close();
            onClick();
        };
    } catch {
        // Some browsers (e.g. Android Chrome) only allow notifications from a Service Worker.
    }
}
