// Copyright (C) 2020-2022 Intel Corporation
// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import './styles.scss';
import React, {
    Dispatch, useEffect, useMemo, useRef,
} from 'react';
import { AnyAction } from 'redux';
import { connect } from 'react-redux';
import { MenuFoldOutlined, MenuUnfoldOutlined } from '@ant-design/icons';
import Tabs from 'antd/lib/tabs';
import Layout from 'antd/lib/layout';

import { CombinedState, ObjectsSidebarTab } from 'reducers';
import { DimensionType } from 'cvat-core-wrapper';
import LabelsList from 'components/annotation-page/standard-workspace/objects-side-bar/labels-list';
import {
    collapseSidebar as collapseSidebarAction,
    setObjectsSidebarTab as setObjectsSidebarTabAction,
} from 'actions/annotation-actions';
import { summarizeIssues } from 'utils/issue-markers';
import AppearanceBlock from 'components/annotation-page/appearance-block';
import IssuesListComponent from 'components/annotation-page/standard-workspace/objects-side-bar/issues-list';

interface OwnProps {
    objectsList: JSX.Element;
}

interface StateToProps {
    sidebarCollapsed: boolean;
    sidebarActiveTab: ObjectsSidebarTab;
    jobInstance: any;
    issues: any[];
}

interface DispatchToProps {
    collapseSidebar(): void;
    setSidebarTab(tab: ObjectsSidebarTab): void;
}

function mapStateToProps(state: CombinedState): StateToProps {
    const {
        annotation: {
            sidebarCollapsed,
            sidebarActiveTab,
            job: { instance: jobInstance },
        },
        review: { issues },
    } = state;

    return {
        sidebarCollapsed,
        sidebarActiveTab,
        jobInstance,
        issues,
    };
}

function mapDispatchToProps(dispatch: Dispatch<AnyAction>): DispatchToProps {
    return {
        collapseSidebar(): void {
            dispatch(collapseSidebarAction());
        },
        setSidebarTab(tab: ObjectsSidebarTab): void {
            dispatch(setObjectsSidebarTabAction(tab));
        },
    };
}

function ObjectsSideBar(props: StateToProps & DispatchToProps & OwnProps): JSX.Element {
    const {
        sidebarCollapsed, sidebarActiveTab, collapseSidebar, setSidebarTab, objectsList, jobInstance, issues,
    } = props;

    // The canvas has to be fitted again once the sidebar width transition ends. This runs for
    // every collapse/expand, including the one triggered by an issue marker click on the player slider.
    const isFirstRender = useRef(true);
    useEffect(() => {
        if (isFirstRender.current) {
            isFirstRender.current = false;
            return undefined;
        }

        const [collapser] = window.document.getElementsByClassName('cvat-objects-sidebar');
        if (!collapser) {
            return undefined;
        }

        const listener = (event: Event): void => {
            const { target, propertyName } = event as TransitionEvent;
            if (target === collapser && propertyName === 'width') {
                window.dispatchEvent(new Event('resize'));
                collapser.removeEventListener('transitionend', listener);
            }
        };

        collapser.addEventListener('transitionend', listener);
        return () => collapser.removeEventListener('transitionend', listener);
    }, [sidebarCollapsed]);

    const { counts: issueCounts } = useMemo(() => summarizeIssues(issues), [issues]);

    const is2D = jobInstance ? jobInstance.dimension === DimensionType.DIMENSION_2D : true;
    const issuesLabel = (
        <span className='cvat-objects-sidebar-issues-tab-label'>
            Issues
            {issueCounts.total > 0 && (
                <span
                    className={`cvat-objects-sidebar-issues-badge ${
                        issueCounts.unresolved > 0 ? 'cvat-objects-sidebar-issues-badge-unresolved' : ''
                    }`}
                >
                    {`${issueCounts.unresolved}/${issueCounts.total}`}
                </span>
            )}
        </span>
    );

    return (
        <Layout.Sider
            className='cvat-objects-sidebar'
            theme='light'
            width={300}
            collapsedWidth={0}
            reverseArrow
            collapsible
            trigger={null}
            collapsed={sidebarCollapsed}
        >
            {/* eslint-disable-next-line */}
            <span
                className='cvat-objects-sidebar-sider'
                onClick={collapseSidebar}
            >
                {sidebarCollapsed ? <MenuFoldOutlined title='Show' /> : <MenuUnfoldOutlined title='Hide' />}
            </span>

            <Tabs
                type='card'
                activeKey={sidebarActiveTab === 'issues' && !is2D ? 'objects' : sidebarActiveTab}
                onChange={(key: string) => setSidebarTab(key as ObjectsSidebarTab)}
                className='cvat-objects-sidebar-tabs'
                items={[{
                    key: 'objects',
                    label: 'Objects',
                    children: objectsList,
                }, {
                    key: 'labels',
                    label: 'Labels',
                    forceRender: true,
                    children: <LabelsList />,
                }, ...(is2D ? [{ key: 'issues', label: issuesLabel, children: <IssuesListComponent /> }] : [])]}
            />
            {!sidebarCollapsed && <AppearanceBlock />}
        </Layout.Sider>
    );
}

export default connect(mapStateToProps, mapDispatchToProps)(React.memo(ObjectsSideBar));
