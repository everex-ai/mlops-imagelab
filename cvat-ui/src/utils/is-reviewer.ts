// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { CombinedState } from 'reducers';

// INNO-125: a "reviewer" is any user in the system group `reviewer`, admins included.
// Organization-level `reviewer` roles do not count.
// 가정(사용자 확인 대기): this criterion is the recommended default; change it only here.
export function isReviewerGroups(groups: readonly string[] | null | undefined): boolean {
    return !!groups && groups.includes('reviewer');
}

export function selectIsReviewer(state: CombinedState): boolean {
    return isReviewerGroups(state.auth.user?.groups);
}

// Shortcuts registered globally (so F2 save/restore works) but bound and shown only for reviewers.
export const REVIEWER_ONLY_SHORTCUTS: readonly string[] = ['SWITCH_STANDARD_REVIEW_WORKSPACE'];

export function hideReviewerOnlyShortcuts<T>(keyMap: Record<string, T>, isReviewer: boolean): Record<string, T> {
    if (isReviewer) {
        return keyMap;
    }

    return Object.fromEntries(
        Object.entries(keyMap).filter(([key]) => !REVIEWER_ONLY_SHORTCUTS.includes(key)),
    );
}
