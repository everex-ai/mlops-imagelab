# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from django.contrib.auth.models import User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status

from cvat.apps.engine.models import Issue, Job, Project
from cvat.apps.engine.tests.utils import ApiTestBase
from cvat.apps.production_stats.serializers import MAX_PERIOD
from cvat.apps.production_stats.tests.test_endpoints import (
    ISSUE_FACTS_PATH,
    PERIOD,
    PERIOD_END,
    PERIOD_START,
    UTC,
    create_db_users,
    create_job,
)

INSIDE = PERIOD_START + timedelta(days=3)


def add_issue(job: Job, *, frame: int, created: datetime = INSIDE) -> Issue:
    """
    A real Issue row with a chosen creation time.

    ``created_date`` is ``auto_now_add``, so it cannot be set through ``create()``; the
    follow-up ``update()`` is the only way to put an issue at a known instant.
    """
    issue = Issue.objects.create(job=job, frame=frame, position=[1.0, 2.0])
    Issue.objects.filter(id=issue.id).update(created_date=created)
    return issue


class IssueFactsTest(ApiTestBase):
    """
    Review feedback per assignee, read from Postgres alone.

    Like the object counts route this never touches ClickHouse, so the tests do not fake
    one - a statement that needed it would fail loudly instead of reading a stub.
    """

    @classmethod
    def setUpTestData(cls):
        create_db_users(cls)

        cls.alice = User.objects.create_user(username="alice", password="alice")
        cls.bob = User.objects.create_user(username="bob", password="bob")

        project = Project.objects.create(name="Wrist flexion")
        cls.job_alice = create_job(project=project, task_name="alpha", assignee=cls.alice)
        cls.job_alice_2 = create_job(project=project, task_name="beta", assignee=cls.alice)
        cls.job_bob = create_job(project=project, task_name="gamma", assignee=cls.bob)
        cls.job_nobody = create_job(project=project, task_name="delta")

    def _read(self, **query_params) -> dict[str, Any]:
        response = self._get_request(
            ISSUE_FACTS_PATH, user=self.admin, query_params={**PERIOD, **query_params}
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()

    def _row(self, payload: dict[str, Any], user: User) -> dict[str, Any]:
        rows = [row for row in payload["results"] if row["assignee"]["id"] == user.id]
        self.assertEqual(len(rows), 1, payload)
        return rows[0]

    def test_several_issues_on_one_frame_are_one_flagged_frame(self):
        for _ in range(3):
            add_issue(self.job_alice, frame=5)
        add_issue(self.job_alice, frame=7)

        row = self._row(self._read(), self.alice)

        self.assertEqual(row["issues"], 4)
        self.assertEqual(row["flagged_frames"], 2)

    def test_the_same_frame_number_on_two_jobs_is_two_flagged_frames(self):
        # A frame number means nothing outside its job; frame 5 of two different jobs are
        # two different images.
        add_issue(self.job_alice, frame=5)
        add_issue(self.job_alice_2, frame=5)

        row = self._row(self._read(), self.alice)

        self.assertEqual(row["flagged_frames"], 2)

    def test_rows_are_grouped_by_the_jobs_assignee(self):
        add_issue(self.job_alice, frame=1)
        add_issue(self.job_bob, frame=1)
        add_issue(self.job_bob, frame=2)

        payload = self._read()

        self.assertEqual(self._row(payload, self.alice)["issues"], 1)
        self.assertEqual(self._row(payload, self.bob)["issues"], 2)
        self.assertEqual(self._row(payload, self.bob)["assignee"]["username"], "bob")

    def test_a_reassigned_job_credits_its_current_assignee(self):
        add_issue(self.job_alice, frame=1)
        Job.objects.filter(id=self.job_alice.id).update(assignee=self.bob)

        payload = self._read()

        self.assertEqual(self._row(payload, self.bob)["issues"], 1)
        self.assertFalse(any(row["assignee"]["id"] == self.alice.id for row in payload["results"]))

    def test_issues_on_unassigned_jobs_are_reported_apart_rather_than_dropped(self):
        add_issue(self.job_nobody, frame=1)
        add_issue(self.job_nobody, frame=1)
        add_issue(self.job_nobody, frame=2)

        payload = self._read()

        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["unassigned"], {"issues": 3, "flagged_frames": 2})

    def test_the_window_is_half_open(self):
        add_issue(self.job_alice, frame=1, created=PERIOD_START)
        add_issue(self.job_alice, frame=2, created=PERIOD_END - timedelta(microseconds=1))
        add_issue(self.job_alice, frame=3, created=PERIOD_END)
        add_issue(self.job_alice, frame=4, created=PERIOD_START - timedelta(microseconds=1))

        row = self._row(self._read(), self.alice)

        self.assertEqual(row["flagged_frames"], 2)

    def test_an_empty_window_is_an_empty_list_with_zero_unassigned(self):
        payload = self._read()

        self.assertEqual(payload["count"], 0)
        self.assertEqual(payload["results"], [])
        self.assertEqual(payload["unassigned"], {"issues": 0, "flagged_frames": 0})
        self.assertIsNone(payload["next"])

    def test_the_period_is_echoed_back(self):
        payload = self._read()

        self.assertEqual(
            datetime.fromisoformat(payload["period"]["start"].replace("Z", "+00:00")),
            PERIOD_START,
        )
        self.assertEqual(
            datetime.fromisoformat(payload["period"]["end"].replace("Z", "+00:00")),
            PERIOD_END,
        )

    def test_rows_come_back_sorted_by_assignee_id(self):
        add_issue(self.job_bob, frame=1)
        add_issue(self.job_alice, frame=1)

        ids = [row["assignee"]["id"] for row in self._read()["results"]]

        self.assertEqual(ids, sorted(ids))

    def test_the_aggregate_is_one_statement_however_many_issues(self):
        for frame in range(20):
            add_issue(self.job_alice, frame=frame)
            add_issue(self.job_bob, frame=frame)

        with CaptureQueriesContext(connection) as captured:
            self._read()

        aggregates = [
            query for query in captured.captured_queries if "engine_issue" in query["sql"]
        ]
        self.assertEqual(len(aggregates), 1, aggregates)

    def test_a_missing_period_is_rejected(self):
        response = self._get_request(ISSUE_FACTS_PATH, user=self.admin)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_period_longer_than_the_cap_is_rejected(self):
        start = datetime(2025, 1, 1, tzinfo=UTC)
        response = self._get_request(
            ISSUE_FACTS_PATH,
            user=self.admin,
            query_params={
                "period_start": start.isoformat(),
                "period_end": (start + MAX_PERIOD + timedelta(days=1)).isoformat(),
            },
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
