// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { JobNotificationActor, JobNotificationEvent } from 'cvat-core-wrapper';

export const EVENT_LABELS: Record<JobNotificationEvent, string> = {
    [JobNotificationEvent.REJECTED]: '검수 반려',
    [JobNotificationEvent.ACCEPTED]: '검수 완료',
    [JobNotificationEvent.SUBMITTED]: '작업 완료',
};

export const EVENT_TAG_COLORS: Record<JobNotificationEvent, string> = {
    [JobNotificationEvent.REJECTED]: 'red',
    [JobNotificationEvent.ACCEPTED]: 'green',
    [JobNotificationEvent.SUBMITTED]: 'blue',
};

export function actorName(actor: JobNotificationActor): string {
    const fullName = [actor.firstName, actor.lastName].filter(Boolean).join(' ').trim();
    return fullName || actor.username;
}
