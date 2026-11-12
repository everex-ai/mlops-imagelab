// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// INNO-158: decide whether a rectangle edit is a whole-rectangle move
// (unrotated before and after, width and height unchanged). Such a move is
// saved without fitting the points to the image, so a rectangle that was
// partly outside does not shrink on drop; resizes are still fitted.
//
// No imports and type annotations only, so `node --test` loads it directly.

export const RECT_SIZE_EPS = 1e-3;

export function isSizePreservingRectMove(
    before: { points: number[]; rotation: number } | null,
    after: { points: number[]; rotation: number },
): boolean {
    if (!before || before.rotation || after.rotation) {
        return false;
    }

    if (!Array.isArray(before.points) || !Array.isArray(after.points) ||
        before.points.length !== 4 || after.points.length !== 4) {
        return false;
    }

    const [xtl, ytl, xbr, ybr] = after.points;
    const [prevXtl, prevYtl, prevXbr, prevYbr] = before.points;
    return Math.abs((xbr - xtl) - (prevXbr - prevXtl)) < RECT_SIZE_EPS &&
        Math.abs((ybr - ytl) - (prevYbr - prevYtl)) < RECT_SIZE_EPS;
}

// A kept (unfitted) move must still respect the start-relative rule used by
// the canvas: every edge is inside the image or no further out than before.
// Saves from other paths (API, plugins) that push a rectangle out of the
// image therefore still get fitted.
export function isRectMoveWithinAllowedRange(
    before: { points: number[] },
    after: { points: number[] },
    imageWidth: number,
    imageHeight: number,
): boolean {
    const [xtl, ytl, xbr, ybr] = after.points;
    const [prevXtl, prevYtl, prevXbr, prevYbr] = before.points;
    return xtl >= Math.min(0, prevXtl) - RECT_SIZE_EPS &&
        ytl >= Math.min(0, prevYtl) - RECT_SIZE_EPS &&
        xbr <= Math.max(imageWidth, prevXbr) + RECT_SIZE_EPS &&
        ybr <= Math.max(imageHeight, prevYbr) + RECT_SIZE_EPS;
}
