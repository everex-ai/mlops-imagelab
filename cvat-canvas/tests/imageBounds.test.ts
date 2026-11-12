// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// Run with: yarn workspace cvat-canvas run test:unit  (node --test, no build)

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    clampGroupDelta, clampEdges, unwrapAngle, clampRotationAngle, clampRect, snapNearBorder, clampMovedPoint,
} from '../src/typescript/imageBounds.ts';

const B = {
    xmin: 0, ymin: 0, xmax: 1920, ymax: 1080,
};
const box = (xmin: number, ymin: number, xmax: number, ymax: number) => ({
    xmin, ymin, xmax, ymax,
});

test('clampGroupDelta: stops at the wall per axis and slides along it (AE4)', () => {
    assert.deepEqual(clampGroupDelta([box(100, 100, 400, 300)], -500, 50, B), { dx: -100, dy: 50 });
    assert.deepEqual(clampGroupDelta([box(100, 100, 400, 300)], -500, -500, B), { dx: -100, dy: -100 });
});

test('clampGroupDelta: the whole group stops when one member hits the border (AE5)', () => {
    const extents = [box(100, 100, 400, 500), box(1500, 100, 1800, 500)];
    assert.deepEqual(clampGroupDelta(extents, 300, 0, B), { dx: 120, dy: 0 });
});

test('clampGroupDelta: already-outside extent never jumps and only blocks outwards (AE7)', () => {
    const outside = [box(-15, 100, 300, 400)];
    assert.equal(clampGroupDelta(outside, -10, 0, B).dx, 0);
    assert.equal(clampGroupDelta(outside, 50, 0, B).dx, 50);
    assert.equal(clampGroupDelta(outside, 0, 0, B).dx, 0);
});

test('clampGroupDelta: partially-outside extent moved inwards stays partially outside (AE8)', () => {
    assert.equal(clampGroupDelta([box(-30, 0, 270, 200)], 10, 0, B).dx, 10);
});

test('clampGroupDelta: zero-size keypoint extent stops at 0 and does not jump back (AE3)', () => {
    const kp = [box(5, 500, 5, 500)];
    assert.equal(clampGroupDelta(kp, -20, 0, B).dx, -5);
    assert.equal(clampGroupDelta(kp, -3, 0, B).dx, -3);
});

test('clampGroupDelta: extent touching the border', () => {
    const touching = [box(1600, 100, 1920, 300)];
    assert.equal(clampGroupDelta(touching, 1, 0, B).dx, 0);
    assert.equal(clampGroupDelta(touching, -1, 0, B).dx, -1);
});

test('clampGroupDelta: empty extents list returns the raw delta', () => {
    assert.deepEqual(clampGroupDelta([], -5000, 7000, B), { dx: -5000, dy: 7000 });
});

test('clampGroupDelta: bounds with a canvas offset', () => {
    const shifted = {
        xmin: 1000, ymin: 1000, xmax: 2920, ymax: 2080,
    };
    assert.deepEqual(clampGroupDelta([box(1010, 1010, 1100, 1100)], -50, 2000, shifted), { dx: -10, dy: 980 });
});

test('clampEdges: corner handle dragged outside stops at the corner (AE2)', () => {
    const start = box(1500, 700, 1800, 1000);
    assert.deepEqual(clampEdges(start, box(1500, 700, 2000, 1100), B), box(1500, 700, 1920, 1080));
});

test('clampEdges: an edge that started outside may stay there but not go further', () => {
    const start = box(-15, 100, 300, 400);
    assert.equal(clampEdges(start, box(-20, 100, 300, 400), B).xmin, -15);
    assert.equal(clampEdges(start, box(0, 100, 300, 400), B).xmin, 0);
    assert.equal(clampEdges(start, box(-10, 100, 300, 400), B).xmin, -10);
});

test('clampEdges: edges inside the image are untouched', () => {
    const start = box(100, 100, 300, 300);
    assert.deepEqual(clampEdges(start, box(50, 80, 350, 400), B), box(50, 80, 350, 400));
});

test('unwrapAngle: keeps a continuous signed gesture angle', () => {
    assert.equal(unwrapAngle(-265, 85), 95);
    assert.equal(unwrapAngle(-240, 95), 120);
    assert.equal(unwrapAngle(-20, -10), -20);
    assert.equal(unwrapAngle(10, 0), 10);
    assert.equal(unwrapAngle(-170, -150), -170);
});

test('clampRotationAngle: stops at the last integer angle before a keypoint leaves (AE9)', () => {
    // pivot (1700, 500), shoulder at (1900, 500): radius 200, rotating
    // clockwise moves the point down-left, so use a point above the pivot:
    // (1700, 300) rotated clockwise by a goes to (1700 + 200 sin a, 500 - 200 cos a).
    // x <= 1920 holds for all angles; use a tighter wall instead.
    const bounds = {
        xmin: 0, ymin: 0, xmax: 1800, ymax: 1080,
    };
    const points = [1700, 300];
    // 1700 + 200 sin(a) <= 1800  =>  sin(a) <= 0.5  =>  a <= 30
    assert.equal(clampRotationAngle(points, 1700, 500, 45, bounds), 30);
    assert.equal(clampRotationAngle(points, 1700, 500, 120, bounds), 30);
    // the opposite direction moves the point left — unconstrained
    assert.equal(clampRotationAngle(points, 1700, 500, -45, bounds), -45);
    assert.equal(clampRotationAngle(points, 1700, 500, 0, bounds), 0);
    // non-integer requests are rounded
    assert.equal(clampRotationAngle(points, 1700, 500, 12.4, bounds), 12);
});

test('clampRotationAngle: an already-outside point may not go further out', () => {
    // point at x = -5 above the pivot; rotating counter-clockwise (negative)
    // moves it further left, clockwise moves it right (inwards)
    const points = [-5, 300];
    const pivotX = -5;
    const pivotY = 500;
    assert.equal(clampRotationAngle(points, pivotX, pivotY, -10, B), 0);
    assert.equal(clampRotationAngle(points, pivotX, pivotY, 10, B), 10);
});

test('clampRotationAngle: no points means no constraint', () => {
    assert.equal(clampRotationAngle([], 0, 0, 77, B), 77);
});

test('clampRect: drawing rect stops at the border (AE1)', () => {
    assert.deepEqual(clampRect({
        x: 1900, y: 500, width: 200, height: 300,
    }, B), {
        x: 1900, y: 500, width: 20, height: 300,
    });
    assert.deepEqual(clampRect({
        x: -50, y: 100, width: 150, height: 100,
    }, B), {
        x: 0, y: 100, width: 100, height: 100,
    });
    assert.deepEqual(clampRect({
        x: 2000, y: 100, width: 50, height: 100,
    }, B).width, 0);
});

test('clampGroupDelta: mixed inside/outside group', () => {
    const extents = [box(-15, 100, 300, 400), box(1500, 100, 1800, 400)];
    assert.equal(clampGroupDelta(extents, -10, 0, B).dx, 0);
    assert.equal(clampGroupDelta(extents, 500, 0, B).dx, 120);
});

test('unwrap + clamp: a gesture stuck at a wall never flips to the other side', () => {
    const bounds = {
        xmin: 0, ymin: 0, xmax: 1800, ymax: 1080,
    };
    const points = [1700, 300];
    // svg.js raw angles of a continuous clockwise gesture 20 -> 160 degrees
    let prev = 0;
    for (const raw of [20, 60, 90, -270, -240, -200]) {
        prev = unwrapAngle(raw, prev);
        const clamped = clampRotationAngle(points, 1700, 500, prev, bounds);
        assert.ok(clamped >= 0 && clamped <= 30, `raw ${raw} -> unwrapped ${prev} -> ${clamped}`);
        if (prev >= 30) assert.equal(clamped, 30);
    }
    assert.equal(prev, 160);
});

test('clampRotationAngle: negative direction blocked by the left wall, second point limits', () => {
    // point above the pivot, counter-clockwise rotation moves it left
    const bounds = {
        xmin: 1600, ymin: 0, xmax: 1920, ymax: 1080,
    };
    // 1700 - 200 sin(a) >= 1600  => a <= 30 (counter-clockwise)
    assert.equal(clampRotationAngle([1700, 300], 1700, 500, -45, bounds), -30);
    // a second point further from the pivot limits earlier: 1700 - 400 sin(a) >= 1600 => a <= 14
    assert.equal(clampRotationAngle([1700, 300, 1700, 100], 1700, 500, -45, bounds), -14);
});

test('clampRotationAngle: a point exactly on the border stays allowed at 0 and blocks outwards', () => {
    // point on the right border to the right of the pivot; clockwise moves it down (y)
    const points = [1920, 500];
    assert.equal(clampRotationAngle(points, 1820, 500, 0, B), 0);
    // any rotation pulls x inwards (cos < 1), so it is allowed in both directions
    assert.equal(clampRotationAngle(points, 1820, 500, 10, B), 10);
    assert.equal(clampRotationAngle(points, 1820, 500, -10, B), -10);
});

test('clampRotationAngle: y walls', () => {
    // point right of the pivot near the bottom; clockwise moves it down
    const points = [1000, 1000];
    // 1000 + 100 sin(a) <= 1080... pivot (900, 1000): y = 1000 + 100 sin a <= 1080 => a <= 53
    assert.equal(clampRotationAngle(points, 900, 1000, 90, B), 53);
});

test('clampEdges: far edges starting outside, two edges at once', () => {
    const start = box(100, -10, 1930, 1090);
    assert.deepEqual(clampEdges(start, box(90, -20, 1950, 1100), B), box(90, -10, 1930, 1090));
    assert.deepEqual(clampEdges(start, box(90, 0, 1900, 1000), B), box(90, 0, 1900, 1000));
});

test('clampRect: y overflow and a rect drawn up-left (normalized by svg.draw)', () => {
    assert.deepEqual(clampRect({
        x: 100, y: 1000, width: 50, height: 300,
    }, B), {
        x: 100, y: 1000, width: 50, height: 80,
    });
    assert.deepEqual(clampRect({
        x: -10, y: -10, width: 5, height: 5,
    }, B), {
        x: 0, y: 0, width: 0, height: 0,
    });
});

test('snapNearBorder: float noise outside the image snaps onto the border only', () => {
    assert.deepEqual(snapNearBorder([-4.5e-7, 1080.0000001, 1920.0004, -0.5], 1920, 1080), [0, 1080, 1920, -0.5]);
    assert.deepEqual(snapNearBorder([10, 20, 1925, 1100], 1920, 1080), [10, 20, 1925, 1100]);
});

test('clampMovedPoint: an outside keypoint at (0,0) is pushed along the border, never out', () => {
    // person moves left/up: the point stays at (0, 0)
    assert.deepEqual(clampMovedPoint(0, 0, -120, -40, B), [0, 0]);
    // person moves right/down: the point moves normally
    assert.deepEqual(clampMovedPoint(0, 0, 120, 40, B), [120, 40]);
    // mixed: slides along the left border while moving down
    assert.deepEqual(clampMovedPoint(0, 0, -50, 70, B), [0, 70]);
    // far border
    assert.deepEqual(clampMovedPoint(1900, 1070, 1950, 1100, B), [1920, 1080]);
});

test('clampMovedPoint: a point that started outside does not jump in, only no further out', () => {
    assert.deepEqual(clampMovedPoint(-30, 500, -40, 500, B), [-30, 500]);
    assert.deepEqual(clampMovedPoint(-30, 500, -20, 500, B), [-20, 500]);
});

test('group limit ignores outside keypoints; they are clamped individually', () => {
    // person extent [400..700] (outside keypoint at (0,0) excluded) moved left by 500:
    // the group stops at -400, the outside keypoint stays at (0, 0)
    const { dx, dy } = clampGroupDelta([box(400, 300, 700, 900)], -500, -10, B);
    assert.deepEqual([dx, dy], [-400, -10]);
    assert.deepEqual(clampMovedPoint(0, 0, 0 + dx, 0 + dy, B), [0, 0]);
});
