# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Read API for job round snapshots and issue history (admin-only).

Consumed by Beacon's job detail viewer; excluded from the OpenAPI schema like the
rest of production_stats. These tests talk to a real OPA instance.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone
from rest_framework import status

from cvat.apps.engine.models import (
    Comment,
    Issue,
    IssueAnnotationSnapshot,
    IssueResolutionChange,
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
            job=job,
            trigger=trigger,
            from_stage="annotation",
            from_state="in progress",
            to_stage="annotation",
            to_state="completed",
            transitioned_at=at,
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
            f"{SNAPSHOTS}/{self.submitted.id}",
            self.admin,
            query_params={"frame_from": 1, "frame_to": 2},
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual([f["frame"] for f in response.json()["frames"]], [1, 2])

    def test_retrieve_rejects_ranges_over_the_cap(self):
        response = self._get_request(
            f"{SNAPSHOTS}/{self.submitted.id}",
            self.admin,
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


ISSUES = "/api/production_stats/job_issues"


class JobIssuesApiTest(ApiTestBase):
    @classmethod
    def setUpTestData(cls):
        create_db_users(cls)
        cls.job = create_job(project=Project.objects.create(name="Issues"), task_name="issues")
        other = create_job(project=Project.objects.create(name="Else"), task_name="else")

        cls.issue = Issue.objects.create(
            job=cls.job, frame=2, position=[10.0, 20.0], owner=cls.admin, resolved=True
        )
        Comment.objects.create(issue=cls.issue, owner=cls.admin, message="무릎이 낮음")
        IssueResolutionChange.objects.create(issue=cls.issue, resolved=True, actor=cls.admin)
        IssueResolutionChange.objects.create(issue=cls.issue, resolved=False, actor=cls.admin)
        IssueResolutionChange.objects.create(issue=cls.issue, resolved=True, actor=cls.admin)
        IssueAnnotationSnapshot.objects.create(
            issue=cls.issue, job=cls.job, trigger="before", frame=2, data={"objects": []}
        )
        # A row left by the short-lived 07-07 build: the reader must not choke on it.
        # objects.create() does not run choices validation, so the stale value stores as-is.
        IssueAnnotationSnapshot.objects.create(
            issue=cls.issue, job=cls.job, trigger="after", frame=2, data={}
        )

        cls.untouched = Issue.objects.create(job=cls.job, frame=0, position=[1.0, 1.0])
        Issue.objects.create(job=other, frame=0, position=[0.0, 0.0])

    def test_lists_this_jobs_issues_with_history(self):
        response = self._get_request(ISSUES, self.admin, query_params={"job_id": self.job.id})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        issues = response.json()["issues"]
        self.assertEqual([i["id"] for i in issues], sorted([self.issue.id, self.untouched.id]))

        issue = next(i for i in issues if i["id"] == self.issue.id)
        self.assertEqual((issue["frame"], issue["position"]), (2, [10.0, 20.0]))
        self.assertEqual(issue["comments"][0]["message"], "무릎이 낮음")
        self.assertEqual([c["resolved"] for c in issue["resolution_changes"]], [True, False, True])
        self.assertEqual(sorted(s["trigger"] for s in issue["snapshots"]), ["after", "before"])

    def test_an_issue_without_history_has_empty_lists_not_missing_keys(self):
        response = self._get_request(ISSUES, self.admin, query_params={"job_id": self.job.id})
        untouched = next(i for i in response.json()["issues"] if i["id"] == self.untouched.id)
        self.assertEqual(
            (untouched["comments"], untouched["resolution_changes"], untouched["snapshots"]),
            ([], [], []),
        )

    def test_query_count_does_not_grow_with_issues(self):
        # Warm up: the first request through this route pays a one-off cost
        # (LastActivityMiddleware's first-ever Profile update for `admin` in this
        # test) that would otherwise land on whichever measurement runs first.
        self._get_request(ISSUES, self.admin, query_params={"job_id": self.job.id})

        # Measured *before* adding issues: prefetch keeps it constant, a per-issue
        # query would add at least 5 here.
        with CaptureQueriesContext(connection) as before:
            self._get_request(ISSUES, self.admin, query_params={"job_id": self.job.id})
        for frame in range(5):
            extra = Issue.objects.create(job=self.job, frame=frame, position=[0.0, 0.0])
            Comment.objects.create(issue=extra, owner=self.admin, message="x")
            IssueResolutionChange.objects.create(issue=extra, resolved=True, actor=self.admin)
        with CaptureQueriesContext(connection) as after:
            self._get_request(ISSUES, self.admin, query_params={"job_id": self.job.id})
        self.assertEqual(len(after.captured_queries), len(before.captured_queries))

    def test_non_admins_are_denied(self):
        for user in (self.user, self.worker):
            with self.subTest(user=user.username):
                response = self._get_request(ISSUES, user, query_params={"job_id": self.job.id})
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
