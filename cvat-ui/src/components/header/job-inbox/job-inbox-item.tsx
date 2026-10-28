// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';
import Tag from 'antd/lib/tag';
import Text from 'antd/lib/typography/Text';

import { JobNotification, JobNotificationEvent } from 'cvat-core-wrapper';
import CVATTooltip from 'components/common/cvat-tooltip';
import dayjs from 'utils/dayjs-wrapper';

import { EVENT_LABELS, EVENT_TAG_COLORS, actorName } from './labels';

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

    return (
        <button type='button' className={className} onClick={() => onClick(item)}>
            <span className='cvat-job-inbox-item-dot' aria-hidden />
            <span className='cvat-job-inbox-item-body'>
                <span className='cvat-job-inbox-item-title'>
                    <Text strong>{`#${item.jobId}`}</Text>
                    <Tag color={EVENT_TAG_COLORS[item.event]} className='cvat-job-inbox-item-tag'>
                        {EVENT_LABELS[item.event]}
                    </Tag>
                    {!item.isRead && <span className='cvat-job-inbox-visually-hidden'>읽지 않음</span>}
                </span>
                <CVATTooltip overlay={item.taskName}>
                    <Text className='cvat-job-inbox-item-task' ellipsis>{item.taskName}</Text>
                </CVATTooltip>
                <span className='cvat-job-inbox-item-meta'>
                    {/* 가정 Q5(사용자 확인 대기): the actor is shown on 작업 완료 only */}
                    {item.event === JobNotificationEvent.SUBMITTED && item.actor && (
                        <Text type='secondary'>{`${actorName(item.actor)} · `}</Text>
                    )}
                    <CVATTooltip overlay={created.format('YYYY-MM-DD HH:mm:ss')}>
                        <Text type='secondary'>{created.locale('ko').fromNow()}</Text>
                    </CVATTooltip>
                </span>
            </span>
        </button>
    );
}
