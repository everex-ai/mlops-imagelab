// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { Canvas } from 'cvat-canvas-wrapper';
import { ActiveControl } from 'reducers';

export function finishDrawAvailable(activeControl: ActiveControl): boolean {
    return [
        ActiveControl.DRAW_POLYGON,
        ActiveControl.DRAW_POLYLINE,
        ActiveControl.DRAW_POINTS,
        ActiveControl.AI_TOOLS,
        ActiveControl.OPENCV_TOOLS,
    ].includes(activeControl);
}

export function finishDraw(canvas: Canvas, activeControl: ActiveControl): void {
    if ([ActiveControl.AI_TOOLS, ActiveControl.OPENCV_TOOLS].includes(activeControl)) {
        canvas.interact({ enabled: false });
        return;
    }

    canvas.draw({ enabled: false });
}
