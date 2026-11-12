// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// Fallback skeleton bbox (INNO-158).
//
// When a skeleton has no usable bbox (never drawn, or the legacy [0,0,0,0]
// placeholder), cvat-core derives one from the keypoint extent plus a small
// visual margin. Every edge is clipped to the image, but never inside a
// keypoint that is already outside the image: the bbox always contains the
// keypoints.
//
// The file has no imports and uses type annotations only, so `node --test`
// can load it directly.

export const SKELETON_BBOX_FALLBACK_MARGIN = 20;

export interface KeypointExtent {
    xmin: number;
    ymin: number;
    xmax: number;
    ymax: number;
}

// Returns [xtl, ytl, xbr, ybr]. imageWidth/imageHeight may be missing
// (unknown frame size): the margin is then applied without clipping.
export function fallbackSkeletonBbox(
    keypoints: KeypointExtent,
    margin: number,
    imageWidth: number | undefined,
    imageHeight: number | undefined,
): number[] {
    const width = typeof imageWidth === 'number' && Number.isFinite(imageWidth) ? imageWidth : Number.POSITIVE_INFINITY;
    const height = typeof imageHeight === 'number' && Number.isFinite(imageHeight) ? imageHeight : Number.POSITIVE_INFINITY;
    return [
        Math.max(keypoints.xmin - margin, Math.min(0, keypoints.xmin)),
        Math.max(keypoints.ymin - margin, Math.min(0, keypoints.ymin)),
        Math.min(keypoints.xmax + margin, Math.max(width, keypoints.xmax)),
        Math.min(keypoints.ymax + margin, Math.max(height, keypoints.ymax)),
    ];
}

// INNO-158: clamp one moved point into the image (0..width, 0..height),
// start-relative: a point that started outside may stay there but not go
// further out. Applied to `outside` keypoints when a skeleton rotation is
// baked in: they do not limit the angle but must not leave the image.
export function clampMovedPoint(
    startX: number,
    startY: number,
    x: number,
    y: number,
    imageWidth: number | undefined,
    imageHeight: number | undefined,
): number[] {
    const width = typeof imageWidth === 'number' && Number.isFinite(imageWidth) ? imageWidth : Number.POSITIVE_INFINITY;
    const height = typeof imageHeight === 'number' && Number.isFinite(imageHeight) ? imageHeight : Number.POSITIVE_INFINITY;
    return [
        Math.min(Math.max(x, Math.min(0, startX)), Math.max(width, startX)),
        Math.min(Math.max(y, Math.min(0, startY)), Math.max(height, startY)),
    ];
}
