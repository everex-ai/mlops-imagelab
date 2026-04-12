// Copyright (C) 2020-2022 Intel Corporation
// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import React from 'react';
import Icon from '@ant-design/icons';

import { GroupIcon } from 'icons';
import CVATTooltip from 'components/common/cvat-tooltip';
import { useSelector } from 'react-redux';
import { CombinedState } from 'reducers';
import { Canvas } from 'cvat-canvas-wrapper';

export interface Props {
    disabled?: boolean;
    dynamicIconProps: Record<string, any>;
    canvasInstance: Canvas;
}

function GroupControl(props: Props): JSX.Element {
    const {
        disabled,
        dynamicIconProps,
    } = props;

    const { normalizedKeyMap } = useSelector((state: CombinedState) => state.shortcuts);

    const title = [];
    title.push(`Group shapes ${normalizedKeyMap.SWITCH_GROUP_MODE_STANDARD_CONTROLS}`);
    title.push(`Select and press ${normalizedKeyMap.RESET_GROUP_STANDARD_CONTROLS} to reset a group.`);

    return disabled ? (
        <Icon className='cvat-group-control cvat-disabled-canvas-control' component={GroupIcon} />
    ) : (
        <CVATTooltip title={title.join(' ')} placement='right'>
            <Icon {...dynamicIconProps} component={GroupIcon} />
        </CVATTooltip>
    );
}

export default React.memo(GroupControl);
