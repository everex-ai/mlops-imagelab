// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import './styles.scss';
import 'dayjs/locale/ko';
import React, { useCallback, useRef, useState } from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { useHistory } from 'react-router';
import { BellOutlined, InfoCircleOutlined } from '@ant-design/icons';
import Badge from 'antd/lib/badge';
import Button from 'antd/lib/button';
import Checkbox from 'antd/lib/checkbox';
import Popover from 'antd/lib/popover';
import Spin from 'antd/lib/spin';
import Text from 'antd/lib/typography/Text';
import message from 'antd/lib/message';

import { JobNotification } from 'cvat-core-wrapper';
import { CombinedState } from 'reducers';
import { changeFrameAsync } from 'actions/annotation-actions';
import CVATTooltip from 'components/common/cvat-tooltip';

import { requestBrowserNotificationPermission } from './browser-notifications';
import JobInboxItem from './job-inbox-item';
import { useJobInbox } from './use-job-inbox';

export default function JobInbox(): JSX.Element {
    const history = useHistory();
    const dispatch = useDispatch();
    const openedJobId = useSelector((state: CombinedState) => state.annotation.job.instance?.id ?? null);
    const openedJobIdRef = useRef(openedJobId);
    openedJobIdRef.current = openedJobId;

    const [open, setOpen] = useState(false);
    const [unreadOnly, setUnreadOnly] = useState(false);
    const bellRef = useRef<HTMLButtonElement>(null);

    const navigate = useCallback((item: JobNotification): void => {
        const path = `/tasks/${item.taskId}/jobs/${item.jobId}`;
        if (openedJobIdRef.current === item.jobId && history.location.pathname === path) {
            // The annotation page reads ?frame= only when it loads a job, so for the job
            // that is already open just move the player.
            dispatch(changeFrameAsync(item.targetFrame));
            return;
        }
        // For another job, the top bar's history.block() asks about unsaved changes, and
        // the page reloads the job (with ?frame=) once the route's job id changes.
        history.push(`${path}?frame=${item.targetFrame}`);
    }, [history, dispatch]);

    const inboxRef = useRef<ReturnType<typeof useJobInbox>>();
    const openItem = useCallback(async (item: JobNotification): Promise<void> => {
        setOpen(false);
        const result = await inboxRef.current?.markRead(item);
        if (result === 'gone') {
            message.warning('더 이상 접근할 수 없는 Job입니다');
            return;
        }
        navigate(item);
    }, [navigate]);

    const inbox = useJobInbox({ open, unreadOnly, onBrowserNotificationClick: openItem });
    inboxRef.current = inbox;
    const {
        unreadCount, items, loading, failed, reload, markAllRead,
    } = inbox;

    const onOpenChange = (nextOpen: boolean): void => {
        setOpen(nextOpen);
        if (nextOpen) {
            requestBrowserNotificationPermission();
        } else {
            bellRef.current?.focus();
        }
    };

    let list: React.ReactNode;
    if (items === null && loading) {
        list = <div className='cvat-job-inbox-state'><Spin /></div>;
    } else if (items === null && failed) {
        list = null;
    } else if (!items?.length) {
        list = (
            <div className='cvat-job-inbox-state'>
                <Text type='secondary'>{unreadOnly ? '안 읽은 알림이 없습니다' : '알림이 없습니다'}</Text>
            </div>
        );
    } else {
        list = items.map((item) => <JobInboxItem key={item.id} item={item} onClick={openItem} />);
    }

    const panel = (
        <div className='cvat-job-inbox-panel'>
            <div className='cvat-job-inbox-header'>
                <span className='cvat-job-inbox-header-title'>
                    <Text strong>알림</Text>
                    <Text type='secondary'>· 최신순</Text>
                    <CVATTooltip overlay='알림은 30일이 지나면 자동으로 삭제됩니다.'>
                        <InfoCircleOutlined className='cvat-job-inbox-info' />
                    </CVATTooltip>
                </span>
                <span className='cvat-job-inbox-header-actions'>
                    <Checkbox
                        checked={unreadOnly}
                        onChange={(event) => setUnreadOnly(event.target.checked)}
                    >
                        읽은 알림 제외
                    </Checkbox>
                    <Button type='link' size='small' disabled={!unreadCount} onClick={markAllRead}>
                        모두 읽음
                    </Button>
                </span>
            </div>
            {failed && (
                <div className='cvat-job-inbox-error'>
                    <Text type='danger'>불러오지 못했습니다</Text>
                    <Button type='link' size='small' onClick={reload}>다시 시도</Button>
                </div>
            )}
            <div className='cvat-job-inbox-list'>{list}</div>
        </div>
    );

    return (
        <Popover
            trigger='click'
            placement='bottomRight'
            open={open}
            onOpenChange={onOpenChange}
            content={panel}
            arrow={false}
            overlayClassName='cvat-job-inbox-popover'
        >
            <Button
                ref={bellRef}
                type='link'
                size='large'
                className='cvat-job-inbox-button cvat-header-button'
                aria-label={unreadCount ? `알림, 안 읽은 알림 ${unreadCount}개` : '알림'}
                icon={(
                    <Badge count={unreadCount} overflowCount={99} size='small'>
                        <BellOutlined />
                    </Badge>
                )}
            />
        </Popover>
    );
}
