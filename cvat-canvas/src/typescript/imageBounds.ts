// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// Pure helpers that keep edits inside the image (INNO-158).
//
// The file intentionally has no imports and uses type annotations only (no
// enums, no parameter properties), so `node --test` can load it directly with
// Node's built-in type stripping. It is the shared contract between INNO-158
// (single/multi drag, keypoints, bbox handles, rotation, skeleton drawing) and
// the INNO-156 keypoint group drag (`GroupDragSession.constrain` calls
// `clampGroupDelta`).
//
// Core rule — "allowed range relative to the start position": every moving
// item may move by dx in [min(0, bounds.xmin - xmin), max(0, bounds.xmax - xmax)]
// (same for y), where xmin/xmax are the item's extent when the gesture started.
// Every range contains 0, so an object that is already partly outside never
// jumps when grabbed; it is only stopped from going further out. Axes are
// clamped independently, so the item slides along a wall.

export interface Bounds {
    xmin: number;
    ymin: number;
    xmax: number;
    ymax: number;
}

// Same shape as Bounds: the extent of a moving item at gesture start.
// A keypoint is a zero-size extent (xmin === xmax, ymin === ymax).
export type Extent = Bounds;

export interface Delta {
    dx: number;
    dy: number;
}

// The current image in canvas coordinates: [offset, offset + size],
// borders inclusive (same convention as cvat-core fitPoints).
export function boundsFromGeometry(geometry: {
    offset: number;
    image: { width: number; height: number };
}): Bounds {
    return {
        xmin: geometry.offset,
        ymin: geometry.offset,
        xmax: geometry.offset + geometry.image.width,
        ymax: geometry.offset + geometry.image.height,
    };
}

function clampValue(value: number, min: number, max: number): number {
    return Math.min(Math.max(value, min), max);
}

// Clamp a raw delta (dx, dy) so that every extent, moved by the same delta,
// stays inside the bounds (or does not go further out than it started).
// With an empty extents list the raw delta is returned unchanged.
export function clampGroupDelta(extents: Extent[], dx: number, dy: number, bounds: Bounds): Delta {
    let loX = Number.NEGATIVE_INFINITY;
    let hiX = Number.POSITIVE_INFINITY;
    let loY = Number.NEGATIVE_INFINITY;
    let hiY = Number.POSITIVE_INFINITY;

    for (const extent of extents) {
        loX = Math.max(loX, Math.min(0, bounds.xmin - extent.xmin));
        hiX = Math.min(hiX, Math.max(0, bounds.xmax - extent.xmax));
        loY = Math.max(loY, Math.min(0, bounds.ymin - extent.ymin));
        hiY = Math.min(hiY, Math.max(0, bounds.ymax - extent.ymax));
    }

    return {
        dx: clampValue(dx, loX, hiX),
        dy: clampValue(dy, loY, hiY),
    };
}

// Clamp a resized box edge-wise. Every edge may lie within
// [min(boundsMin, startValue), max(boundsMax, startValue)]: an edge that
// started outside the image may stay there (or move inwards) but cannot go
// further out, an edge that started inside stops at the image border.
export function clampEdges(start: Extent, proposed: Extent, bounds: Bounds): Extent {
    const clampEdge = (value: number, startValue: number, min: number, max: number): number => (
        clampValue(value, Math.min(min, startValue), Math.max(max, startValue))
    );

    return {
        xmin: clampEdge(proposed.xmin, start.xmin, bounds.xmin, bounds.xmax),
        ymin: clampEdge(proposed.ymin, start.ymin, bounds.ymin, bounds.ymax),
        xmax: clampEdge(proposed.xmax, start.xmax, bounds.xmin, bounds.xmax),
        ymax: clampEdge(proposed.ymax, start.ymax, bounds.ymin, bounds.ymax),
    };
}

// svg.js reports a rotation in (-270, 90], so a continuous clockwise gesture
// of 120 degrees reads as -240. Map the raw angle to the equivalent angle
// (raw + 360k) closest to the previous unwrapped angle, producing a
// continuous signed gesture angle.
export function unwrapAngle(raw: number, prevUnwrapped: number): number {
    const k = Math.round((prevUnwrapped - raw) / 360);
    return raw + 360 * k;
}

// Rotation formula shared with cvat-canvas `rotate2DPoints` and cvat-core
// `saveRotation`: positive angles turn clockwise on screen (y axis down).
function rotatePoint(x: number, y: number, pivotX: number, pivotY: number, angle: number): [number, number] {
    const rad = (Math.PI / 180) * angle;
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);
    return [
        (x - pivotX) * cos - (y - pivotY) * sin + pivotX,
        (y - pivotY) * cos + (x - pivotX) * sin + pivotY,
    ];
}

// Small tolerance so that points sitting exactly on the border are not
// rejected because of floating point noise of sin/cos.
const ROTATION_EPS = 1e-6;

function rotationFits(points: number[], pivotX: number, pivotY: number, angle: number, bounds: Bounds): boolean {
    for (let i = 0; i < points.length; i += 2) {
        const x = points[i];
        const y = points[i + 1];
        const [rx, ry] = rotatePoint(x, y, pivotX, pivotY, angle);
        if (
            rx < Math.min(bounds.xmin, x) - ROTATION_EPS ||
            rx > Math.max(bounds.xmax, x) + ROTATION_EPS ||
            ry < Math.min(bounds.ymin, y) - ROTATION_EPS ||
            ry > Math.max(bounds.ymax, y) + ROTATION_EPS
        ) {
            return false;
        }
    }
    return true;
}

// Clamp a (continuous, unwrapped) rotation angle in whole degrees.
// Starting from 0, the points (flat [x1, y1, x2, y2, ...] start coordinates)
// are rotated around the pivot one degree at a time in the direction of the
// requested angle; the last integer angle at which every point stays inside
// its allowed range (start-relative, see clampEdges) is returned.
// The result is always an integer with |result| <= |round(angle)|.
export function clampRotationAngle(
    points: number[],
    pivotX: number,
    pivotY: number,
    angle: number,
    bounds: Bounds,
): number {
    const target = Math.round(angle);
    const step = target < 0 ? -1 : 1;
    let allowed = 0;
    for (let candidate = step; Math.abs(candidate) <= Math.abs(target); candidate += step) {
        if (!rotationFits(points, pivotX, pivotY, candidate, bounds)) {
            break;
        }
        allowed = candidate;
    }
    return allowed;
}

// Clamp a rectangle being drawn to the bounds. Width/height never become
// negative (a rect completely outside collapses onto the border).
export function clampRect(
    rect: { x: number; y: number; width: number; height: number },
    bounds: Bounds,
): { x: number; y: number; width: number; height: number } {
    const xmin = clampValue(rect.x, bounds.xmin, bounds.xmax);
    const ymin = clampValue(rect.y, bounds.ymin, bounds.ymax);
    const xmax = clampValue(rect.x + rect.width, bounds.xmin, bounds.xmax);
    const ymax = clampValue(rect.y + rect.height, bounds.ymin, bounds.ymax);
    return {
        x: xmin,
        y: ymin,
        width: Math.max(0, xmax - xmin),
        height: Math.max(0, ymax - ymin),
    };
}

// Snap image-space coordinates (flat [x1, y1, x2, y2, ...]) that lie within
// eps outside the image onto the border. Only float noise is affected;
// real out-of-image values (existing data) are kept.
export function snapNearBorder(points: number[], width: number, height: number, eps = 1e-3): number[] {
    return points.map((value: number, idx: number): number => {
        const max = idx % 2 === 0 ? width : height;
        if (value < 0 && value > -eps) return 0;
        if (value > max && value < max + eps) return max;
        return value;
    });
}

// Clamp one point that moved from (startX, startY) to (x, y) into the image,
// start-relative: a point that started outside may stay there but not go
// further out. Used for `outside` skeleton keypoints, which are excluded from
// the group limit (they must never block a drag or rotation) but must not be
// carried out of the image either: they get pushed along the border.
export function clampMovedPoint(
    startX: number,
    startY: number,
    x: number,
    y: number,
    bounds: Bounds,
): [number, number] {
    return [
        clampValue(x, Math.min(bounds.xmin, startX), Math.max(bounds.xmax, startX)),
        clampValue(y, Math.min(bounds.ymin, startY), Math.max(bounds.ymax, startY)),
    ];
}

// Drag-start extent of a skeleton group member (INNO-156/158): its wrapping
// rect when it moves as a whole, plus every moving keypoint that is not
// `outside` (those are clamped one by one with clampMovedPoint instead).
// Null when nothing limits the member.
export function skeletonMemberExtent(
    rect: { xtl: number; ytl: number; xbr: number; ybr: number } | null,
    keypoints: { cx: number; cy: number; outside: boolean }[],
): Extent | null {
    const xs: number[] = [];
    const ys: number[] = [];
    if (rect) {
        xs.push(rect.xtl, rect.xbr);
        ys.push(rect.ytl, rect.ybr);
    }
    for (const { cx, cy, outside } of keypoints) {
        if (outside) continue;
        xs.push(cx);
        ys.push(cy);
    }
    if (!xs.length) return null;
    return {
        xmin: Math.min(...xs), ymin: Math.min(...ys), xmax: Math.max(...xs), ymax: Math.max(...ys),
    };
}

// Rotate a delta by `degrees` (SVG convention: positive is clockwise on screen,
// y axis down). svg.draggable measures a drag in the dragged element's own
// frame, which for a rotated shape is rotated by its `rotate` transform:
// rotateDelta(local, +rotation) gives the canvas-axis delta, and
// rotateDelta(canvas, -rotation) maps it back. Exact for 0 degrees.
export function rotateDelta(dx: number, dy: number, degrees: number): Delta {
    if (!degrees) return { dx, dy };
    const rad = (degrees * Math.PI) / 180;
    const cos = Math.cos(rad);
    const sin = Math.sin(rad);
    return {
        dx: dx * cos - dy * sin,
        dy: dx * sin + dy * cos,
    };
}
