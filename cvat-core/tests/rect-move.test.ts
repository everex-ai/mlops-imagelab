// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// Run with: yarn workspace cvat-core run test:unit  (node --test, no build)

import { test } from 'node:test';
import assert from 'node:assert/strict';

import { isSizePreservingRectMove, isRectMoveWithinAllowedRange } from '../src/rect-move.ts';

const g = (points: number[], rotation = 0) => ({ points, rotation });

test('a translated rectangle is a move (R19, AE8)', () => {
    assert.equal(isSizePreservingRectMove(g([-30, 0, 270, 200]), g([-20, 0, 280, 200])), true);
    assert.equal(isSizePreservingRectMove(g([100, 100, 400, 300]), g([1620, 50, 1920, 250])), true);
});

test('sub-epsilon float noise still counts as a move', () => {
    assert.equal(isSizePreservingRectMove(g([0, 0, 100, 100]), g([10.0000001, 0, 110.0000003, 100])), true);
});

test('a resize is not a move (still fitted to the image)', () => {
    assert.equal(isSizePreservingRectMove(g([0, 0, 100, 100]), g([0, 0, 101, 100])), false);
    assert.equal(isSizePreservingRectMove(g([0, 0, 100, 100]), g([0, 0, 100, 99.99])), false);
});

test('a rotation on either side disqualifies', () => {
    assert.equal(isSizePreservingRectMove(g([0, 0, 100, 100], 30), g([10, 0, 110, 100])), false);
    assert.equal(isSizePreservingRectMove(g([0, 0, 100, 100]), g([10, 0, 110, 100], 30)), false);
});

test('unknown or malformed geometry disqualifies', () => {
    assert.equal(isSizePreservingRectMove(null, g([0, 0, 100, 100])), false);
    assert.equal(isSizePreservingRectMove(g([0, 0, 100]), g([0, 0, 100, 100])), false);
    assert.equal(isSizePreservingRectMove(g([0, 0, 100, 100]), g([0, 0, 100, 100, 5, 5])), false);
});

test('allowed range: inside or no further out than before', () => {
    // partly outside on the left, moved inwards (AE8)
    assert.equal(isRectMoveWithinAllowedRange(g([-30, 0, 270, 200]), g([-20, 0, 280, 200]), 1920, 1080), true);
    // moved to touch the right border
    assert.equal(isRectMoveWithinAllowedRange(g([100, 0, 400, 200]), g([1620, 0, 1920, 200]), 1920, 1080), true);
    // pushed out of the image by a non-canvas save -> must be fitted
    assert.equal(isRectMoveWithinAllowedRange(g([100, 0, 400, 200]), g([1700, 0, 2000, 200]), 1920, 1080), false);
    // already outside, pushed further out
    assert.equal(isRectMoveWithinAllowedRange(g([-30, 0, 270, 200]), g([-40, 0, 260, 200]), 1920, 1080), false);
    assert.equal(isRectMoveWithinAllowedRange(g([0, 900, 100, 1100]), g([0, 910, 100, 1110]), 1920, 1080), false);
});
