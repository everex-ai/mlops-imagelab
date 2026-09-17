# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Freeze a job's whole annotation geometry at each round boundary.

A viewer that replays a job's rounds (submit -> reject -> resubmit -> accept)
needs the geometry each boundary had. CVAT stores only the current state, and
`handle_annotations_change` keeps object ids but drops coordinates, so nothing
else can reconstruct it. Captured async, best-effort: a capture failure must
never fail the job transition that triggered it.

Boundaries follow production (see `JobSnapshotTrigger`): work stays in stage
`annotation` and moves by state; only acceptance changes the stage.
"""

from __future__ import annotations

from cvat.apps.engine.models import JobSnapshotTrigger, StageChoice, StateChoice

_ACCEPTANCE = StageChoice.ACCEPTANCE.value
_COMPLETED = StateChoice.COMPLETED.value
_REOPENED_STATES = frozenset({StateChoice.REJECTED.value, StateChoice.IN_PROGRESS.value})


def classify_job_transition(
    *, old_stage: str, old_state: str, new_stage: str, new_state: str
) -> JobSnapshotTrigger | None:
    """Return the round boundary this transition crosses, or None."""
    if new_stage == _ACCEPTANCE and old_stage != _ACCEPTANCE:
        return JobSnapshotTrigger.ACCEPTED
    if new_stage != old_stage:
        # Other stage moves (e.g. validation) are not used by this organisation's
        # workflow; treating them as boundaries would invent rounds job_rounds lacks.
        return None
    if new_state == _COMPLETED and old_state != _COMPLETED:
        return JobSnapshotTrigger.SUBMITTED
    if old_state == _COMPLETED and new_state in _REOPENED_STATES:
        return JobSnapshotTrigger.REJECTED
    return None
