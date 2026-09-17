# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Read API for job round snapshots and issue history (admin-only).

Consumed by Beacon's job detail viewer; excluded from the OpenAPI schema like the
rest of production_stats. These tests talk to a real OPA instance.
"""

from __future__ import annotations

from datetime import timedelta

from django.utils import timezone
from rest_framework import status

from cvat.apps.engine.models import (
    JobAnnotationSnapshot,
    JobAnnotationSnapshotFrame,
    Project,
)
from cvat.apps.engine.tests.utils import ApiTestBase
from cvat.apps.production_stats.tests.test_endpoints import create_db_users, create_job

SNAPSHOTS = "/api/production_stats/job_snapshots"


class JobSnapshotsApiTest(ApiTestBase):
    @classmethod
    def setUpTestData(cls):
        create_db_users(cls)
        cls.job = create_job(project=Project.objects.create(name="History"), task_name="history")
        cls.other_job = create_job(project=Project.objects.create(name="Other"), task_name="other")
        now = timezone.now()
        cls.submitted = cls._snapshot(cls.job, "submitted", now - timedelta(hours=2), frames=3)
        cls.rejected = cls._snapshot(cls.job, "rejected", now - timedelta(hours=1), frames=3)
        cls._snapshot(cls.other_job, "submitted", now, frames=1)

    @staticmethod
    def _snapshot(job, trigger, at, *, frames):
        snap = JobAnnotationSnapshot.objects.create(
            job=job, trigger=trigger, from_stage="annotation", from_state="in progress",
            to_stage="annotation", to_state="completed", transitioned_at=at,
            frame_count=frames,
        )
        JobAnnotationSnapshotFrame.objects.bulk_create(
            JobAnnotationSnapshotFrame(
                snapshot=snap, frame=i, data={"frame": i, "objects": [{"points": [i, i]}]}
            )
            for i in range(frames)
        )
        return snap

    def test_list_returns_only_this_jobs_snapshots_in_transition_order(self):
        response = self._get_request(SNAPSHOTS, self.admin, query_params={"job_id": self.job.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["job_id"], self.job.id)
        self.assertEqual(
            [s["id"] for s in body["snapshots"]], [self.submitted.id, self.rejected.id]
        )
        self.assertEqual(body["snapshots"][0]["frame_count"], 3)
        self.assertNotIn("frames", body["snapshots"][0])

    def test_list_requires_job_id(self):
        response = self._get_request(SNAPSHOTS, self.admin)
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retrieve_returns_the_requested_frame_range(self):
        response = self._get_request(
            f"{SNAPSHOTS}/{self.submitted.id}", self.admin,
            query_params={"frame_from": 1, "frame_to": 2},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([f["frame"] for f in response.json()["frames"]], [1, 2])

    def test_retrieve_rejects_ranges_over_the_cap(self):
        response = self._get_request(
            f"{SNAPSHOTS}/{self.submitted.id}", self.admin,
            query_params={"frame_from": 0, "frame_to": 20},
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retrieve_missing_snapshot_is_404(self):
        response = self._get_request(
            f"{SNAPSHOTS}/99999999", self.admin, query_params={"frame_from": 0, "frame_to": 0}
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_non_admins_are_denied_before_existence_is_revealed(self):
        for user in (self.user, self.worker):
            for path, params in (
                (SNAPSHOTS, {"job_id": self.job.id}),
                (f"{SNAPSHOTS}/{self.submitted.id}", {"frame_from": 0, "frame_to": 0}),
                (f"{SNAPSHOTS}/99999999", {"frame_from": 0, "frame_to": 0}),
            ):
                with self.subTest(user=user.username, path=path):
                    response = self._get_request(path, user, query_params=params)
                    self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
