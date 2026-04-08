// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React, { useEffect, useState } from 'react';
import { shallowEqual, useDispatch, useSelector } from 'react-redux';
import Modal from 'antd/lib/modal';
import InputNumber from 'antd/lib/input-number';
import Text from 'antd/lib/typography/Text';
import Button from 'antd/lib/button';
import { Row, Col } from 'antd/lib/grid';
import Slider from 'antd/lib/slider';
import { clamp } from 'utils/math';
import { convertShapeToTrackAsync, switchConvertShapeToTrackVisibility } from 'actions/annotation-actions';
import { CombinedState } from 'reducers';

function ConvertToTrackConfirmComponent(): JSX.Element {
    const dispatch = useDispatch();
    const {
        visible,
        frameNumber,
        frameNumbers,
    } = useSelector((state: CombinedState) => ({
        visible: state.annotation.convertShapeToTrack.visible,
        frameNumber: state.annotation.player.frame.number,
        frameNumbers: state.annotation.job.frameNumbers,
    }), shallowEqual);

    const startFrame = frameNumbers.length ? frameNumbers[0] : 0;
    const stopFrame = frameNumbers.length ? frameNumbers[frameNumbers.length - 1] : 0;

    const [rangeStart, setRangeStart] = useState<number>(startFrame);
    const [rangeEnd, setRangeEnd] = useState<number>(frameNumber);

    // Reset to the default "Up to current" range whenever the modal opens
    useEffect(() => {
        if (visible) {
            setRangeStart(startFrame);
            setRangeEnd(frameNumber);
        }
    }, [visible]);

    // The source shape lives on the current frame; requiring the range to
    // contain it keeps the conversion's spatial meaning intuitive.
    const rangeContainsCurrent = rangeStart <= frameNumber && frameNumber <= rangeEnd;
    const rangeIsValid = rangeStart <= rangeEnd && rangeContainsCurrent;

    const setUpToCurrent = (): void => {
        setRangeStart(startFrame);
        setRangeEnd(frameNumber);
    };

    const setFromCurrent = (): void => {
        setRangeStart(frameNumber);
        setRangeEnd(stopFrame);
    };

    return (
        <Modal
            okType='primary'
            okText='Convert'
            cancelText='Cancel'
            onOk={() => {
                dispatch(convertShapeToTrackAsync(rangeStart, rangeEnd))
                    .then(() => dispatch(switchConvertShapeToTrackVisibility(false)));
            }}
            onCancel={() => dispatch(switchConvertShapeToTrackVisibility(false))}
            title='Convert shape to track'
            open={visible}
            destroyOnClose
            okButtonProps={{ disabled: !rangeIsValid }}
        >
            <div className='cvat-convert-to-track-confirm'>
                <Row>
                    <Col span={24}>
                        <Text>
                            A new track will be created with keyframes at the range boundaries,
                            matching the current shape&apos;s position. The original shape is removed.
                        </Text>
                    </Col>
                </Row>
                <Row style={{ marginTop: 12 }}>
                    <Col>
                        <Button
                            size='small'
                            onClick={setUpToCurrent}
                            disabled={frameNumber === startFrame}
                            className='cvat-convert-to-track-confirm-up-to-current'
                        >
                            Up to current
                        </Button>
                    </Col>
                    <Col offset={1}>
                        <Button
                            size='small'
                            onClick={setFromCurrent}
                            disabled={frameNumber === stopFrame}
                            className='cvat-convert-to-track-confirm-from-current'
                        >
                            From current
                        </Button>
                    </Col>
                </Row>
                <Row style={{ marginTop: 12 }} className='cvat-convert-to-track-range-wrapper'>
                    <Col span={24}>
                        <Text>Adjust the range:</Text>
                    </Col>
                    <Col span={14} offset={1} className='cvat-convert-to-track-slider-wrapper'>
                        <Slider
                            range
                            min={startFrame}
                            max={stopFrame}
                            marks={{
                                [frameNumber]: 'CURRENT',
                            }}
                            value={[rangeStart, rangeEnd] as [number, number]}
                            onChange={([value1, value2]: number[]) => {
                                setRangeStart(clamp(Math.min(value1, value2), startFrame, stopFrame));
                                setRangeEnd(clamp(Math.max(value1, value2), startFrame, stopFrame));
                            }}
                        />
                    </Col>
                </Row>
                <Row style={{ marginTop: 8 }}>
                    <Col>
                        <Text>Start frame</Text>
                    </Col>
                    <Col offset={1}>
                        <InputNumber
                            size='small'
                            className='cvat-convert-to-track-confirm-start-input'
                            min={startFrame}
                            max={rangeEnd}
                            value={rangeStart}
                            onChange={(value: number | null) => {
                                if (typeof value === 'number') {
                                    setRangeStart(clamp(Math.round(value), startFrame, rangeEnd));
                                }
                            }}
                        />
                    </Col>
                    <Col offset={2}>
                        <Text>End frame</Text>
                    </Col>
                    <Col offset={1}>
                        <InputNumber
                            size='small'
                            className='cvat-convert-to-track-confirm-end-input'
                            min={rangeStart}
                            max={stopFrame}
                            value={rangeEnd}
                            onChange={(value: number | null) => {
                                if (typeof value === 'number') {
                                    setRangeEnd(clamp(Math.round(value), rangeStart, stopFrame));
                                }
                            }}
                        />
                    </Col>
                </Row>
                {!rangeContainsCurrent && (
                    <Row style={{ marginTop: 8 }}>
                        <Col span={24}>
                            <Text type='danger'>
                                The range must contain the current frame (
                                {frameNumber}
                                ).
                            </Text>
                        </Col>
                    </Row>
                )}
            </div>
        </Modal>
    );
}

export default React.memo(ConvertToTrackConfirmComponent);
