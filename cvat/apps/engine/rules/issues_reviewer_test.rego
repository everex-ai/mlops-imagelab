package issues_reviewer_test

import rego.v1

import data.issues

reviewer_auth := {
    "user": {"id": 1, "privilege": "user"},
    "organization": {
        "id": 10,
        "owner": {"id": 999},
        "user": {"role": "reviewer"}
    }
}

# Issue created by the reviewer themselves.
own_issue := {
    "id": 200,
    "owner": {"id": 1},
    "assignee": {"id": 1},
    "organization": {"id": 10},
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "project": null,
    "job": {"assignee": {"id": 50}, "stage": "validation"}
}

# Issue created by somebody else (e.g. another labeler).
other_issue := {
    "id": 201,
    "owner": {"id": 50},
    "assignee": {"id": 50},
    "organization": {"id": 10},
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "project": null,
    "job": {"assignee": {"id": 50}, "stage": "validation"}
}

# Used for CREATE_IN_JOB — there is no existing issue yet.
create_resource := {
    "owner": {"id": 1},
    "assignee": null,
    "organization": {"id": 10},
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "project": null,
    "job": {"assignee": {"id": 50}, "stage": "annotation"}
}

# === Positive cases ===

test_reviewer_can_create_issue if {
    issues.allow with input as {
        "scope": "create@job",
        "auth": reviewer_auth,
        "resource": create_resource,
    }
}

test_reviewer_can_view_other_issue if {
    issues.allow with input as {
        "scope": "view",
        "auth": reviewer_auth,
        "resource": other_issue,
    }
}

test_reviewer_can_view_own_issue if {
    issues.allow with input as {
        "scope": "view",
        "auth": reviewer_auth,
        "resource": own_issue,
    }
}

test_reviewer_can_update_own_issue if {
    issues.allow with input as {
        "scope": "update",
        "auth": reviewer_auth,
        "resource": own_issue,
    }
}

test_reviewer_can_delete_own_issue if {
    issues.allow with input as {
        "scope": "delete",
        "auth": reviewer_auth,
        "resource": own_issue,
    }
}

# === Negative cases ===

test_reviewer_cannot_update_other_issue if {
    not issues.allow with input as {
        "scope": "update",
        "auth": reviewer_auth,
        "resource": other_issue,
    }
}

test_reviewer_cannot_delete_other_issue if {
    not issues.allow with input as {
        "scope": "delete",
        "auth": reviewer_auth,
        "resource": other_issue,
    }
}

test_reviewer_cannot_create_issue_in_other_org if {
    other_org_resource := json.patch(create_resource, [
        {"op": "replace", "path": "/organization/id", "value": 99}
    ])
    not issues.allow with input as {
        "scope": "create@job",
        "auth": reviewer_auth,
        "resource": other_org_resource,
    }
}
