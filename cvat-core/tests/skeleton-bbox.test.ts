// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// Run with: yarn workspace cvat-core run test:unit  (node --test, no build)

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { fallbackSkeletonBbox } from '../src/skeleton-bbox.ts';

const kp = (xmin: number, ymin: number, xmax: number, ymax: number) => ({
    xmin, ymin, xmax, ymax,
});

test('margin is clipped at the image border (AE1)', () => {
    assert.deepEqual(fallbackSkeletonBbox(kp(1850, 500, 1905, 900), 20, 1920, 1080), [1830, 480, 1920, 920]);
});

test('keypoints far from the border keep the full margin', () => {
    assert.deepEqual(fallbackSkeletonBbox(kp(100, 200, 300, 400), 20, 1920, 1080), [80, 180, 320, 420]);
});

test('an already-outside keypoint is still contained, nothing goes further out (R20)', () => {
    assert.deepEqual(fallbackSkeletonBbox(kp(-5, 100, 300, 1090), 20, 1920, 1080), [-5, 80, 320, 1090]);
});

test('a keypoint close to the border gets only the remaining margin', () => {
    assert.deepEqual(fallbackSkeletonBbox(kp(3, 2, 300, 400), 20, 1920, 1080), [0, 0, 320, 420]);
});

test('unknown image size: margin without clipping', () => {
    assert.deepEqual(fallbackSkeletonBbox(kp(1850, 500, 1905, 900), 20, undefined, undefined), [1830, 480, 1925, 920]);
});

test('only one dimension known: the other is not clipped', () => {
    assert.deepEqual(fallbackSkeletonBbox(kp(1850, 990, 1905, 995), 20, 1920, undefined), [1830, 970, 1920, 1015]);
});
