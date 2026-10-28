// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';
import Tag from 'antd/lib/tag';
import Text from 'antd/lib/typography/Text';

import { JobNotification, JobNotificationEvent } from 'cvat-core-wrapper';
import CVATTooltip from 'components/common/cvat-tooltip';
import dayjs from 'utils/dayjs-wrapper';

import { EVENT_LABELS, EVENT_TAG_COLORS } from './labels';

interface Props {
    item: JobNotification;
    onClick(item: JobNotification): void;
}

export default function JobInboxItem({ item, onClick }: Props): JSX.Element {
    const created = dayjs(item.createdDate);
    const className = [
        'cvat-job-inbox-item',
        item.isRead ? 'cvat-job-inbox-item-read' : 'cvat-job-inbox-item-unread',
    ].join(' ');

    // 사용자 결정 2026-10-28 (Q5): the actor (username) is shown on 작업 완료 only, after the Task name
    const subtitle = item.event === JobNotificationEvent.SUBMITTED && item.actor ?
        `${item.taskName} · ${item.actor.username}` : item.taskName;

    return (
        <button type='button' className={className} onClick={() => onClick(item)}>
            <span className='cvat-job-inbox-item-dot' aria-hidden />
            <span className='cvat-job-inbox-item-body'>
                <span className='cvat-job-inbox-item-title'>
                    <Text strong>{`Job #${item.jobId}`}</Text>
                    <Tag color={EVENT_TAG_COLORS[item.event]} className='cvat-job-inbox-item-tag'>
                        {EVENT_LABELS[item.event]}
                    </Tag>
                    {!item.isRead && <span className='cvat-job-inbox-visually-hidden'>읽지 않음</span>}
                    <CVATTooltip overlay={created.format('YYYY-MM-DD HH:mm:ss')}>
                        <Text type='secondary' className='cvat-job-inbox-item-time'>
                            {created.locale('ko').fromNow()}
                        </Text>
                    </CVATTooltip>
                </span>
                <CVATTooltip overlay={subtitle}>
                    <Text className='cvat-job-inbox-item-task' ellipsis>{subtitle}</Text>
                </CVATTooltip>
            </span>
        </button>
    );
}
