// Copyright (C) 2022 Intel Corporation
// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useCallback, useEffect, useState } from 'react';
import { shallowEqual, useDispatch, useSelector } from 'react-redux';
import { CombinedState } from 'reducers';
import Text from 'antd/lib/typography/Text';
import Modal from 'antd/lib/modal';

import config from 'config';
import {
    removeObjectAsync,
    removeObject as removeObjectAction,
    removeObjectsAsync,
    removeObjects as removeObjectsAction,
} from 'actions/annotation-actions';
import { ObjectType } from 'cvat-core-wrapper';

export default function RemoveConfirmComponent(): JSX.Element | null {
    const dispatch = useDispatch();
    const [visible, setVisible] = useState(false);
    const [title, setTitle] = useState('');
    const [description, setDescription] = useState<string | JSX.Element>('');
    const { objectState, objectStates, force } = useSelector((state: CombinedState) => ({
        objectState: state.annotation.remove.objectState,
        objectStates: state.annotation.remove.objectStates,
        force: state.annotation.remove.force,
    }), shallowEqual);

    const onOk = useCallback(() => {
        if (objectStates && objectStates.length > 0) {
            dispatch(removeObjectsAsync(objectStates, true));
        } else if (objectState) {
            dispatch(removeObjectAsync(objectState, true));
        }
    }, [objectState, objectStates]);

    const onCancel = useCallback(() => {
        if (objectStates) {
            dispatch(removeObjectsAction([], false));
        } else {
            dispatch(removeObjectAction(null, false));
        }
    }, [objectStates]);

    useEffect(() => {
        // Multi-delete path
        if (objectStates && objectStates.length > 0) {
            const hasLocked = objectStates.some((s: any) => s.lock);
            const hasTracks = objectStates.some((s: any) => s.objectType === ObjectType.TRACK);
            const needsConfirm = (hasLocked && !force) || (hasTracks && !force);

            if (needsConfirm) {
                setTitle(hasLocked ? 'Some objects are locked' : 'Remove objects');
                let msg: string | JSX.Element = `Are you sure you want to remove ${objectStates.length} objects?`;
                if (hasTracks) {
                    msg = (
                        <>
                            <Text>
                                {`You are about to remove ${objectStates.length} objects, including tracks. `}
                                {'Tracks remove many drawn objects on different frames. '}
                                {msg}
                            </Text>
                            <div className='cvat-remove-object-confirm-wrapper'>
                                {/* eslint-disable-next-line */}
                                <img src={config.OUTSIDE_PIC_URL} />
                            </div>
                        </>
                    );
                }
                setDescription(msg);
                setVisible(true);
            } else {
                setVisible(false);
                dispatch(removeObjectsAsync(objectStates, true));
            }
            return;
        }

        // Single-delete path (original)
        const newVisible = (!!objectState && !force && objectState.lock) ||
            (objectState?.objectType === ObjectType.TRACK && !force);
        setTitle(objectState?.lock ? 'Object is locked' : 'Remove object');
        let descriptionMessage: string | JSX.Element = 'Are you sure you want to remove it?';

        if (objectState?.objectType === ObjectType.TRACK && !force) {
            descriptionMessage = (
                <>
                    <Text>
                        {
                            `The object you are trying to remove is a track.
                            If you continue, it removes many drawn objects on different frames.
                            If you want to hide it only on this frame, use the outside feature instead.
                            ${descriptionMessage}`
                        }
                    </Text>
                    <div className='cvat-remove-object-confirm-wrapper'>
                        {/* eslint-disable-next-line */}
                        <img src={config.OUTSIDE_PIC_URL} />
                    </div>
                </>
            );
        }

        setDescription(descriptionMessage);
        setVisible(newVisible);
        if (!newVisible && objectState) {
            dispatch(removeObjectAsync(objectState, true));
        }
    }, [objectState, objectStates, force]);

    return (
        <Modal
            okType='primary'
            okText='Yes'
            cancelText='Cancel'
            title={title}
            open={visible}
            cancelButtonProps={{
                autoFocus: true,
            }}
            onOk={onOk}
            onCancel={onCancel}
            destroyOnClose
            className='cvat-modal-confirm-remove-object'
        >
            <div>
                {description}
            </div>
        </Modal>
    );
}
