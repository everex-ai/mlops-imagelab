// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// Pure helpers behind the player slider issue markers and the Issues tab badge (INNO-124).
// The markers summarize the whole job; the badge reads "this frame's issues / the job's issues".
// They depend only on the issue list and plain geometry, never on React or Redux.

export interface IssueLike {
    frame: number;
    resolved: boolean;
}

export interface IssueFrame {
    frame: number;
    hasUnresolved: boolean;
}

export interface IssueCounts {
    unresolved: number;
    total: number;
}

export interface IssuesSummary {
    // one entry per frame that has at least one issue, sorted by frame
    frames: IssueFrame[];
    counts: IssueCounts;
}

export interface PlacedIssueMarker extends IssueFrame {
    x: number;
}

// snap range of a marker in pixels on each side, shrunk to the midpoint with a closer neighbour
export const ISSUE_MARKER_SNAP_RADIUS = 6;

export function summarizeIssues(issues: readonly IssueLike[]): IssuesSummary {
    const unresolvedByFrame = new Map<number, boolean>();
    let unresolved = 0;
    for (const issue of issues) {
        if (!issue.resolved) {
            unresolved++;
        }
        unresolvedByFrame.set(issue.frame, !!unresolvedByFrame.get(issue.frame) || !issue.resolved);
    }

    const frames = Array.from(unresolvedByFrame.entries())
        .map(([frame, hasUnresolved]) => ({ frame, hasUnresolved }))
        .sort((a, b) => a.frame - b.frame);

    return { frames, counts: { unresolved, total: issues.length } };
}

// "T I" (issuesHidden) hides every marker; "T R" (issuesResolvedHidden) hides only resolved-only frames.
// The badge counts are intentionally not affected by either flag.
export function filterVisibleIssueFrames(
    frames: readonly IssueFrame[],
    issuesHidden: boolean,
    issuesResolvedHidden: boolean,
): IssueFrame[] {
    if (issuesHidden) {
        return [];
    }

    if (issuesResolvedHidden) {
        return frames.filter((frame) => frame.hasUnresolved);
    }

    return [...frames];
}

// Same mapping as the antd slider handle: (value - min) / (max - min) * width, rounded to an integer pixel.
export function frameToX(frame: number, min: number, max: number, width: number): number {
    if (max <= min) {
        return 0;
    }

    return Math.round(((frame - min) / (max - min)) * width);
}

export function xToFrame(x: number, min: number, max: number, width: number): number {
    if (max <= min || width <= 0) {
        return min;
    }

    return min + (x / width) * (max - min);
}

// Returns markers sorted by x. Frames outside [min, max] are dropped.
// Within the same x, resolved (grey) markers come first so unresolved (red) ones are painted on top.
export function placeIssueMarkers(
    frames: readonly IssueFrame[],
    min: number,
    max: number,
    width: number,
): PlacedIssueMarker[] {
    return frames
        .filter(({ frame }) => frame >= min && frame <= max)
        .map((frame) => ({ ...frame, x: frameToX(frame.frame, min, max, width) }))
        .sort((a, b) => (
            a.x - b.x ||
            Number(a.hasUnresolved) - Number(b.hasUnresolved) ||
            a.frame - b.frame
        ));
}

// "Nearest marker within the snap radius". This is equivalent to giving every marker the range
// [x - min(r, gapLeft / 2), x + min(r, gapRight / 2)].
// Several frames may share one pixel: the frame closest to the cursor (in frame units) wins,
// then an unresolved frame, then the smaller frame number.
export function findSnappedIssueFrame(
    markers: readonly PlacedIssueMarker[],
    cursorX: number,
    min: number,
    max: number,
    width: number,
    radius: number = ISSUE_MARKER_SNAP_RADIUS,
): PlacedIssueMarker | null {
    if (!markers.length) {
        return null;
    }

    // first index whose x >= cursorX
    let lo = 0;
    let hi = markers.length;
    while (lo < hi) {
        const mid = Math.floor((lo + hi) / 2);
        if (markers[mid].x < cursorX) {
            lo = mid + 1;
        } else {
            hi = mid;
        }
    }

    const candidatesX: number[] = [];
    if (lo < markers.length) candidatesX.push(markers[lo].x);
    if (lo > 0) candidatesX.push(markers[lo - 1].x);

    let bestX: number | null = null;
    for (const x of candidatesX) {
        const distance = Math.abs(x - cursorX);
        if (distance <= radius && (bestX === null || distance < Math.abs(bestX - cursorX))) {
            bestX = x;
        }
    }

    if (bestX === null) {
        return null;
    }

    const cursorFrame = xToFrame(cursorX, min, max, width);
    let best: PlacedIssueMarker | null = null;
    for (const marker of markers) {
        if (marker.x !== bestX) continue;
        if (best === null) {
            best = marker;
            continue;
        }

        const distance = Math.abs(marker.frame - cursorFrame);
        const bestDistance = Math.abs(best.frame - cursorFrame);
        if (
            distance < bestDistance ||
            (distance === bestDistance && marker.hasUnresolved && !best.hasUnresolved) ||
            (distance === bestDistance && marker.hasUnresolved === best.hasUnresolved && marker.frame < best.frame)
        ) {
            best = marker;
        }
    }

    return best;
}
