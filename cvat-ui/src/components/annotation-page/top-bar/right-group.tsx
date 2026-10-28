// Copyright (C) 2020-2022 Intel Corporation
// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, {
    useEffect, useCallback, useRef, useState,
} from 'react';
import { useDispatch, useSelector } from 'react-redux';
import { Col } from 'antd/lib/grid';
import Icon, { InfoCircleOutlined } from '@ant-design/icons';
import Select from 'antd/lib/select';
import Button from 'antd/lib/button';
import Modal from 'antd/lib/modal';
import notification from 'antd/lib/notification';

import { FilterIcon, FullscreenIcon, GuideIcon } from 'icons';
import config from 'config';
import {
    Job, JobStage, JobState,
} from 'cvat-core-wrapper';
import { ActiveControl, CombinedState, Workspace } from 'reducers';
import { changeWorkspace as changeWorkspaceAction, getToggledReviewWorkspace } from 'actions/annotation-actions';
import { registerComponentShortcuts } from 'actions/shortcuts-actions';
import { ShortcutScope } from 'utils/enums';
import { subKeyMap } from 'utils/component-subkeymap';
import GlobalHotKeys from 'utils/mousetrap-react';
import { useIsReviewer } from 'utils/is-reviewer';

import MDEditor from '@uiw/react-md-editor';

interface Props {
    showStatistics(): void;
    showFilters(): void;
    changeWorkspace(workspace: Workspace): void;
    jobInstance: Job;
    workspace: Workspace;
    annotationFilters: object[];
    initialOpenGuide: boolean;
}

// INNO-125: registered globally so F2 customization is saved/restored like any other shortcut,
// but bound, listed and displayed only for reviewers (see utils/is-reviewer.ts)
const componentShortcuts = {
    SWITCH_STANDARD_REVIEW_WORKSPACE: {
        name: 'Switch Standard/Review',
        description: 'Switch the workspace between Standard and Review (reviewers only)',
        sequences: ['z'],
        scope: ShortcutScope.ANNOTATION_PAGE,
    },
};

registerComponentShortcuts(componentShortcuts);

const TOGGLE_HIGHLIGHT_MS = 500;

function formatSequences(sequences: string[]): string {
    return sequences.map((sequence) => sequence.split('+')
        .map((key) => key.charAt(0).toUpperCase() + key.slice(1)).join('+')).join(', ');
}

function RightGroup(props: Props): JSX.Element {
    const {
        showStatistics,
        changeWorkspace,
        showFilters,
        workspace,
        jobInstance,
        annotationFilters,
        initialOpenGuide,
    } = props;

    const filters = annotationFilters.length;

    const dispatch = useDispatch();
    const isReviewer = useIsReviewer();
    const keyMap = useSelector((state: CombinedState) => state.shortcuts.keyMap);
    const activeControl = useSelector((state: CombinedState) => state.annotation.canvas.activeControl);
    const toggleSequences = keyMap.SWITCH_STANDARD_REVIEW_WORKSPACE?.sequences ?? [];
    const toggleKeyHint = isReviewer ? formatSequences(toggleSequences) : '';

    const toggleRequestedRef = useRef(false);
    const pointerPressedRef = useRef(false);
    const highlightTimeoutRef = useRef<number | null>(null);
    const [highlighted, setHighlighted] = useState(false);

    useEffect(() => {
        if (!toggleRequestedRef.current) {
            return;
        }

        // workspace changed because of the toggle shortcut: highlight the selector briefly
        toggleRequestedRef.current = false;
        if (highlightTimeoutRef.current !== null) {
            window.clearTimeout(highlightTimeoutRef.current);
        }
        setHighlighted(true);
        highlightTimeoutRef.current = window.setTimeout(() => {
            highlightTimeoutRef.current = null;
            setHighlighted(false);
        }, TOGGLE_HIGHLIGHT_MS);
    }, [workspace]);

    useEffect(() => () => {
        if (highlightTimeoutRef.current !== null) {
            window.clearTimeout(highlightTimeoutRef.current);
        }
    }, []);

    useEffect(() => {
        // a shape drag/resize keeps the CURSOR control, so track the pointer to avoid switching mid-gesture
        const onDown = (): void => { pointerPressedRef.current = true; };
        const onUp = (): void => { pointerPressedRef.current = false; };
        window.addEventListener('pointerdown', onDown, true);
        window.addEventListener('pointerup', onUp, true);
        window.addEventListener('pointercancel', onUp, true);
        window.addEventListener('blur', onUp);
        return () => {
            window.removeEventListener('pointerdown', onDown, true);
            window.removeEventListener('pointerup', onUp, true);
            window.removeEventListener('pointercancel', onUp, true);
            window.removeEventListener('blur', onUp);
        };
    }, []);

    const onWorkspaceSelected = useCallback((ws: Workspace): void => {
        changeWorkspace(ws);
        // antd keeps focus in the Select search input after a choice, which makes Mousetrap ignore
        // every shortcut (including the toggle) until the user clicks elsewhere
        window.setTimeout(() => {
            const { activeElement } = window.document;
            if (activeElement instanceof HTMLElement && activeElement.closest('.cvat-workspace-selector')) {
                activeElement.blur();
            }
        });
    }, [changeWorkspace]);

    const handlers = {
        SWITCH_STANDARD_REVIEW_WORKSPACE: (event: KeyboardEvent) => {
            if (event?.repeat || pointerPressedRef.current) {
                return;
            }

            // the same guard as the CHANGE_WORKSPACE reducer, so the highlight only follows a real switch
            if (activeControl !== ActiveControl.CURSOR && workspace !== Workspace.SINGLE_SHAPE) {
                return;
            }

            toggleRequestedRef.current = true;
            dispatch(changeWorkspaceAction(getToggledReviewWorkspace(workspace), { preserveSelection: true }));
            if (window.document.activeElement) {
                (window.document.activeElement as HTMLElement).blur();
            }
        },
    };

    const openGuide = useCallback(() => {
        const PADDING = Math.min(window.screen.availHeight, window.screen.availWidth) * 0.4;
        jobInstance.guide().then((guide) => {
            if (guide) {
                Modal.info({
                    icon: null,
                    width: window.screen.availWidth - PADDING,
                    className: 'cvat-annotation-view-markdown-guide-modal',
                    content: (
                        <MDEditor
                            visibleDragbar={false}
                            data-color-mode='light'
                            height={window.screen.availHeight - PADDING}
                            preview='preview'
                            hideToolbar
                            value={guide.markdown}
                        />
                    ),
                });
            }
        }).catch((error: unknown) => {
            notification.error({
                message: 'Could not receive annotation guide',
                description: error instanceof Error ? error.message : console.error('error'),
            });
        });
    }, [jobInstance]);

    useEffect(() => {
        if (Number.isInteger(jobInstance?.guideId)) {
            if (initialOpenGuide) {
                openGuide();
            } else if (
                jobInstance?.stage === JobStage.ANNOTATION &&
                jobInstance?.state === JobState.NEW
            ) {
                let seenGuides = [];
                try {
                    seenGuides = JSON.parse(localStorage.getItem('seenGuides') || '[]');
                    if (!Array.isArray(seenGuides) || seenGuides.some((el) => !Number.isInteger(el))) {
                        throw new Error('Wrong structure stored in local storage');
                    }
                } catch (error: unknown) {
                    seenGuides = [];
                }

                if (!seenGuides.includes(jobInstance.guideId)) {
                    // open guide if the user have not seen it yet
                    openGuide();
                    const updatedSeenGuides = Array
                        .from(new Set([
                            jobInstance.guideId,
                            ...seenGuides.slice(0, config.LOCAL_STORAGE_SEEN_GUIDES_MEMORY_LIMIT - 1),
                        ]));
                    localStorage.setItem('seenGuides', JSON.stringify(updatedSeenGuides));
                }
            }
        }
    }, []);

    return (
        <Col className='cvat-annotation-header-right-group'>
            {isReviewer && (
                <GlobalHotKeys keyMap={subKeyMap(componentShortcuts, keyMap)} handlers={handlers} />
            )}
            <Button
                type='link'
                className='cvat-annotation-header-fullscreen-button cvat-annotation-header-button'
                onClick={(): void => {
                    if (window.document.fullscreenEnabled) {
                        if (window.document.fullscreenElement) {
                            window.document.exitFullscreen();
                        } else {
                            window.document.documentElement.requestFullscreen();
                        }
                    }
                }}
            >
                <Icon component={FullscreenIcon} />
                Fullscreen
            </Button>
            { jobInstance.guideId !== null && (
                <Button
                    type='link'
                    className='cvat-annotation-header-guide-button cvat-annotation-header-button'
                    onClick={openGuide}
                >
                    <Icon component={GuideIcon} />
                    Guide
                </Button>
            )}
            <Button
                type='link'
                className='cvat-annotation-header-info-button cvat-annotation-header-button'
                onClick={showStatistics}
            >
                <InfoCircleOutlined />
                Info
            </Button>
            <Button
                type='link'
                className={`cvat-annotation-header-filters-button cvat-annotation-header-button ${filters ?
                    'filters-armed' : ''
                }`}
                onClick={showFilters}
            >
                <Icon component={FilterIcon} />
                Filters
            </Button>
            <div>
                <Select
                    popupClassName='cvat-workspace-selector-dropdown'
                    className={`cvat-workspace-selector${highlighted ? ' cvat-workspace-selector-toggled' : ''}`}
                    onChange={onWorkspaceSelected}
                    value={workspace}
                    optionLabelProp='title'
                >
                    {Object.values(Workspace).map((ws) => (
                        <Select.Option key={ws} value={ws} title={ws}>
                            {ws}
                            {toggleKeyHint && (ws === Workspace.STANDARD || ws === Workspace.REVIEW) && (
                                <span className='cvat-workspace-selector-shortcut'>{toggleKeyHint}</span>
                            )}
                        </Select.Option>
                    ))}
                </Select>
            </div>
        </Col>
    );
}

export default React.memo(RightGroup);
