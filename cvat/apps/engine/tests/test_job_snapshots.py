# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Job annotation snapshots captured at round boundaries.

A job's round history (submit -> review -> reject -> resubmit -> accept) is only
visible later if the geometry at each boundary is frozen: CVAT keeps the current
annotation state only, and annotation change events keep object ids but drop the
coordinates. See label_supporter docs/brainstorms/2026-09-17-imagelab-job-detail-
viewer-requirements.md (KD1, KD2).
"""

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from cvat.apps.engine import models
from cvat.apps.engine.job_snapshots import classify_job_transition
from cvat.apps.engine.models import (
    JobAnnotationSnapshot,
    JobAnnotationSnapshotFrame,
    JobSnapshotTrigger,
)
from cvat.apps.engine.tests.test_issue_snapshots_capture import _make_job


def _snapshot(job, trigger=JobSnapshotTrigger.SUBMITTED, **kwargs):
    return JobAnnotationSnapshot.objects.create(
        job=job,
        trigger=trigger,
        from_stage="annotation",
        from_state="in progress",
        to_stage="annotation",
        to_state="completed",
        transitioned_at=timezone.now(),
        **kwargs,
    )


class JobAnnotationSnapshotModelTest(TestCase):
    def test_frames_round_trip_json(self):
        _, job, _ = _make_job()
        snap = _snapshot(job, frame_count=1)
        JobAnnotationSnapshotFrame.objects.create(
            snapshot=snap, frame=0, data={"frame": 0, "objects": [{"points": [1.5, 2.5]}]}
        )
        stored = snap.frames.get(frame=0)
        self.assertEqual(stored.data["objects"][0]["points"], [1.5, 2.5])

    def test_one_row_per_frame_per_snapshot(self):
        _, job, _ = _make_job()
        snap = _snapshot(job)
        JobAnnotationSnapshotFrame.objects.create(snapshot=snap, frame=0, data={})
        with self.assertRaises(IntegrityError), transaction.atomic():
            JobAnnotationSnapshotFrame.objects.create(snapshot=snap, frame=0, data={})

    def test_repeated_transitions_keep_every_snapshot(self):
        # R21: reject -> resubmit within minutes is a real pattern (job 74236). Never dedupe.
        _, job, _ = _make_job()
        _snapshot(job, JobSnapshotTrigger.SUBMITTED)
        _snapshot(job, JobSnapshotTrigger.REJECTED)
        _snapshot(job, JobSnapshotTrigger.SUBMITTED)
        self.assertEqual(job.annotation_snapshots.count(), 3)

    def test_cascade_on_job_delete(self):
        # KD11: kept indefinitely, removed only together with the job.
        _, job, _ = _make_job()
        snap = _snapshot(job)
        JobAnnotationSnapshotFrame.objects.create(snapshot=snap, frame=0, data={})
        job.delete()
        self.assertEqual(JobAnnotationSnapshot.objects.count(), 0)
        self.assertEqual(JobAnnotationSnapshotFrame.objects.count(), 0)

    def test_actor_is_kept_null_when_user_is_deleted(self):
        _, job, _ = _make_job()
        user = models.User.objects.create_user(username="gone", password="x")
        snap = _snapshot(job, actor=user)
        user.delete()
        snap.refresh_from_db()
        self.assertIsNone(snap.actor_id)


class ClassifyJobTransitionTest(SimpleTestCase):
    """Boundaries observed on production jobs 74236, 77315, 78299 (2026-09-17)."""

    def _classify(self, old, new):
        return classify_job_transition(
            old_stage=old[0], old_state=old[1], new_stage=new[0], new_state=new[1]
        )

    def test_submit_is_state_to_completed(self):
        for old_state in ("new", "in progress", "rejected"):
            with self.subTest(old_state=old_state):
                self.assertEqual(
                    self._classify(("annotation", old_state), ("annotation", "completed")),
                    JobSnapshotTrigger.SUBMITTED,
                )

    def test_reject_is_completed_to_rejected_or_in_progress(self):
        for new_state in ("rejected", "in progress"):
            with self.subTest(new_state=new_state):
                self.assertEqual(
                    self._classify(("annotation", "completed"), ("annotation", new_state)),
                    JobSnapshotTrigger.REJECTED,
                )

    def test_accept_is_stage_to_acceptance_whatever_the_state(self):
        # JobWriteSerializer resets state to `new` when only the stage is sent.
        for new_state in ("new", "completed"):
            with self.subTest(new_state=new_state):
                self.assertEqual(
                    self._classify(("annotation", "completed"), ("acceptance", new_state)),
                    JobSnapshotTrigger.ACCEPTED,
                )

    def test_non_boundaries(self):
        for old, new in (
            (("annotation", "new"), ("annotation", "in progress")),  # started work
            (("annotation", "completed"), ("annotation", "completed")),  # no change
            (("acceptance", "completed"), ("acceptance", "completed")),
            (("annotation", "completed"), ("validation", "new")),  # stage unused here
        ):
            with self.subTest(old=old, new=new):
                self.assertIsNone(self._classify(old, new))
