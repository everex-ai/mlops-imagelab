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

import django_rq
from crum import get_current_user
from django.conf import settings
from django.db import transaction
from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.utils import timezone

from cvat.apps.engine.issue_snapshots import load_job_data, serialize_frame
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
    job_data = load_job_data(db_job)
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


def run_job_snapshot_capture(**capture_kwargs) -> None:
    """RQ worker entry point. Isolates every failure (R20)."""
    try:
        capture_job_snapshot(**capture_kwargs)
    except Exception:  # noqa: BLE001 - capture must never escalate
        logger.exception("Failed to capture job snapshot for job %s", capture_kwargs.get("job_id"))


def enqueue_job_snapshot(**capture_kwargs) -> None:
    """Enqueue on the notifications queue (utils worker). Failures are swallowed (R20).

    Must pass kwargs via RQ's explicit `kwargs=` form, not `**capture_kwargs`: RQ
    reserves `job_id` in its own call signature (it's the RQ job's id, not ours),
    so splatting our `job_id` straight in gets captured and stripped by RQ instead
    of reaching `run_job_snapshot_capture`.
    """
    try:
        queue = django_rq.get_queue(settings.CVAT_QUEUES.NOTIFICATIONS.value)
        queue.enqueue(run_job_snapshot_capture, kwargs=capture_kwargs)
    except Exception:  # noqa: BLE001 - enqueue must not break the job transition
        logger.exception("Failed to enqueue job snapshot for job %s", capture_kwargs.get("job_id"))


_PENDING_ATTR = "_pending_job_snapshot"


@receiver(pre_save, sender=Job)
def remember_job_transition(sender, instance: Job, update_fields=None, **kwargs):
    """Compare against the stored row before it is overwritten.

    Classification must happen here (the old values are gone after save) but the
    enqueue waits for post_save + commit, so the worker reads committed state.
    """
    instance.__dict__.pop(_PENDING_ATTR, None)
    if instance.pk is None:
        return
    if update_fields and set(update_fields) <= {"updated_date", "assignee_updated_date"}:
        return
    old = Job.objects.filter(pk=instance.pk).values("stage", "state").first()
    if old is None:
        return
    trigger = classify_job_transition(
        old_stage=old["stage"],
        old_state=old["state"],
        new_stage=instance.stage,
        new_state=instance.state,
    )
    if trigger is None:
        return
    user = get_current_user()
    setattr(
        instance,
        _PENDING_ATTR,
        dict(
            job_id=instance.pk,
            trigger=trigger.value,
            from_stage=old["stage"],
            from_state=old["state"],
            to_stage=instance.stage,
            to_state=instance.state,
            actor_id=getattr(user, "id", None),
            transitioned_at=timezone.now(),
        ),
    )


@receiver(post_save, sender=Job)
def schedule_job_snapshot(sender, instance: Job, created: bool, **kwargs):
    capture_kwargs = instance.__dict__.pop(_PENDING_ATTR, None)
    if created or capture_kwargs is None:
        return
    transaction.on_commit(lambda: enqueue_job_snapshot(**capture_kwargs), robust=True)
