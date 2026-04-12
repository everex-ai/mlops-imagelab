package issues_sandbox_reviewer_test

import rego.v1

import data.issues

sandbox_reviewer_auth := {
    "user": {"id": 1, "privilege": "reviewer"},
    "organization": null
}

issue_resource := {
    "id": 200,
    "owner": {"id": 1},
    "assignee": {"id": 50},
    "organization": null,
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "job": {"assignee": {"id": 50}, "stage": "validation"},
    "project": null
}

other_user_issue := {
    "id": 201,
    "owner": {"id": 77},
    "assignee": {"id": 50},
    "organization": null,
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "job": {"assignee": {"id": 50}, "stage": "validation"},
    "project": null
}

# === Positive cases ===

test_sandbox_reviewer_can_create_issue if {
    issues.allow with input as {
        "scope": "create@job",
        "auth": sandbox_reviewer_auth,
        "resource": issue_resource,
    }
}

test_sandbox_reviewer_can_view_issue if {
    issues.allow with input as {
        "scope": "view",
        "auth": sandbox_reviewer_auth,
        "resource": issue_resource,
    }
}

test_sandbox_reviewer_can_list_issues if {
    issues.allow with input as {
        "scope": "list",
        "auth": sandbox_reviewer_auth,
        "resource": issue_resource,
    }
}

test_sandbox_reviewer_can_update_own_issue if {
    issues.allow with input as {
        "scope": "update",
        "auth": sandbox_reviewer_auth,
        "resource": issue_resource,
    }
}

test_sandbox_reviewer_can_delete_own_issue if {
    issues.allow with input as {
        "scope": "delete",
        "auth": sandbox_reviewer_auth,
        "resource": issue_resource,
    }
}

# === Negative cases ===

test_sandbox_reviewer_cannot_update_other_issue if {
    not issues.allow with input as {
        "scope": "update",
        "auth": sandbox_reviewer_auth,
        "resource": other_user_issue,
    }
}

test_sandbox_reviewer_cannot_delete_other_issue if {
    not issues.allow with input as {
        "scope": "delete",
        "auth": sandbox_reviewer_auth,
        "resource": other_user_issue,
    }
}

# === Filter ===

test_sandbox_reviewer_filter_returns_all if {
    issues.filter == [] with input as {
        "scope": "list",
        "auth": sandbox_reviewer_auth,
        "resource": issue_resource,
    }
}
