package comments_sandbox_reviewer_test

import rego.v1

import data.comments

sandbox_reviewer_auth := {
    "user": {"id": 1, "privilege": "reviewer"},
    "organization": null
}

comment_resource := {
    "id": 300,
    "owner": {"id": 1},
    "organization": null,
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "job": {"assignee": {"id": 50}, "stage": "validation"},
    "issue": {"owner": {"id": 1}, "assignee": {"id": 50}},
    "project": null
}

other_user_comment := {
    "id": 301,
    "owner": {"id": 77},
    "organization": null,
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "job": {"assignee": {"id": 50}, "stage": "validation"},
    "issue": {"owner": {"id": 77}, "assignee": {"id": 50}},
    "project": null
}

# === Positive cases ===

test_sandbox_reviewer_can_create_comment if {
    comments.allow with input as {
        "scope": "create@issue",
        "auth": sandbox_reviewer_auth,
        "resource": comment_resource,
    }
}

test_sandbox_reviewer_can_view_comment if {
    comments.allow with input as {
        "scope": "view",
        "auth": sandbox_reviewer_auth,
        "resource": comment_resource,
    }
}

test_sandbox_reviewer_can_list_comments if {
    comments.allow with input as {
        "scope": "list",
        "auth": sandbox_reviewer_auth,
        "resource": comment_resource,
    }
}

test_sandbox_reviewer_can_update_own_comment if {
    comments.allow with input as {
        "scope": "update",
        "auth": sandbox_reviewer_auth,
        "resource": comment_resource,
    }
}

test_sandbox_reviewer_can_delete_own_comment if {
    comments.allow with input as {
        "scope": "delete",
        "auth": sandbox_reviewer_auth,
        "resource": comment_resource,
    }
}

# === Negative cases ===

test_sandbox_reviewer_cannot_update_other_comment if {
    not comments.allow with input as {
        "scope": "update",
        "auth": sandbox_reviewer_auth,
        "resource": other_user_comment,
    }
}

test_sandbox_reviewer_cannot_delete_other_comment if {
    not comments.allow with input as {
        "scope": "delete",
        "auth": sandbox_reviewer_auth,
        "resource": other_user_comment,
    }
}

# === Filter ===

test_sandbox_reviewer_filter_returns_all if {
    comments.filter == [] with input as {
        "scope": "list",
        "auth": sandbox_reviewer_auth,
        "resource": comment_resource,
    }
}
