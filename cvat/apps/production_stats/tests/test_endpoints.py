# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import mock

from django.contrib.auth.models import Group, User
from django.db import connection
from django.test.utils import CaptureQueriesContext
from rest_framework import status

from cvat.apps.engine.models import (
    Data,
    Job,
    JobType,
    Project,
    Segment,
    SegmentType,
    StageChoice,
    StateChoice,
    Task,
)
from cvat.apps.engine.tests.utils import ApiTestBase, logging_disabled
from cvat.apps.production_stats.queries.clickhouse import ClickHouseError
from cvat.apps.production_stats.serializers import MAX_PERIOD

JOB_FACTS_PATH = "/api/production_stats/job_facts"
JOB_ROUNDS_PATH = "/api/production_stats/job_rounds/1"
ALL_PATHS = (JOB_FACTS_PATH, JOB_ROUNDS_PATH)

UTC = timezone.utc
PERIOD_START = datetime(2026, 8, 3, tzinfo=UTC)
PERIOD_END = datetime(2026, 8, 31, tzinfo=UTC)
PERIOD = {
    "period_start": PERIOD_START.isoformat(),
    "period_end": PERIOD_END.isoformat(),
}

# queries.default_executor() resolves run_query from this module on every call, so replacing
# the module attribute is enough to keep every test in this file off a live ClickHouse.
RUN_QUERY = "cvat.apps.production_stats.queries.clickhouse.run_query"


class FakeClickHouse:
    """
    Stands in for the ClickHouse executor.

    Statements are routed by a distinctive fragment of each one rather than by call order:
    the view issues five queries and reordering them must not silently rewire the fixture.
    An unrecognised statement is a failure rather than an empty result - the latter is what
    turns a renamed column into a green test with no rows.
    """

    def __init__(
        self,
        *,
        jobs: Sequence[tuple[int, int | None]] = (),
        lifecycle: Sequence[Mapping[str, Any]] = (),
        working_time: Sequence[Mapping[str, Any]] = (),
        daily: Sequence[Mapping[str, Any]] = (),
        last_seen: Mapping[str, Any] | None = None,
    ):
        self.jobs = list(jobs)
        self.lifecycle = list(lifecycle)
        self.working_time = list(working_time)
        self.daily = list(daily)
        self.last_seen = last_seen
        self.statements: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, sql: str, parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
        self.statements.append((sql, dict(parameters)))

        if "SELECT DISTINCT job_id" in sql:
            project_id = parameters.get("project_id")
            return [
                {"job_id": job_id}
                for job_id, job_project_id in sorted(self.jobs)
                if project_id is None or job_project_id == project_id
            ]

        if "started_at" in sql:
            wanted = set(parameters["job_ids"])
            return [dict(row) for row in self.lifecycle if row["job_id"] in wanted]

        if "working_ms" in sql:
            wanted = set(parameters["job_ids"])
            return [dict(row) for row in self.working_time if row["job_id"] in wanted]

        if "GROUP BY day" in sql:
            return [dict(row) for row in self.daily]

        if "max(timestamp) AS last_seen" in sql:
            return [dict(self.last_seen)] if self.last_seen else [{"last_seen": None, "events": 0}]

        raise AssertionError(f"unexpected statement: {sql}")


def create_db_users(cls: type[ApiTestBase]) -> None:
    group_admin, _ = Group.objects.get_or_create(name="admin")
    group_user, _ = Group.objects.get_or_create(name="user")
    group_worker, _ = Group.objects.get_or_create(name="worker")

    # OPA reads the privilege from the Django auth group, not from User.is_superuser,
    # so create_superuser() alone would still be denied.
    cls.admin = User.objects.create_superuser(username="admin", email="", password="admin")
    cls.admin.groups.add(group_admin)

    cls.user = User.objects.create_user(username="user", password="user")
    cls.user.groups.add(group_user)

    cls.worker = User.objects.create_user(username="worker", password="worker")
    cls.worker.groups.add(group_worker)


class ProductionStatsPermissionTest(ApiTestBase):
    """
    Checks that the production stats endpoints are reachable by admins only.

    These tests talk to a real OPA instance at settings.IAM_OPA_HOST, like the
    rest of the permission tests in this repository.
    """

    @classmethod
    def setUpTestData(cls):
        create_db_users(cls)

    def _get(self, path: str, user: User | None):
        query_params = PERIOD if path == JOB_FACTS_PATH else None
        with mock.patch(RUN_QUERY, FakeClickHouse()):
            return self._get_request(path, user=user, query_params=query_params)

    def test_admin_can_read_production_stats(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                response = self._get(path, user=self.admin)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_job_facts_returns_a_list_payload(self):
        response = self._get(JOB_FACTS_PATH, user=self.admin)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.json())

    def test_job_rounds_returns_a_rounds_payload(self):
        response = self._get(JOB_ROUNDS_PATH, user=self.admin)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("rounds", response.json())

    def test_regular_user_cannot_read_production_stats(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                response = self._get(path, user=self.user)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_worker_cannot_read_production_stats(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                response = self._get(path, user=self.worker)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_cannot_read_production_stats(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                response = self._get(path, user=None)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)


class JobFactsTest(ApiTestBase):
    """
    The merge of the ClickHouse derived values with the Postgres identity.

    ClickHouse is faked (see FakeClickHouse); Postgres is real, because the two things this
    endpoint takes from it - Segment.frame_count and the presence or absence of a job row -
    are exactly what a fake would get wrong.
    """

    @classmethod
    def setUpTestData(cls):
        create_db_users(cls)

        cls.annotator = User.objects.create_user(username="annotator", password="annotator")
        cls.reviewer = User.objects.create_user(username="reviewer", password="reviewer")
        cls.outsider = User.objects.create_user(username="outsider", password="outsider")

        cls.project_alpha = Project.objects.create(name="Alpha")
        cls.project_beta = Project.objects.create(name="Beta")

        # A plain range segment: 5 frames out of a 10 frame task.
        cls.job_alpha = cls._create_job(
            project=cls.project_alpha,
            task_name="alpha-range",
            start_frame=0,
            stop_frame=4,
            assignee=cls.annotator,
            stage=StageChoice.ACCEPTANCE,
            state=StateChoice.COMPLETED,
        )

        # A specific-frames segment spanning the whole task: stop_frame - start_frame + 1
        # would say 10, the real frame set holds 3.
        cls.job_specific = cls._create_job(
            project=cls.project_alpha,
            task_name="alpha-specific",
            start_frame=0,
            stop_frame=9,
            assignee=cls.annotator,
            stage=StageChoice.ANNOTATION,
            state=StateChoice.IN_PROGRESS,
            frames=[0, 2, 4],
        )

        # Another project, and nobody assigned to it.
        cls.job_beta = cls._create_job(
            project=cls.project_beta,
            task_name="beta-range",
            start_frame=0,
            stop_frame=9,
            assignee=None,
            stage=StageChoice.ANNOTATION,
            state=StateChoice.IN_PROGRESS,
        )

        # A job id ClickHouse still remembers after its task cascaded away in Postgres.
        cls.deleted_job_id = cls.job_beta.id + 10_000

    @classmethod
    def _create_job(
        cls,
        *,
        project: Project,
        task_name: str,
        start_frame: int,
        stop_frame: int,
        assignee: User | None,
        stage: StageChoice,
        state: StateChoice,
        frames: Sequence[int] | None = None,
    ) -> Job:
        data = Data.objects.create(size=10, start_frame=0, stop_frame=9, image_quality=70)
        task = Task.objects.create(name=task_name, project=project, data=data, mode="annotation")
        segment = Segment.objects.create(
            task=task,
            start_frame=start_frame,
            stop_frame=stop_frame,
            type=SegmentType.SPECIFIC_FRAMES if frames else SegmentType.RANGE,
            frames=list(frames or []),
        )

        return Job.objects.create(
            segment=segment,
            assignee=assignee,
            stage=stage.value,
            state=state.value,
            type=JobType.ANNOTATION.value,
        )

    # ---------------------------------------------------------------- fixtures

    def _all_jobs(self) -> list[tuple[int, int | None]]:
        return [
            (self.job_alpha.id, self.project_alpha.id),
            (self.job_specific.id, self.project_alpha.id),
            (self.job_beta.id, self.project_beta.id),
        ]

    def _lifecycle(self) -> list[dict[str, Any]]:
        return [
            {
                "job_id": self.job_alpha.id,
                "started_at": datetime(2026, 8, 10, 1, tzinfo=UTC),
                "first_submit_at": datetime(2026, 8, 10, 9, tzinfo=UTC),
                "accepted_at": datetime(2026, 8, 11, 2, tzinfo=UTC),
                "assignee_changed_at": datetime(2026, 8, 9, 23, tzinfo=UTC),
                "rejections": 0,
                "accepter_user_ids": [self.reviewer.id],
                "rejecter_user_ids": [],
            },
            # job_specific and job_beta have never been accepted; the activity half of the
            # union window selects them, and they must not be filtered out.
            {
                "job_id": self.job_specific.id,
                "started_at": datetime(2026, 8, 12, 1, tzinfo=UTC),
                "accepted_at": None,
                "accepter_user_ids": [],
                "rejecter_user_ids": [],
            },
            {
                "job_id": self.job_beta.id,
                "started_at": datetime(2026, 8, 13, 1, tzinfo=UTC),
                "accepted_at": None,
                "accepter_user_ids": [],
                "rejecter_user_ids": [],
            },
        ]

    def _working_time(self) -> list[dict[str, Any]]:
        return [
            {
                "job_id": self.job_alpha.id,
                "user_id": self.annotator.id,
                "day": "2026-08-10",
                "working_ms": 3_600_000,
            },
            {
                "job_id": self.job_alpha.id,
                "user_id": self.reviewer.id,
                "day": "2026-08-11",
                "working_ms": 600_000,
            },
            {
                "job_id": self.job_specific.id,
                "user_id": self.annotator.id,
                "day": "2026-08-12",
                "working_ms": 1_200_000,
            },
            {
                "job_id": self.job_beta.id,
                "user_id": self.outsider.id,
                "day": "2026-08-13",
                "working_ms": 900_000,
            },
        ]

    def _fake(self, **overrides: Any) -> FakeClickHouse:
        defaults: dict[str, Any] = {
            "jobs": self._all_jobs(),
            "lifecycle": self._lifecycle(),
            "working_time": self._working_time(),
            "daily": [
                {
                    "day": "2026-08-10",
                    "events": 12,
                    "last_seen": datetime(2026, 8, 10, 9, tzinfo=UTC),
                }
            ],
            "last_seen": {"last_seen": datetime(2026, 8, 13, 4, tzinfo=UTC), "events": 40},
        }
        defaults.update(overrides)

        return FakeClickHouse(**defaults)

    # ----------------------------------------------------------------- helpers

    def _read(
        self,
        *,
        fake: Any = None,
        params: Mapping[str, Any] | None = None,
    ):
        query_params = dict(PERIOD)
        query_params.update(params or {})

        with mock.patch(RUN_QUERY, fake if fake is not None else self._fake()):
            return self._get_request(JOB_FACTS_PATH, user=self.admin, query_params=query_params)

    def _rows(self, response) -> list[dict[str, Any]]:
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        return response.json()["results"]

    def _row(self, response, job_id: int) -> dict[str, Any]:
        matches = [row for row in self._rows(response) if row["job_id"] == job_id]
        self.assertEqual(len(matches), 1, f"job {job_id} is missing from the response")
        return matches[0]

    # ------------------------------------------------------------------- tests

    def test_project_scope_returns_only_that_projects_jobs(self):
        response = self._read(params={"project_id": self.project_alpha.id})

        self.assertEqual(
            sorted(row["job_id"] for row in self._rows(response)),
            sorted([self.job_alpha.id, self.job_specific.id]),
        )

    def test_omitting_project_id_returns_every_project(self):
        fake = self._fake()
        response = self._read(fake=fake)

        self.assertEqual(
            sorted(row["job_id"] for row in self._rows(response)),
            sorted([self.job_alpha.id, self.job_specific.id, self.job_beta.id]),
        )

        # The screen's first-load path: no project predicate is bound at all.
        scan_sql, scan_parameters = fake.statements[0]
        self.assertIn("SELECT DISTINCT job_id", scan_sql)
        self.assertNotIn("project_id", scan_parameters)

    def test_period_longer_than_the_cap_is_rejected(self):
        response = self._read(
            params={"period_end": (PERIOD_START + MAX_PERIOD + timedelta(days=1)).isoformat()}
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_period_exactly_at_the_cap_is_accepted(self):
        response = self._read(params={"period_end": (PERIOD_START + MAX_PERIOD).isoformat()})

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_inverted_period_is_rejected(self):
        response = self._read(
            params={
                "period_start": PERIOD_END.isoformat(),
                "period_end": PERIOD_START.isoformat(),
            }
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_unaccepted_job_is_listed_with_a_null_acceptance(self):
        row = self._row(self._read(), self.job_specific.id)

        self.assertIsNone(row["accepted_at"])
        self.assertFalse(row["deleted"])

    def test_accepted_job_carries_its_reviewer_and_acceptance(self):
        row = self._row(self._read(), self.job_alpha.id)

        self.assertIsNotNone(row["accepted_at"])
        self.assertEqual(row["reviewer"], {"id": self.reviewer.id, "username": "reviewer"})
        self.assertEqual(row["reviewers"], [{"id": self.reviewer.id, "username": "reviewer"}])
        self.assertEqual(row["reviewer_source"], "acceptance")
        self.assertEqual(row["assignee"], {"id": self.annotator.id, "username": "annotator"})
        self.assertEqual(row["project_name"], "Alpha")
        self.assertEqual(row["task_name"], "alpha-range")
        self.assertEqual(row["stage"], "acceptance")
        self.assertEqual(row["state"], "completed")

    def test_day_role_entries_carry_frames_distributed_within_their_role(self):
        row = self._row(self._read(), self.job_alpha.id)

        self.assertEqual(
            row["days"],
            [
                {
                    "date": "2026-08-10",
                    "user_id": self.annotator.id,
                    "role": "annotation",
                    "seconds": 3600.0,
                    "frames": 5.0,
                },
                {
                    "date": "2026-08-11",
                    "user_id": self.reviewer.id,
                    "role": "review",
                    "seconds": 600.0,
                    "frames": 5.0,
                },
            ],
        )

    def test_specific_frames_job_reports_the_real_frame_set_size(self):
        row = self._row(self._read(), self.job_specific.id)

        # start_frame 0, stop_frame 9 - stop - start + 1 would say 10.
        self.assertEqual(row["frame_count"], 3)

    def test_unassigned_job_is_listed_with_a_null_assignee(self):
        row = self._row(self._read(), self.job_beta.id)

        self.assertIsNone(row["assignee"])
        # Nobody is supposed to be on this job, so every recorded second is unattributed.
        self.assertEqual(row["non_assignee_seconds"], 900.0)

    def test_job_missing_from_postgres_is_flagged_deleted(self):
        fake = self._fake(
            jobs=self._all_jobs() + [(self.deleted_job_id, self.project_beta.id)],
            lifecycle=self._lifecycle()
            + [
                {
                    "job_id": self.deleted_job_id,
                    "accepted_at": datetime(2026, 8, 14, 5, tzinfo=UTC),
                    "accepter_user_ids": [self.reviewer.id],
                    "rejecter_user_ids": [],
                }
            ],
            working_time=self._working_time()
            + [
                {
                    "job_id": self.deleted_job_id,
                    "user_id": self.annotator.id,
                    "day": "2026-08-14",
                    "working_ms": 300_000,
                }
            ],
        )

        row = self._row(self._read(fake=fake), self.deleted_job_id)

        self.assertTrue(row["deleted"])
        self.assertIsNone(row["frame_count"])
        self.assertIsNone(row["task_id"])
        self.assertIsNone(row["project_id"])
        self.assertIsNone(row["assignee"])
        # It still counts towards the approved total, so the acceptance survives.
        self.assertIsNotNone(row["accepted_at"])
        # No frame count means no fabricated frame shares either.
        self.assertEqual([element["frames"] for element in row["days"]], [None])

    def test_response_is_a_single_page(self):
        response = self._read()
        payload = response.json()

        self.assertIsNone(payload["next"])
        self.assertIsNone(payload["previous"])
        self.assertEqual(payload["count"], 3)
        self.assertEqual(len(payload["results"]), payload["count"])

    def test_freshness_travels_on_the_envelope(self):
        payload = self._read().json()

        self.assertEqual(payload["freshness"]["scope"], "send:working_time")
        self.assertEqual(payload["freshness"]["days"][0]["date"], "2026-08-10")
        self.assertEqual(payload["freshness"]["days"][0]["events"], 12)
        self.assertIsNotNone(payload["freshness"]["last_seen"])

    def test_user_directory_covers_every_account_the_rows_mention(self):
        payload = self._read().json()

        self.assertEqual(
            sorted(entry["username"] for entry in payload["users"]),
            ["annotator", "outsider", "reviewer"],
        )

    def test_clickhouse_failure_is_a_503_without_a_stack_trace(self):
        def explode(sql, parameters):
            raise ClickHouseError("connection refused to clickhouse:8123")

        with logging_disabled():
            response = self._read(fake=explode)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

        body = response.content.decode()
        self.assertNotIn("Traceback", body)
        self.assertNotIn("connection refused", body)

    def test_usernames_are_resolved_in_one_query_regardless_of_row_count(self):
        one_job = [(self.job_alpha.id, self.project_alpha.id)]

        # Warm up: the first request through this route pays one-off costs (content types,
        # the session backend) that would otherwise land on whichever measurement runs first.
        self._read(fake=self._fake(jobs=one_job))

        with CaptureQueriesContext(connection) as single_row:
            single = self._read(fake=self._fake(jobs=one_job))

        with CaptureQueriesContext(connection) as every_row:
            every = self._read()

        # Guard against a vacuous comparison: the second request really does carry more rows
        # and more distinct accounts to resolve.
        self.assertEqual(len(self._rows(single)), 1)
        self.assertEqual(len(self._rows(every)), 3)
        self.assertGreater(len(every.json()["users"]), len(single.json()["users"]))

        self.assertEqual(
            len(every_row.captured_queries),
            len(single_row.captured_queries),
            "username resolution must not scale with the number of rows",
        )
