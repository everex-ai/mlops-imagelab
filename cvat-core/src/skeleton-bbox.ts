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
    const width = Number.isFinite(imageWidth) ? imageWidth : Number.POSITIVE_INFINITY;
    const height = Number.isFinite(imageHeight) ? imageHeight : Number.POSITIVE_INFINITY;
    return [
        Math.max(keypoints.xmin - margin, Math.min(0, keypoints.xmin)),
        Math.max(keypoints.ymin - margin, Math.min(0, keypoints.ymin)),
        Math.min(keypoints.xmax + margin, Math.max(width, keypoints.xmax)),
        Math.min(keypoints.ymax + margin, Math.max(height, keypoints.ymax)),
    ];
}
