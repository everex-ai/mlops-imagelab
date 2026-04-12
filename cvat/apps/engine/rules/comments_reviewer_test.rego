package comments_reviewer_test

import rego.v1

import data.comments

reviewer_auth := {
    "user": {"id": 1, "privilege": "user"},
    "organization": {
        "id": 10,
        "owner": {"id": 999},
        "user": {"role": "reviewer"}
    }
}

own_comment := {
    "id": 300,
    "owner": {"id": 1},
    "organization": {"id": 10},
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "project": null,
    "job": {"assignee": {"id": 50}, "stage": "validation"},
    "issue": {"owner": {"id": 50}, "assignee": {"id": 50}}
}

other_comment := {
    "id": 301,
    "owner": {"id": 50},
    "organization": {"id": 10},
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "project": null,
    "job": {"assignee": {"id": 50}, "stage": "validation"},
    "issue": {"owner": {"id": 50}, "assignee": {"id": 50}}
}

create_resource := {
    "owner": {"id": 1},
    "organization": {"id": 10},
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "project": null,
    "job": {"assignee": {"id": 50}, "stage": "validation"},
    "issue": {"owner": {"id": 50}, "assignee": {"id": 50}}
}

# === Positive cases ===

test_reviewer_can_create_comment if {
    comments.allow with input as {
        "scope": "create@issue",
        "auth": reviewer_auth,
        "resource": create_resource,
    }
}

test_reviewer_can_view_other_comment if {
    comments.allow with input as {
        "scope": "view",
        "auth": reviewer_auth,
        "resource": other_comment,
    }
}

test_reviewer_can_update_own_comment if {
    comments.allow with input as {
        "scope": "update",
        "auth": reviewer_auth,
        "resource": own_comment,
    }
}

test_reviewer_can_delete_own_comment if {
    comments.allow with input as {
        "scope": "delete",
        "auth": reviewer_auth,
        "resource": own_comment,
    }
}

# === Negative cases ===

test_reviewer_cannot_update_other_comment if {
    not comments.allow with input as {
        "scope": "update",
        "auth": reviewer_auth,
        "resource": other_comment,
    }
}

test_reviewer_cannot_delete_other_comment if {
    not comments.allow with input as {
        "scope": "delete",
        "auth": reviewer_auth,
        "resource": other_comment,
    }
}

test_reviewer_cannot_create_comment_in_other_org if {
    other_org_resource := json.patch(create_resource, [
        {"op": "replace", "path": "/organization/id", "value": 99}
    ])
    not comments.allow with input as {
        "scope": "create@issue",
        "auth": reviewer_auth,
        "resource": other_org_resource,
    }
}
