package jobs_reject_test

import rego.v1

import data.jobs

# INNO-126: workers may not move a job to state "rejected"; everyone else may.
# (사용자 결정 2026-10-28, Q1: worker만 차단)
# Hand-written because the generated matrix (jobs_test.gen.rego) has no
# request-value axis; requests without `input.request` must keep their old result.

# --- fixtures -------------------------------------------------------------

sandbox_auth(user_id, privilege) := {
    "user": {"id": user_id, "privilege": privilege},
    "organization": null,
}

org_auth(user_id, privilege, role) := {
    "user": {"id": user_id, "privilege": privilege},
    "organization": {
        "id": 10,
        "owner": {"id": 999},
        "user": {"role": role},
    },
}

# Job 100: assignee 50, task owner 60, task assignee 61.
job(org_id) := {
    "id": 100,
    "stage": "annotation",
    "assignee": {"id": 50},
    "organization": {"id": org_id},
    "task": {"owner": {"id": 60}, "assignee": {"id": 61}},
    "project": null,
    "rq_job": null,
}

sandbox_job := job(null)

org_job := job(10)

state_input(auth, resource, state) := {
    "scope": "update:state",
    "auth": auth,
    "resource": resource,
    "request": {"state": state},
}

# --- sandbox worker (job assignee) ----------------------------------------

test_sandbox_worker_assignee_cannot_reject if {
    not jobs.allow with input as state_input(sandbox_auth(50, "worker"), sandbox_job, "rejected")
}

test_sandbox_worker_assignee_can_set_other_states if {
    every state in ["new", "in progress", "completed"] {
        jobs.allow with input as state_input(sandbox_auth(50, "worker"), sandbox_job, state)
    }
}

# Covers AE4: a rejected job can still be moved back to "in progress".
test_sandbox_worker_can_leave_rejected_state if {
    resource := object.union(sandbox_job, {"state": "rejected"})
    jobs.allow with input as state_input(sandbox_auth(50, "worker"), resource, "in progress")
}

# The guard must not leak into the other scopes of the same rule.
test_sandbox_worker_can_still_update_annotations if {
    jobs.allow with input as {
        "scope": "update:annotations",
        "auth": sandbox_auth(50, "worker"),
        "resource": sandbox_job,
        "request": {"state": "rejected"},
    }
}

# Without the request key the result is unchanged (generated-test compatibility).
test_sandbox_worker_update_state_without_request_key if {
    jobs.allow with input as {
        "scope": "update:state",
        "auth": sandbox_auth(50, "worker"),
        "resource": sandbox_job,
    }
}

test_sandbox_worker_null_requested_state_is_not_reject if {
    jobs.allow with input as state_input(sandbox_auth(50, "worker"), sandbox_job, null)
}

# --- sandbox user / reviewer / admin -------------------------------------

test_sandbox_user_task_owner_can_reject if {
    jobs.allow with input as state_input(sandbox_auth(60, "user"), sandbox_job, "rejected")
}

test_sandbox_reviewer_can_reject if {
    jobs.allow with input as state_input(sandbox_auth(1, "reviewer"), sandbox_job, "rejected")
}

test_sandbox_admin_can_reject if {
    jobs.allow with input as state_input(sandbox_auth(1, "admin"), sandbox_job, "rejected")
}

# A sandbox worker who is also task staff is still a worker.
test_sandbox_worker_task_owner_cannot_reject if {
    not jobs.allow with input as state_input(sandbox_auth(60, "worker"), sandbox_job, "rejected")
}

# --- organization ---------------------------------------------------------

test_org_worker_assignee_cannot_reject if {
    not jobs.allow with input as state_input(org_auth(50, "worker", "worker"), org_job, "rejected")
}

test_org_worker_assignee_can_complete if {
    jobs.allow with input as state_input(org_auth(50, "worker", "worker"), org_job, "completed")
}

# The org role decides inside an organization, even for a global "user".
test_org_worker_role_with_user_privilege_cannot_reject if {
    not jobs.allow with input as state_input(org_auth(50, "user", "worker"), org_job, "rejected")
}

test_org_roleless_worker_assignee_cannot_reject if {
    not jobs.allow with input as state_input(org_auth(50, "worker", null), org_job, "rejected")
}

test_org_roleless_worker_assignee_can_complete if {
    jobs.allow with input as state_input(org_auth(50, "worker", null), org_job, "completed")
}

test_org_maintainer_can_reject if {
    jobs.allow with input as state_input(org_auth(2, "user", "maintainer"), org_job, "rejected")
}

test_org_owner_can_reject if {
    jobs.allow with input as state_input(org_auth(999, "user", "owner"), org_job, "rejected")
}

# Supervisor reaches update:state through job staff membership (task owner here).
test_org_supervisor_task_owner_can_reject if {
    jobs.allow with input as state_input(org_auth(60, "user", "supervisor"), org_job, "rejected")
}

test_org_reviewer_can_reject if {
    jobs.allow with input as state_input(org_auth(1, "user", "reviewer"), org_job, "rejected")
}

test_global_reviewer_with_org_worker_role_cannot_reject if {
    not jobs.allow with input as state_input(org_auth(50, "reviewer", "worker"), org_job, "rejected")
}

test_org_admin_can_reject if {
    jobs.allow with input as state_input(org_auth(1, "admin", "worker"), org_job, "rejected")
}

test_org_reviewer_of_other_org_cannot_reject if {
    not jobs.allow with input as state_input(org_auth(1, "user", "reviewer"), job(11), "rejected")
}
