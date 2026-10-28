// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { JobNotification, JobNotificationEvent } from 'cvat-core-wrapper';

import { EVENT_LABELS } from './labels';

// OS notifications while an ImageLab tab is open (R21-R25). No Service Worker:
// with every tab closed nothing is shown, the bell catches up on the next visit.

// 사용자 결정 2026-10-28 (Q2): all three events raise an OS notification.
const OS_NOTIFIED_EVENTS = new Set<JobNotificationEvent>([
    JobNotificationEvent.REJECTED,
    JobNotificationEvent.SUBMITTED,
    JobNotificationEvent.ACCEPTED,
]);

// Korean particle after "Job #N", read as a Sino-Korean number: ...2/4/5/9 end in a vowel
// (이/사/오/구); every other ending, including 십/백/천/만 for trailing zeros, ends in a consonant.
function endsWithVowel(jobId: number): boolean {
    return [2, 4, 5, 9].includes(jobId % 10);
}

function subjectJob(jobId: number): string {
    return `Job #${jobId}${endsWithVowel(jobId) ? '가' : '이'}`;
}

function objectJob(jobId: number): string {
    return `Job #${jobId}${endsWithVowel(jobId) ? '를' : '을'}`;
}

export function browserNotificationText(item: JobNotification): { title: string; body: string } {
    const title = `ImageLab · Job #${item.jobId} ${EVENT_LABELS[item.event]}`;
    const task = `'${item.taskName}' Task의`;
    let body: string;
    if (item.event === JobNotificationEvent.REJECTED) {
        body = `${task} ${subjectJob(item.jobId)} 반려되었습니다. 반려 사유를 확인하세요.`;
    } else if (item.event === JobNotificationEvent.SUBMITTED) {
        const who = item.actor ? `${item.actor.username}님이 ` : '';
        body = `${who}${task} ${objectJob(item.jobId)} 완료했습니다. 검수를 시작하세요.`;
    } else {
        body = `${task} ${subjectJob(item.jobId)} 검수 완료되었습니다.`;
    }
    return { title, body };
}

export function browserNotificationsSupported(): boolean {
    // The Notification API only exists in secure contexts (https, localhost). Users on the
    // plain-http LAN address get the badge and the list only.
    return typeof window !== 'undefined' && 'Notification' in window && window.isSecureContext;
}

// 사용자 결정 2026-10-28 (Q3): asked once, on the first bell click (a user gesture).
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

    const { title, body } = browserNotificationText(item);

    try {
        // The same tag in every open tab: the OS shows one notification, not one per tab (R24).
        const notification = new Notification(title, {
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

export function showBrowserNotificationsDigest(count: number, onClick: () => void): void {
    if (!browserNotificationsSupported() || Notification.permission !== 'granted') {
        return;
    }

    try {
        const notification = new Notification(`ImageLab · 새 Job 알림 ${count}건`, {
            body: '알림 목록에서 확인하세요.',
            tag: 'imagelab-job-notification-digest',
        });
        notification.onclick = () => {
            window.focus();
            notification.close();
            onClick();
        };
    } catch {
        // See showBrowserNotification.
    }
}
