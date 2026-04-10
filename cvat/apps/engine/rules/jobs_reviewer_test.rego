package jobs_reviewer_test

import rego.v1

import data.jobs

# Explicit reviewer-role test cases for jobs.rego.
#
# These tests are NOT generated from the CSV matrix because reviewer is
# intentionally not in organizations.get_priority(): the priority-based
# generator cannot model "reviewer is a separate axis". They live as
# hand-written cases instead, so the labeling-blocking guarantee is
# verified directly against the OPA policy engine.

reviewer_auth := {
    "user": {"id": 1, "privilege": "user"},
    "organization": {
        "id": 10,
        "owner": {"id": 999},
        "user": {"role": "reviewer"}
    }
}

# Reviewer is in the same organization as the job.
job_resource(stage) := {
    "id": 100,
    "stage": stage,
    "assignee": {"id": 50},
    "organization": {"id": 10},
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "project": null,
    "rq_job": null
}

# === Positive cases (reviewer must be allowed) ===

test_reviewer_can_view_job_at_annotation if {
    jobs.allow with input as {
        "scope": "view",
        "auth": reviewer_auth,
        "resource": job_resource("annotation"),
    }
}

test_reviewer_can_view_job_at_validation if {
    jobs.allow with input as {
        "scope": "view",
        "auth": reviewer_auth,
        "resource": job_resource("validation"),
    }
}

test_reviewer_can_view_job_at_acceptance if {
    jobs.allow with input as {
        "scope": "view",
        "auth": reviewer_auth,
        "resource": job_resource("acceptance"),
    }
}

test_reviewer_can_view_annotations if {
    jobs.allow with input as {
        "scope": "view:annotations",
        "auth": reviewer_auth,
        "resource": job_resource("annotation"),
    }
}

test_reviewer_can_view_data if {
    jobs.allow with input as {
        "scope": "view:data",
        "auth": reviewer_auth,
        "resource": job_resource("validation"),
    }
}

test_reviewer_can_view_metadata if {
    jobs.allow with input as {
        "scope": "view:metadata",
        "auth": reviewer_auth,
        "resource": job_resource("validation"),
    }
}

test_reviewer_can_view_validation_layout if {
    jobs.allow with input as {
        "scope": "view:validation_layout",
        "auth": reviewer_auth,
        "resource": job_resource("validation"),
    }
}

test_reviewer_can_update_stage if {
    jobs.allow with input as {
        "scope": "update:stage",
        "auth": reviewer_auth,
        "resource": job_resource("validation"),
    }
}

test_reviewer_can_update_state if {
    jobs.allow with input as {
        "scope": "update:state",
        "auth": reviewer_auth,
        "resource": job_resource("annotation"),
    }
}

test_reviewer_can_update_assignee if {
    jobs.allow with input as {
        "scope": "update:assignee",
        "auth": reviewer_auth,
        "resource": job_resource("annotation"),
    }
}

# === Negative cases — labeling MUST be blocked ===

test_reviewer_cannot_update_annotations_at_annotation if {
    not jobs.allow with input as {
        "scope": "update:annotations",
        "auth": reviewer_auth,
        "resource": job_resource("annotation"),
    }
}

test_reviewer_cannot_update_annotations_at_validation if {
    not jobs.allow with input as {
        "scope": "update:annotations",
        "auth": reviewer_auth,
        "resource": job_resource("validation"),
    }
}

test_reviewer_cannot_update_annotations_at_acceptance if {
    not jobs.allow with input as {
        "scope": "update:annotations",
        "auth": reviewer_auth,
        "resource": job_resource("acceptance"),
    }
}

test_reviewer_cannot_delete_annotations if {
    not jobs.allow with input as {
        "scope": "delete:annotations",
        "auth": reviewer_auth,
        "resource": job_resource("annotation"),
    }
}

test_reviewer_cannot_import_annotations if {
    not jobs.allow with input as {
        "scope": "import:annotations",
        "auth": reviewer_auth,
        "resource": job_resource("annotation"),
    }
}

test_reviewer_cannot_export_annotations if {
    not jobs.allow with input as {
        "scope": "export:annotations",
        "auth": reviewer_auth,
        "resource": job_resource("validation"),
    }
}

test_reviewer_cannot_export_dataset if {
    not jobs.allow with input as {
        "scope": "export:dataset",
        "auth": reviewer_auth,
        "resource": job_resource("validation"),
    }
}

# === Negative cases — other mutations also blocked ===

test_reviewer_cannot_create_job if {
    not jobs.allow with input as {
        "scope": "create",
        "auth": reviewer_auth,
        "resource": job_resource("annotation"),
    }
}

test_reviewer_cannot_delete_job if {
    not jobs.allow with input as {
        "scope": "delete",
        "auth": reviewer_auth,
        "resource": job_resource("annotation"),
    }
}

test_reviewer_cannot_update_metadata if {
    not jobs.allow with input as {
        "scope": "update:metadata",
        "auth": reviewer_auth,
        "resource": job_resource("annotation"),
    }
}

test_reviewer_cannot_update_validation_layout if {
    not jobs.allow with input as {
        "scope": "update:validation_layout",
        "auth": reviewer_auth,
        "resource": job_resource("validation"),
    }
}

# === Cross-organization isolation ===

test_reviewer_cannot_view_job_in_other_org if {
    other_resource := json.patch(job_resource("validation"), [
        {"op": "replace", "path": "/organization/id", "value": 99}
    ])
    not jobs.allow with input as {
        "scope": "view",
        "auth": reviewer_auth,
        "resource": other_resource,
    }
}

test_reviewer_cannot_update_stage_in_other_org if {
    other_resource := json.patch(job_resource("validation"), [
        {"op": "replace", "path": "/organization/id", "value": 99}
    ])
    not jobs.allow with input as {
        "scope": "update:stage",
        "auth": reviewer_auth,
        "resource": other_resource,
    }
}

test_reviewer_cannot_update_state_in_other_org if {
    other_resource := json.patch(job_resource("validation"), [
        {"op": "replace", "path": "/organization/id", "value": 99}
    ])
    not jobs.allow with input as {
        "scope": "update:state",
        "auth": reviewer_auth,
        "resource": other_resource,
    }
}

test_reviewer_cannot_update_assignee_in_other_org if {
    other_resource := json.patch(job_resource("validation"), [
        {"op": "replace", "path": "/organization/id", "value": 99}
    ])
    not jobs.allow with input as {
        "scope": "update:assignee",
        "auth": reviewer_auth,
        "resource": other_resource,
    }
}

# === Regression: existing roles unaffected ===

worker_auth := {
    "user": {"id": 1, "privilege": "user"},
    "organization": {
        "id": 10,
        "owner": {"id": 999},
        "user": {"role": "worker"}
    }
}

worker_owned_job := {
    "id": 100,
    "stage": "annotation",
    "assignee": {"id": 1},
    "organization": {"id": 10},
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "project": null,
    "rq_job": null
}

test_worker_can_still_update_own_annotations if {
    jobs.allow with input as {
        "scope": "update:annotations",
        "auth": worker_auth,
        "resource": worker_owned_job,
    }
}
