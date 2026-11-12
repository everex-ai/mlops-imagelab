// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// Run with: yarn workspace cvat-canvas run test:unit  (node --test, no build)

import { test } from 'node:test';
import assert from 'node:assert/strict';

import {
    clampGroupDelta, clampEdges, unwrapAngle, clampRotationAngle, clampRect,
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
