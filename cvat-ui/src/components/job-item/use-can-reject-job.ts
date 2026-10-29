// Copyright (C) CVAT.ai Corporation
//
// SPDX-License-Identifier: MIT

// INNO-126: workers may not set a job state to "rejected"; everyone else may
// (사용자 결정 2026-10-28, Q1: worker만 차단).
// The server (jobs.rego `can_reject`) is the source of truth; this mirrors it so
// the UI can disable the option instead of letting the request fail with 403.

import { useEffect, useState } from 'react';
import { shallowEqual, useSelector } from 'react-redux';

import { MembershipRole, Organization } from 'cvat-core-wrapper';
import { CombinedState } from 'reducers';

export const REJECT_DISABLED_TOOLTIP = '반려(rejected)는 작업자 계정으로 할 수 없습니다';

// Same order as IAM_ROLES in cvat/settings/base.py: the server keeps only the
// first matching group as the user's privilege (cvat/apps/iam/middleware.py).
const PRIVILEGE_ORDER = ['admin', 'user', 'reviewer', 'worker'];

export function getEffectivePrivilege(groups: string[]): string | null {
    return PRIVILEGE_ORDER.find((privilege) => groups.includes(privilege)) ?? null;
}

// Keep in sync with `can_reject` in cvat/apps/engine/rules/jobs.rego: admins and global
// reviewers always, otherwise the job is rejectable unless the effective privilege is "worker" — the
// global privilege in the sandbox, the membership role inside an organization.
export function canRejectJob(
    privilege: string | null,
    organization: { role: MembershipRole | null } | null,
): boolean {
    // 사용자 결정 2026-10-28: a global reviewer may reject regardless of its org role
    if (privilege === 'admin' || privilege === 'reviewer') return true;
    if (organization === null) return privilege !== null && privilege !== 'worker';
    return organization.role !== null && organization.role !== MembershipRole.WORKER;
}

// The membership role of the current user, or `undefined` when it could not be
// determined (request failed). One lookup per (organization, user) is shared by
// every selector on the page (e.g. all job cards on the task page).
type OrgRoleLookup = MembershipRole | null | undefined;
const orgRoleCache = new Map<string, Promise<OrgRoleLookup>>();

function fetchOrgRole(organization: Organization, username: string): Promise<OrgRoleLookup> {
    const key = `${organization.id}:${username}`;
    let request = orgRoleCache.get(key);
    if (!request) {
        request = organization.members({
            filter: JSON.stringify({ and: [{ '==': [{ var: 'user' }, username] }] }),
        }).then((memberships) => {
            // The server ignores inactive (not yet accepted) memberships
            const active = memberships.find((membership) => membership.isActive);
            return active ? active.role : null;
        }).catch(() => {
            orgRoleCache.delete(key); // retry on the next mount
            return undefined;
        });
        orgRoleCache.set(key, request);
    }
    return request;
}

export function useCanRejectJob(): boolean {
    const { user, organization } = useSelector((state: CombinedState) => ({
        user: state.auth.user,
        organization: state.organizations.current ?? null,
    }), shallowEqual);

    const privilege = getEffectivePrivilege(user?.groups ?? []);
    // The membership role matters only inside an organization and for non-admins.
    const lookup = (user && organization && privilege !== 'admin' && privilege !== 'reviewer') ?
        { organization, username: user.username, key: `${organization.id}:${user.username}` } :
        null;
    const [orgRole, setOrgRole] = useState<{ key: string; role: OrgRoleLookup } | null>(null);

    useEffect(() => {
        if (!lookup) return undefined;

        let cancelled = false;
        fetchOrgRole(lookup.organization, lookup.username).then((role) => {
            if (!cancelled) setOrgRole({ key: lookup.key, role });
        });
        return () => { cancelled = true; };
    }, [lookup?.key]);

    if (!user) return false;
    if (!organization) return canRejectJob(privilege, null);
    if (!lookup) return canRejectJob(privilege, { role: null });

    // While the role is loading keep the option disabled. If the lookup failed, leave
    // it enabled: the server is authoritative and answers a worker with a 403 reason.
    if (orgRole?.key !== lookup.key) return false;
    if (orgRole.role === undefined) return true;
    return canRejectJob(privilege, { role: orgRole.role });
}
