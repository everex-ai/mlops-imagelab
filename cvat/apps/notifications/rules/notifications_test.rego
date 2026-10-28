# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

package notifications_test

import rego.v1

import data.notifications

# Hand-written, like jobs_reviewer_test.rego: the CSV generator models privileges
# by priority and cannot express the fork's "reviewer" group.

auth(privilege, org_role) := {
    "user": {"id": 1, "privilege": privilege},
    "organization": org(org_role),
}

org(null) := null

org(role) := {"id": 10, "owner": {"id": 999}, "user": {"role": role}} if role != null

test_every_privilege_can_list if {
    every privilege in ["admin", "user", "reviewer", "worker", null] {
        notifications.allow with input as {"scope": "list", "auth": auth(privilege, null)}
    }
}

test_org_reviewer_can_list_and_mark_all if {
    notifications.allow with input as {"scope": "list", "auth": auth("reviewer", "reviewer")}
    notifications.allow with input as {"scope": "update:all", "auth": auth("worker", "reviewer")}
}

test_recipient_can_mark_own_notification_read if {
    notifications.allow with input as {
        "scope": "update",
        "auth": auth("reviewer", null),
        "resource": {"id": 5, "recipient": {"id": 1}},
    }
}

test_nobody_marks_someone_elses_notification if {
    every privilege in ["admin", "user", "reviewer", "worker"] {
        not notifications.allow with input as {
            "scope": "update",
            "auth": auth(privilege, "owner"),
            "resource": {"id": 5, "recipient": {"id": 2}},
        }
    }
}

test_unknown_scope_is_denied if {
    not notifications.allow with input as {"scope": "delete", "auth": auth("admin", null)}
}
