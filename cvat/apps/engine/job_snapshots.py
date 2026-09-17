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

import logging
from datetime import datetime

from django.db import transaction

from cvat.apps.engine.issue_snapshots import serialize_frame
from cvat.apps.engine.models import (
    Job,
    JobAnnotationSnapshot,
    JobAnnotationSnapshotFrame,
    JobSnapshotTrigger,
    StageChoice,
    StateChoice,
)

logger = logging.getLogger(__name__)

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


def build_job_snapshot_frames(db_job: Job) -> list[dict]:
    """Every included frame of the job, densified (tracks interpolated), in the
    same payload shape as issue snapshots. Empty frames are kept: "no keypoints"
    and "not recorded" must stay distinguishable (R24)."""
    from cvat.apps.dataset_manager.bindings import JobData
    from cvat.apps.dataset_manager.task import JobAnnotation

    db_job = JobAnnotation.add_prefetch_info(Job.objects.filter(pk=db_job.id)).get()
    annotation = JobAnnotation(pk=db_job.id, db_job=db_job)
    annotation.init_from_db()
    job_data = JobData(
        annotation_ir=annotation.ir_data,
        db_job=db_job,
        host="",
        use_server_track_ids=True,
    )
    return [serialize_frame(m) for m in job_data.group_by_frame(include_empty=True)]


def capture_job_snapshot(
    *,
    job_id: int,
    trigger: str,
    from_stage: str,
    from_state: str,
    to_stage: str,
    to_state: str,
    actor_id: int | None,
    transitioned_at: datetime,
) -> JobAnnotationSnapshot | None:
    """Capture and persist one job snapshot. Returns None if the job is gone."""
    if trigger not in JobSnapshotTrigger.values:
        raise ValueError(f"unknown job snapshot trigger {trigger!r}")

    job = Job.objects.filter(pk=job_id).first()
    if job is None:
        logger.info("Job %s no longer exists; skipping %s snapshot", job_id, trigger)
        return None

    frames = build_job_snapshot_frames(job)
    with transaction.atomic():
        snapshot = JobAnnotationSnapshot.objects.create(
            job=job,
            trigger=trigger,
            from_stage=from_stage,
            from_state=from_state,
            to_stage=to_stage,
            to_state=to_state,
            actor_id=actor_id,
            transitioned_at=transitioned_at,
            frame_count=len(frames),
        )
        JobAnnotationSnapshotFrame.objects.bulk_create(
            JobAnnotationSnapshotFrame(snapshot=snapshot, frame=f["frame"], data=f) for f in frames
        )
    logger.info(
        "Captured %s job snapshot %s for job %s (%d frames)",
        trigger,
        snapshot.id,
        job_id,
        len(frames),
    )
    return snapshot
