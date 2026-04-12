package jobs_sandbox_reviewer_test

import rego.v1

import data.jobs

# Tests for global (sandbox) reviewer privilege.
# A sandbox reviewer has privilege="reviewer" and organization=null.

sandbox_reviewer_auth := {
    "user": {"id": 1, "privilege": "reviewer"},
    "organization": null
}

sandbox_job_resource(stage) := {
    "id": 100,
    "stage": stage,
    "assignee": {"id": 50},
    "organization": null,
    "task": {"owner": {"id": 999}, "assignee": {"id": 999}},
    "project": null,
    "rq_job": null
}

# === Positive cases ===

test_sandbox_reviewer_can_view_job if {
    jobs.allow with input as {
        "scope": "view",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

test_sandbox_reviewer_can_view_annotations if {
    jobs.allow with input as {
        "scope": "view:annotations",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("validation"),
    }
}

test_sandbox_reviewer_can_view_data if {
    jobs.allow with input as {
        "scope": "view:data",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

test_sandbox_reviewer_can_view_metadata if {
    jobs.allow with input as {
        "scope": "view:metadata",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("validation"),
    }
}

test_sandbox_reviewer_can_view_validation_layout if {
    jobs.allow with input as {
        "scope": "view:validation_layout",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("validation"),
    }
}

test_sandbox_reviewer_can_update_stage if {
    jobs.allow with input as {
        "scope": "update:stage",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("validation"),
    }
}

test_sandbox_reviewer_can_update_state if {
    jobs.allow with input as {
        "scope": "update:state",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

test_sandbox_reviewer_can_update_assignee if {
    jobs.allow with input as {
        "scope": "update:assignee",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

test_sandbox_reviewer_can_list_jobs if {
    jobs.allow with input as {
        "scope": "list",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

# === Negative cases — annotation mutation MUST be blocked ===

test_sandbox_reviewer_cannot_update_annotations if {
    not jobs.allow with input as {
        "scope": "update:annotations",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

test_sandbox_reviewer_cannot_delete_annotations if {
    not jobs.allow with input as {
        "scope": "delete:annotations",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

test_sandbox_reviewer_cannot_import_annotations if {
    not jobs.allow with input as {
        "scope": "import:annotations",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

test_sandbox_reviewer_cannot_export_annotations if {
    not jobs.allow with input as {
        "scope": "export:annotations",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("validation"),
    }
}

test_sandbox_reviewer_cannot_export_dataset if {
    not jobs.allow with input as {
        "scope": "export:dataset",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("validation"),
    }
}

test_sandbox_reviewer_cannot_update_metadata if {
    not jobs.allow with input as {
        "scope": "update:metadata",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

test_sandbox_reviewer_cannot_create_job if {
    not jobs.allow with input as {
        "scope": "create",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

test_sandbox_reviewer_cannot_delete_job if {
    not jobs.allow with input as {
        "scope": "delete",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}

# === Filter: sandbox reviewer sees all jobs ===

test_sandbox_reviewer_filter_returns_all if {
    jobs.filter == [] with input as {
        "scope": "list",
        "auth": sandbox_reviewer_auth,
        "resource": sandbox_job_resource("annotation"),
    }
}
