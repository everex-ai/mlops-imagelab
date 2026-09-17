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

from unittest import mock

from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from cvat.apps.engine import models
from cvat.apps.engine.job_snapshots import (
    capture_job_snapshot,
    classify_job_transition,
    enqueue_job_snapshot,
    run_job_snapshot_capture,
)
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


def _capture(job, **overrides):
    kwargs = dict(
        job_id=job.id,
        trigger=JobSnapshotTrigger.SUBMITTED,
        from_stage="annotation",
        from_state="in progress",
        to_stage="annotation",
        to_state="completed",
        actor_id=None,
        transitioned_at=timezone.now(),
    )
    kwargs.update(overrides)
    return capture_job_snapshot(**kwargs)


class CaptureJobSnapshotTest(TestCase):
    def test_every_frame_is_stored_including_empty_ones(self):
        _, job, labels = _make_job(size=3, label_names=("person",))
        models.LabeledShape.objects.create(
            job=job,
            label=labels["person"],
            frame=1,
            type="points",
            points=[10.0, 20.0],
            occluded=False,
            outside=False,
            z_order=0,
            group=0,
            rotation=0.0,
            source="manual",
        )
        snap = _capture(job)
        self.assertEqual(snap.frame_count, 3)
        self.assertEqual(
            list(snap.frames.order_by("frame").values_list("frame", flat=True)), [0, 1, 2]
        )
        self.assertEqual(snap.frames.get(frame=0).data["objects"], [])
        self.assertEqual(snap.frames.get(frame=1).data["objects"][0]["points"], [10.0, 20.0])

    def test_frame_payload_matches_issue_snapshot_shape(self):
        _, job, _ = _make_job(size=1)
        snap = _capture(job)
        self.assertEqual(
            set(snap.frames.get(frame=0).data),
            {"frame", "abs_frame", "name", "width", "height", "objects"},
        )

    def test_transition_metadata_is_stored(self):
        _, job, _ = _make_job()
        user = models.User.objects.create_user(username="rev", password="x")
        at = timezone.now()
        snap = _capture(
            job,
            trigger=JobSnapshotTrigger.REJECTED,
            from_state="completed",
            to_state="rejected",
            actor_id=user.id,
            transitioned_at=at,
        )
        self.assertEqual(
            (snap.trigger, snap.from_state, snap.to_state, snap.actor_id, snap.transitioned_at),
            ("rejected", "completed", "rejected", user.id, at),
        )

    def test_the_geometry_is_frozen_at_capture_time(self):
        _, job, labels = _make_job(size=1, label_names=("person",))
        shape = models.LabeledShape.objects.create(
            job=job,
            label=labels["person"],
            frame=0,
            type="points",
            points=[1.0, 1.0],
            occluded=False,
            outside=False,
            z_order=0,
            group=0,
            rotation=0.0,
            source="manual",
        )
        snap = _capture(job)
        models.LabeledShape.objects.filter(pk=shape.pk).update(points=[9.0, 9.0])
        self.assertEqual(snap.frames.get(frame=0).data["objects"][0]["points"], [1.0, 1.0])

    def test_mask_is_excluded(self):
        _, job, labels = _make_job(size=1, label_names=("region",))
        models.LabeledShape.objects.create(
            job=job,
            label=labels["region"],
            frame=0,
            type="mask",
            points=[0.0, 0.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0],
            occluded=False,
            outside=False,
            z_order=0,
            group=0,
            rotation=0.0,
            source="manual",
        )
        self.assertEqual(_capture(job).frames.get(frame=0).data["objects"], [])

    def test_deleted_job_is_noop(self):
        # The worker runs after commit; the job may be gone by then.
        _, job, _ = _make_job()
        job_id = job.id
        job.delete()
        result = capture_job_snapshot(
            job_id=job_id,
            trigger=JobSnapshotTrigger.SUBMITTED,
            from_stage="annotation",
            from_state="in progress",
            to_stage="annotation",
            to_state="completed",
            actor_id=None,
            transitioned_at=timezone.now(),
        )
        self.assertIsNone(result)
        self.assertEqual(JobAnnotationSnapshot.objects.count(), 0)


_ENQUEUE_JOB = "cvat.apps.engine.job_snapshots.enqueue_job_snapshot"
_JOB_GET_QUEUE = "cvat.apps.engine.job_snapshots.django_rq.get_queue"


class _SyncQueue:
    def enqueue(self, func, *args, **kwargs):
        return func(*args, **kwargs)


class JobSnapshotHookTest(TestCase):
    """Every path that changes stage/state goes through Job.save(), so the hook
    lives on the model signals (JobWriteSerializer.update and consensus merging)."""

    def _transition(self, job, **fields):
        with mock.patch(_ENQUEUE_JOB) as enq:
            with self.captureOnCommitCallbacks(execute=True):
                for name, value in fields.items():
                    setattr(job, name, value)
                job.save()
        return enq

    def test_submit_schedules_a_snapshot(self):
        _, job, _ = _make_job()
        models.Job.objects.filter(pk=job.pk).update(state="in progress")
        job.refresh_from_db()
        enq = self._transition(job, state="completed")
        enq.assert_called_once()
        kwargs = enq.call_args.kwargs
        self.assertEqual(
            (kwargs["job_id"], kwargs["trigger"], kwargs["from_state"], kwargs["to_state"]),
            (job.id, JobSnapshotTrigger.SUBMITTED, "in progress", "completed"),
        )

    def test_reject_and_accept_schedule_snapshots(self):
        _, job, _ = _make_job()
        models.Job.objects.filter(pk=job.pk).update(state="completed")
        job.refresh_from_db()
        self.assertEqual(
            self._transition(job, state="rejected").call_args.kwargs["trigger"],
            JobSnapshotTrigger.REJECTED,
        )
        models.Job.objects.filter(pk=job.pk).update(state="completed")
        job.refresh_from_db()
        self.assertEqual(
            self._transition(job, stage="acceptance").call_args.kwargs["trigger"],
            JobSnapshotTrigger.ACCEPTED,
        )

    def test_non_boundary_saves_schedule_nothing(self):
        _, job, _ = _make_job()
        self._transition(job, state="in progress").assert_not_called()
        self._transition(job).assert_not_called()  # plain re-save

    def test_job_creation_schedules_nothing(self):
        with mock.patch(_ENQUEUE_JOB) as enq:
            with self.captureOnCommitCallbacks(execute=True):
                _make_job()
        enq.assert_not_called()

    def test_updated_date_touch_schedules_nothing(self):
        _, job, _ = _make_job()
        with mock.patch(_ENQUEUE_JOB) as enq:
            with self.captureOnCommitCallbacks(execute=True):
                job.touch()
        enq.assert_not_called()

    def test_enqueue_failure_does_not_break_the_save(self):
        # R20: a Redis outage must never fail the reviewer's transition.
        _, job, _ = _make_job()
        models.Job.objects.filter(pk=job.pk).update(state="in progress")
        job.refresh_from_db()
        with mock.patch(_JOB_GET_QUEUE, side_effect=ConnectionError("no redis")):
            with self.captureOnCommitCallbacks(execute=True):
                job.state = "completed"
                job.save()
        job.refresh_from_db()
        self.assertEqual(job.state, "completed")

    def test_worker_isolates_capture_failures(self):
        with mock.patch(
            "cvat.apps.engine.job_snapshots.capture_job_snapshot",
            side_effect=RuntimeError("boom"),
        ):
            self.assertIsNone(run_job_snapshot_capture(job_id=1, trigger="submitted"))

    def test_end_to_end_transition_persists_snapshot(self):
        _, job, _ = _make_job(size=2)
        models.Job.objects.filter(pk=job.pk).update(state="in progress")
        job.refresh_from_db()
        with mock.patch(_JOB_GET_QUEUE, return_value=_SyncQueue()):
            with self.captureOnCommitCallbacks(execute=True):
                job.state = "completed"
                job.save()
        snap = JobAnnotationSnapshot.objects.get(job=job)
        self.assertEqual((snap.trigger, snap.frame_count), ("submitted", 2))
