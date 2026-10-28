// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { SerializedJobNotification, SerializedJobNotificationsSummary } from './server-response-types';

// Job round-boundary notifications shown by the header bell (INNO-123).
// Plain objects on purpose: they are read-only views of server rows.

export enum JobNotificationEvent {
    SUBMITTED = 'submitted',
    REJECTED = 'rejected',
    ACCEPTED = 'accepted',
}

export interface JobNotificationActor {
    id: number;
    username: string;
    firstName: string;
    lastName: string;
}

export interface JobNotification {
    id: number;
    event: JobNotificationEvent;
    createdDate: string;
    isRead: boolean;
    jobId: number;
    taskId: number;
    taskName: string;
    actor: JobNotificationActor | null;
    targetFrame: number;
}

export interface JobNotificationsSummary {
    unreadCount: number;
    latestId: number | null;
}

export function toJobNotification(data: SerializedJobNotification): JobNotification {
    return {
        id: data.id,
        event: data.event as JobNotificationEvent,
        createdDate: data.created_date,
        isRead: data.is_read,
        jobId: data.job_id,
        taskId: data.task_id,
        taskName: data.task_name,
        actor: data.actor ? {
            id: data.actor.id,
            username: data.actor.username,
            firstName: data.actor.first_name,
            lastName: data.actor.last_name,
        } : null,
        targetFrame: data.target_frame,
    };
}

export function toJobNotificationsSummary(data: SerializedJobNotificationsSummary): JobNotificationsSummary {
    return {
        unreadCount: data.unread_count,
        latestId: data.latest_id,
    };
}
