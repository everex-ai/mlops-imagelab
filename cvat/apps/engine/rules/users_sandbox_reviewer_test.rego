package users_sandbox_reviewer_test

import rego.v1

import data.users

# Tests for sandbox reviewer privilege on user resources.
# A sandbox reviewer has privilege="reviewer" and organization=null.

sandbox_reviewer_auth := {
    "user": {"id": 1, "privilege": "reviewer"},
    "organization": null,
}

other_user_resource := {
    "id": 50,
    "membership": {"role": null},
}

self_resource := {
    "id": 1,
    "membership": {"role": null},
}

# === Positive cases ===

test_sandbox_reviewer_can_list_users if {
    users.allow with input as {
        "scope": "list",
        "auth": sandbox_reviewer_auth,
        "resource": null,
    }
}

test_sandbox_reviewer_can_view_self if {
    users.allow with input as {
        "scope": "view",
        "auth": sandbox_reviewer_auth,
        "resource": self_resource,
    }
}

test_sandbox_reviewer_can_view_other_user if {
    users.allow with input as {
        "scope": "view",
        "auth": sandbox_reviewer_auth,
        "resource": other_user_resource,
    }
}

# === Filter: sandbox reviewer sees all users ===

test_sandbox_reviewer_filter_returns_all if {
    users.filter == [] with input as {
        "scope": "list",
        "auth": sandbox_reviewer_auth,
        "resource": null,
    }
}

# === Negative cases ===

test_sandbox_reviewer_cannot_update_other_user if {
    not users.allow with input as {
        "scope": "update",
        "auth": sandbox_reviewer_auth,
        "resource": other_user_resource,
    }
}

test_sandbox_reviewer_cannot_delete_other_user if {
    not users.allow with input as {
        "scope": "delete",
        "auth": sandbox_reviewer_auth,
        "resource": other_user_resource,
    }
}
