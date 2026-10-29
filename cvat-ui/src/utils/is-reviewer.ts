// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

import { useEffect, useState } from 'react';
import { useSelector } from 'react-redux';
import { CombinedState } from 'reducers';
import { MembershipRole, Organization } from 'cvat-core-wrapper';

// INNO-125: who counts as a reviewer for reviewer-only shortcuts.
// 사용자 결정 2026-10-28: 조직 reviewer 역할 포함 —
// a user is a reviewer when either
//   - they are in the system group `reviewer` or `admin` (사용자 결정 2026-10-29: admins too), or
//   - their membership role in the current organization is `reviewer`.
// The current organization is the job's organization: the server only serves a job inside the
// organization context it belongs to (IAM), so a job open in the annotation view shares it.
// Note: this is intentionally broader than `isReviewerOnly` (reviewer group and not admin) used
// when finishing a job; the two concepts are separate.
export function isReviewerGroups(groups: readonly string[] | null | undefined): boolean {
    return !!groups && (groups.includes('reviewer') || groups.includes('admin'));
}

export function selectIsReviewerGroup(state: CombinedState): boolean {
    return isReviewerGroups(state.auth.user?.groups);
}

// one lookup per (organization, user) per page load; failures are not cached so they can be retried
const orgRoleCache: Record<string, Promise<MembershipRole | null>> = {};

function fetchOrganizationRole(organization: Organization, username: string): Promise<MembershipRole | null> {
    const key = `${organization.slug}:${username}`;
    if (!(key in orgRoleCache)) {
        orgRoleCache[key] = organization.members({
            page: 1,
            pageSize: 1,
            filter: JSON.stringify({ and: [{ '==': [{ var: 'user' }, username] }] }),
        }).then((memberships) => memberships[0]?.role ?? null).catch(() => {
            delete orgRoleCache[key];
            return null;
        });
    }

    return orgRoleCache[key];
}

// Synchronous for the system group; resolves asynchronously for an organization role, so the
// result may flip from false to true once the membership is known.
export function useIsReviewer(): boolean {
    const isReviewerGroup = useSelector(selectIsReviewerGroup);
    const username = useSelector((state: CombinedState) => state.auth.user?.username ?? null);
    const organization = useSelector((state: CombinedState) => state.organizations.current ?? null);
    const [orgRole, setOrgRole] = useState<{ key: string; role: MembershipRole | null } | null>(null);
    const key = organization && username ? `${organization.slug}:${username}` : null;

    useEffect(() => {
        if (isReviewerGroup || !organization || !username || !key) {
            return () => {};
        }

        let cancelled = false;
        fetchOrganizationRole(organization, username).then((role) => {
            if (!cancelled) {
                setOrgRole({ key, role });
            }
        });

        return () => {
            cancelled = true;
        };
    }, [isReviewerGroup, organization, username, key]);

    if (isReviewerGroup) {
        return true;
    }

    return !!key && orgRole?.key === key && orgRole.role === MembershipRole.REVIEWER;
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
