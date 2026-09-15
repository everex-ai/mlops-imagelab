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
from django.test import SimpleTestCase
from django.test.utils import CaptureQueriesContext
from rest_framework import status

from cvat.apps.engine.models import (
    Data,
    Job,
    JobType,
    Label,
    LabeledShape,
    LabeledTrack,
    Project,
    Segment,
    SegmentType,
    ShapeType,
    StageChoice,
    StateChoice,
    Task,
)
from cvat.apps.engine.tests.utils import ApiTestBase, logging_disabled
from cvat.apps.production_stats.queries import UPDATE_JOB_SCOPE, WORKING_TIME_SCOPE
from cvat.apps.production_stats.queries import clickhouse as clickhouse_client
from cvat.apps.production_stats.queries.clickhouse import ClickHouseError
from cvat.apps.production_stats.serializers import MAX_PERIOD
from cvat.apps.production_stats.tests.test_query_builders import (
    PRODUCTION_STATS_LOCATION,
    nginx_read_timeout,
)

JOB_FACTS_PATH = "/api/production_stats/job_facts"
JOB_ROUNDS_PATH = "/api/production_stats/job_rounds"

# The two stage-2 statements, named by a fragment that appears in one of them and nowhere
# else, so a test can pick out what was bound to each.
LIFECYCLE_SCAN = "accepter_user_ids"
WORKING_TIME_SCAN = "AS working_ms"

# An id no fixture creates. The rounds route reads Postgres before anything else, so a
# test that wants a miss has to name an id that really is absent.
MISSING_JOB_ID = 10_000_000


def job_rounds_path(job_id: int) -> str:
    return f"{JOB_ROUNDS_PATH}/{job_id}"


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
    the two views issue six statements between them, and reordering them must not silently
    rewire the fixture. An unrecognised statement is a failure rather than an empty result -
    the latter is what turns a renamed column into a green test with no rows.
    """

    def __init__(
        self,
        *,
        jobs: Sequence[tuple[int, int | None]] = (),
        lifecycle: Sequence[Mapping[str, Any]] = (),
        working_time: Sequence[Mapping[str, Any]] = (),
        timeline: Sequence[Mapping[str, Any]] = (),
        daily: Sequence[Mapping[str, Any]] = (),
        last_seen: Mapping[str, Any] | None = None,
    ):
        self.jobs = list(jobs)
        self.lifecycle = list(lifecycle)
        self.working_time = list(working_time)
        self.timeline = list(timeline)
        self.daily = list(daily)
        self.last_seen = last_seen
        self.statements: list[tuple[str, dict[str, Any]]] = []

    def __call__(self, sql: str, parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
        self.statements.append((sql, dict(parameters)))

        if "scope IN ('update:job', 'send:working_time')" in sql:
            # The rounds scan is already scoped to one job by its `job_id` parameter, and
            # each fixture is built for the job under test.
            return [dict(row) for row in self.timeline]

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

    def parameters_for(self, fragment: str) -> dict[str, Any]:
        """
        What was bound to the first statement containing ``fragment``.

        The fixture rows are returned whatever the period or the history bound says, so a
        statement's parameters are the only place a wrong bound is visible at all.
        """
        for sql, parameters in self.statements:
            if fragment in sql:
                return parameters

        raise AssertionError(f"no statement contained {fragment!r}")


def transition(timestamp: datetime, obj_name: str, obj_val: str, user_id: int) -> dict[str, Any]:
    """An `update:job` row: the changed field in obj_name, its new value in obj_val."""
    return {
        "timestamp": timestamp,
        "scope": UPDATE_JOB_SCOPE,
        "obj_name": obj_name,
        "obj_val": obj_val,
        "user_id": user_id,
        "duration": 0,
    }


def working(timestamp: datetime, user_id: int, duration_ms: int) -> dict[str, Any]:
    """A `send:working_time` row. `duration` is integer milliseconds."""
    return {
        "timestamp": timestamp,
        "scope": WORKING_TIME_SCOPE,
        "obj_name": None,
        "obj_val": None,
        "user_id": user_id,
        "duration": duration_ms,
    }


def create_job(
    *,
    project: Project,
    task_name: str,
    start_frame: int = 0,
    stop_frame: int = 9,
    assignee: User | None = None,
    stage: StageChoice = StageChoice.ANNOTATION,
    state: StateChoice = StateChoice.NEW,
    frames: Sequence[int] | None = None,
) -> Job:
    """A real Postgres job. Both endpoints read their identity half from these rows."""
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


def add_annotations(
    job: Job,
    *,
    shapes: int = 0,
    elements_per_shape: int = 0,
    tracks: int = 0,
    shape_type: str = ShapeType.SKELETON.value,
) -> None:
    """
    Real annotation rows for a job.

    ``elements_per_shape`` models a skeleton: the object itself is one row with
    ``parent=None`` and each keypoint is another row pointing back at it. The count the
    endpoint reports has to be the parents alone - this repo's projects use 24-keypoint
    skeletons, so counting every row would inflate the number 25-fold.
    """
    label, _ = Label.objects.get_or_create(
        project=job.segment.task.project, name="person", type="skeleton"
    )

    for index in range(shapes):
        parent = LabeledShape.objects.create(
            job=job, label=label, frame=index, type=shape_type
        )
        for element in range(elements_per_shape):
            LabeledShape.objects.create(
                job=job,
                label=label,
                frame=index,
                type=ShapeType.POINTS.value,
                parent=parent,
            )

    for index in range(tracks):
        LabeledTrack.objects.create(job=job, label=label, frame=index)


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

        # The rounds route is a detail route that reads Postgres first, so the happy path
        # needs a job that really exists.
        cls.job = create_job(
            project=Project.objects.create(name="Permissions"), task_name="permissions"
        )
        cls.paths = (JOB_FACTS_PATH, job_rounds_path(cls.job.id))

    def _get(self, path: str, user: User | None):
        query_params = PERIOD if path == JOB_FACTS_PATH else None
        with mock.patch(RUN_QUERY, FakeClickHouse()):
            return self._get_request(path, user=user, query_params=query_params)

    def test_admin_can_read_production_stats(self):
        for path in self.paths:
            with self.subTest(path=path):
                response = self._get(path, user=self.admin)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_job_facts_returns_a_list_payload(self):
        response = self._get(JOB_FACTS_PATH, user=self.admin)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.json())

    def test_job_rounds_returns_a_rounds_payload(self):
        response = self._get(job_rounds_path(self.job.id), user=self.admin)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("rounds", response.json())

    def test_regular_user_cannot_read_production_stats(self):
        for path in self.paths:
            with self.subTest(path=path):
                response = self._get(path, user=self.user)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_worker_cannot_read_production_stats(self):
        for path in self.paths:
            with self.subTest(path=path):
                response = self._get(path, user=self.worker)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_cannot_read_production_stats(self):
        for path in self.paths:
            with self.subTest(path=path):
                response = self._get(path, user=None)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_a_non_admin_cannot_probe_which_job_ids_exist(self):
        # The permission check runs before the 404 on purpose: were it the other way round,
        # any logged-in user could tell an existing job from a missing one by the status
        # code, even though the policy denies them the contents either way.
        for user in (self.user, self.worker):
            with self.subTest(user=user.username):
                self.assertEqual(
                    self._get(job_rounds_path(self.job.id), user=user).status_code,
                    self._get(job_rounds_path(MISSING_JOB_ID), user=user).status_code,
                )
                self.assertEqual(
                    self._get(job_rounds_path(MISSING_JOB_ID), user=user).status_code,
                    status.HTTP_403_FORBIDDEN,
                )


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
        cls.job_alpha = create_job(
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
        cls.job_specific = create_job(
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
        cls.job_beta = create_job(
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

    def test_object_count_reports_top_level_shapes(self):
        add_annotations(self.job_alpha, shapes=3)

        row = self._row(self._read(), self.job_alpha.id)

        self.assertEqual(row["object_count"], 3)

    def test_skeleton_elements_are_not_counted_as_objects(self):
        # One skeleton with 24 keypoints is one object, not 25.
        add_annotations(self.job_alpha, shapes=2, elements_per_shape=24)

        row = self._row(self._read(), self.job_alpha.id)

        self.assertEqual(row["object_count"], 2)

    def test_tracks_count_as_objects_too(self):
        # Interpolated annotations live in their own table; leaving them out would report
        # zero for a project that uses them and look like "nothing was labelled".
        add_annotations(self.job_alpha, shapes=1, tracks=2)

        row = self._row(self._read(), self.job_alpha.id)

        self.assertEqual(row["object_count"], 3)

    def test_job_without_annotations_reports_zero_objects(self):
        # Zero is a real observation here - the job exists and holds nothing.
        row = self._row(self._read(), self.job_alpha.id)

        self.assertEqual(row["object_count"], 0)

    def test_object_count_is_scoped_to_its_own_job(self):
        add_annotations(self.job_alpha, shapes=3)
        add_annotations(self.job_specific, shapes=1)

        payload = self._read()

        self.assertEqual(self._row(payload, self.job_alpha.id)["object_count"], 3)
        self.assertEqual(self._row(payload, self.job_specific.id)["object_count"], 1)

    def test_object_count_stays_two_queries_regardless_of_job_count(self):
        # The sibling username guarantee is pinned the same way (see
        # test_usernames_are_resolved_in_one_query_regardless_of_row_count): the
        # aggregate must not become one query per job as the id set grows.
        add_annotations(self.job_alpha, shapes=2)
        add_annotations(self.job_specific, shapes=2)
        add_annotations(self.job_beta, shapes=2)

        with CaptureQueriesContext(connection) as captured:
            self._read()

        counting = [
            query
            for query in captured.captured_queries
            if 'engine_labeledshape' in query['sql']
            or 'engine_labeledtrack' in query['sql']
        ]
        self.assertEqual(len(counting), 2, counting)

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
        # Same rule as frame_count: the Postgres row is gone, so there is nothing to count.
        # Zero would read as "this job held no objects", which is a different claim.
        self.assertIsNone(row["object_count"])
        self.assertIsNone(row["task_id"])
        self.assertIsNone(row["project_id"])
        self.assertIsNone(row["assignee"])
        # It still counts towards the approved total, so the acceptance survives.
        self.assertIsNotNone(row["accepted_at"])
        # No frame count means no fabricated frame shares either.
        self.assertEqual([element["frames"] for element in row["days"]], [None])

    def test_stage_two_is_never_bounded_later_than_the_window_stage_one_used(self):
        # Every surviving job here was created after `period_start` - the fixtures are made
        # now and the window is in the past - so a bound taken from those rows alone starts
        # *after* the window stage 1 qualified jobs on. The job whose Postgres row is gone
        # contributes no `created_date` of its own, and its acceptance and its working time
        # sit early in the period: with the tighter bound stage 2 would scan straight past
        # both, and the row would come back stripped of the evidence it was selected for.
        self.assertTrue(
            all(job.created_date > PERIOD_START for job in Job.objects.all()),
            "the fixture no longer reproduces the case under test",
        )

        fake = self._fake(
            jobs=self._all_jobs() + [(self.deleted_job_id, self.project_beta.id)],
            lifecycle=self._lifecycle()
            + [
                {
                    "job_id": self.deleted_job_id,
                    "accepted_at": datetime(2026, 8, 4, 5, tzinfo=UTC),
                    "accepter_user_ids": [self.reviewer.id],
                    "rejecter_user_ids": [],
                }
            ],
            working_time=self._working_time()
            + [
                {
                    "job_id": self.deleted_job_id,
                    "user_id": self.annotator.id,
                    "day": "2026-08-04",
                    "working_ms": 300_000,
                }
            ],
        )

        self._read(fake=fake)

        for scan in (LIFECYCLE_SCAN, WORKING_TIME_SCAN):
            with self.subTest(scan=scan):
                self.assertEqual(
                    fake.parameters_for(scan)["history_start"],
                    PERIOD_START.replace(tzinfo=None),
                )

    def test_stage_twos_bound_still_widens_to_a_job_older_than_the_window(self):
        # The bound only ever moves earlier: a job created before the window still pulls it
        # back to its own creation, because its history starts there.
        older = PERIOD_START - timedelta(days=30)
        # `created_date` is auto_now_add, so the fixture's real creation time can only be
        # rewritten with an UPDATE.
        Job.objects.filter(id=self.job_alpha.id).update(created_date=older)

        fake = self._fake()
        self._read(fake=fake)

        for scan in (LIFECYCLE_SCAN, WORKING_TIME_SCAN):
            with self.subTest(scan=scan):
                self.assertEqual(
                    fake.parameters_for(scan)["history_start"], older.replace(tzinfo=None)
                )

    def test_a_job_accepted_by_its_own_assignee_keeps_its_annotation_time(self):
        # The assignee is a Postgres fact, so this is also the test that the view threads
        # it into the query layer: without it the accepter is their own reviewer, every
        # second they worked is tagged `review`, and the whole frame count follows.
        lifecycle = [dict(row) for row in self._lifecycle()]
        lifecycle[0]["accepter_user_ids"] = [self.annotator.id]
        working_time = [
            row
            for row in self._working_time()
            if not (row["job_id"] == self.job_alpha.id and row["user_id"] == self.reviewer.id)
        ]

        row = self._row(
            self._read(fake=self._fake(lifecycle=lifecycle, working_time=working_time)),
            self.job_alpha.id,
        )

        self.assertEqual([element["role"] for element in row["days"]], ["annotation"])
        # All five frames on the annotation axis, and no review element to put them on.
        self.assertEqual([element["frames"] for element in row["days"]], [5.0])
        self.assertEqual(
            row["estimated_worker"], {"id": self.annotator.id, "username": "annotator"}
        )
        # Identity is unchanged: they are still displayed as whoever accepted it.
        self.assertEqual(row["reviewer"], {"id": self.annotator.id, "username": "annotator"})

    def test_a_second_reviewer_who_only_rejected_is_reported_as_review_time(self):
        lifecycle = [dict(row) for row in self._lifecycle()]
        lifecycle[0]["rejecter_user_ids"] = [self.outsider.id]
        working_time = self._working_time() + [
            {
                "job_id": self.job_alpha.id,
                "user_id": self.outsider.id,
                "day": "2026-08-11",
                "working_ms": 900_000,
            }
        ]

        row = self._row(
            self._read(fake=self._fake(lifecycle=lifecycle, working_time=working_time)),
            self.job_alpha.id,
        )
        roles = {element["user_id"]: element["role"] for element in row["days"]}

        self.assertEqual(roles[self.outsider.id], "review")
        # The same person the non-assignee total was already excluding - the two answers
        # now come from one set instead of disagreeing silently.
        self.assertEqual(row["non_assignee_seconds"], 0.0)

    def test_the_list_handler_issues_the_statement_count_the_timeout_budget_assumes(self):
        # The per-statement ClickHouse deadline is the request budget divided by this
        # number (see queries/clickhouse.py), so a sixth statement would overrun nginx.
        fake = self._fake()

        self._read(fake=fake)

        self.assertEqual(len(fake.statements), clickhouse_client.MAX_SEQUENTIAL_QUERIES)

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


class ClickHouseDeadlineTest(SimpleTestCase):
    """
    The innermost component must not have the longest deadline.

    clickhouse_connect defaults to 10s to connect and 300s to read. nginx allows 120s
    upstream for these two routes and Beacon gives up on ImageLab after 90, so on the
    library defaults both proxies hang up while the query runs on, and the failure the
    operator sees never names ClickHouse.
    """

    def _client_kwargs(self) -> dict[str, Any]:
        with mock.patch("clickhouse_connect.get_client") as get_client:
            with clickhouse_client.get_client():
                pass

        return get_client.call_args.kwargs

    def test_the_client_is_opened_with_explicit_timeouts(self):
        kwargs = self._client_kwargs()

        self.assertEqual(kwargs["connect_timeout"], clickhouse_client.CONNECT_TIMEOUT)
        self.assertEqual(kwargs["send_receive_timeout"], clickhouse_client.SEND_RECEIVE_TIMEOUT)

    def test_the_server_is_told_to_abandon_the_query_too(self):
        # A client-side timeout only drops the socket. Without max_execution_time the query
        # keeps running on a store that is already struggling, so every slow request leaves
        # orphaned work behind it.
        settings_sent = self._client_kwargs()["settings"]

        self.assertEqual(settings_sent["max_execution_time"], clickhouse_client.MAX_EXECUTION_TIME)
        self.assertLessEqual(
            clickhouse_client.MAX_EXECUTION_TIME, clickhouse_client.SEND_RECEIVE_TIMEOUT
        )

    def test_the_worst_case_request_stays_inside_the_proxy_read_timeout(self):
        worst_case = clickhouse_client.MAX_SEQUENTIAL_QUERIES * (
            clickhouse_client.CONNECT_TIMEOUT + clickhouse_client.SEND_RECEIVE_TIMEOUT
        )

        self.assertLess(worst_case, clickhouse_client.PROXY_READ_TIMEOUT)
        # And the budget is pinned to what nginx actually grants these routes, so raising
        # either number on its own cannot silently cross the proxy.
        self.assertEqual(
            nginx_read_timeout(PRODUCTION_STATS_LOCATION), clickhouse_client.PROXY_READ_TIMEOUT
        )


class JobRoundsTest(ApiTestBase):
    """
    The round decomposition of a single job.

    ClickHouse is faked (see FakeClickHouse); Postgres is real, because the endpoint takes
    three things from it - the identity half of the response, the object the permission
    check is made against, and the `created_date` that bounds the timeline scan.
    """

    T1 = datetime(2026, 8, 18, 1, tzinfo=UTC)  # annotation opens
    T2 = datetime(2026, 8, 18, 5, tzinfo=UTC)  # submitted for review
    T3 = datetime(2026, 8, 18, 6, tzinfo=UTC)  # rejected
    T4 = datetime(2026, 8, 18, 8, tzinfo=UTC)  # resubmitted
    T5 = datetime(2026, 8, 18, 9, tzinfo=UTC)  # accepted
    T6 = datetime(2026, 8, 19, 1, tzinfo=UTC)  # reverted to annotation

    @classmethod
    def setUpTestData(cls):
        create_db_users(cls)

        cls.annotator = User.objects.create_user(username="annotator", password="annotator")
        cls.reviewer = User.objects.create_user(username="reviewer", password="reviewer")
        cls.second_reviewer = User.objects.create_user(username="second", password="second")

        cls.project = Project.objects.create(name="Rounds")
        cls.job = create_job(
            project=cls.project,
            task_name="rounds",
            assignee=cls.annotator,
            stage=StageChoice.ACCEPTANCE,
            state=StateChoice.COMPLETED,
        )

    # ---------------------------------------------------------------- fixtures

    def _one_rejection(self) -> list[dict[str, Any]]:
        """annotation -> review -> rework -> re-review, then acceptance."""
        return [
            transition(self.T1, "state", "in progress", self.annotator.id),
            working(self.T1 + timedelta(minutes=30), self.annotator.id, 600_000),
            transition(self.T2, "state", "completed", self.annotator.id),
            working(self.T2 + timedelta(minutes=10), self.reviewer.id, 300_000),
            transition(self.T3, "state", "rejected", self.reviewer.id),
            working(self.T3 + timedelta(minutes=10), self.annotator.id, 120_000),
            transition(self.T4, "state", "completed", self.annotator.id),
            working(self.T4 + timedelta(minutes=10), self.reviewer.id, 60_000),
            transition(self.T5, "stage", "acceptance", self.reviewer.id),
        ]

    def _two_rejections(self) -> list[dict[str, Any]]:
        """A second rejection, so the fold has to open a third round."""
        second_rejection = self.T4 + timedelta(minutes=30)
        second_resubmit = self.T4 + timedelta(minutes=45)

        return self._one_rejection()[:-1] + [
            transition(second_rejection, "state", "rejected", self.reviewer.id),
            working(second_rejection + timedelta(minutes=5), self.annotator.id, 30_000),
            transition(second_resubmit, "state", "completed", self.annotator.id),
            transition(self.T5, "stage", "acceptance", self.reviewer.id),
        ]

    # ----------------------------------------------------------------- helpers

    def _get(self, fake: Any, *, job_id: int | None = None, user: User | None = None):
        path = job_rounds_path(self.job.id if job_id is None else job_id)

        with mock.patch(RUN_QUERY, fake):
            return self._get_request(path, user=user or self.admin)

    def _payload(self, timeline: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
        response = self._get(FakeClickHouse(timeline=timeline))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        return response.json()

    @staticmethod
    def _iso(value: datetime) -> str:
        return value.isoformat().replace("+00:00", "Z")

    # ------------------------------------------------------------------- tests

    def test_a_rejected_job_comes_back_as_annotation_review_rework_rereview(self):
        payload = self._payload(self._one_rejection())

        self.assertEqual(
            [(entry["round"], entry["phase"]) for entry in payload["rounds"]],
            [(1, "annotation"), (1, "review"), (2, "annotation"), (2, "review")],
        )
        self.assertEqual(
            [(entry["started_at"], entry["ended_at"]) for entry in payload["rounds"]],
            [
                (self._iso(self.T1), self._iso(self.T2)),
                (self._iso(self.T2), self._iso(self.T3)),
                (self._iso(self.T3), self._iso(self.T4)),
                (self._iso(self.T4), self._iso(self.T5)),
            ],
        )
        self.assertEqual(
            [(entry["worker_seconds"], entry["reviewer_seconds"]) for entry in payload["rounds"]],
            [(600.0, 0.0), (0.0, 300.0), (120.0, 0.0), (0.0, 60.0)],
        )

    def test_a_second_rejection_opens_a_third_round(self):
        payload = self._payload(self._two_rejections())

        self.assertEqual(
            [(entry["round"], entry["phase"]) for entry in payload["rounds"]],
            [
                (1, "annotation"),
                (1, "review"),
                (2, "annotation"),
                (2, "review"),
                (3, "annotation"),
                (3, "review"),
            ],
        )

    def test_a_job_that_never_started_is_a_200_with_no_rounds(self):
        # No `state -> in progress` anywhere: somebody opened the job and booked time, but
        # the state machine never moved. The screen shows this as "no work recorded", which
        # it can only do if it is distinguishable from a failed lookup.
        payload = self._payload([working(self.T1, self.annotator.id, 60_000)])

        self.assertEqual(payload["rounds"], [])
        self.assertIsNone(payload["trailing"])
        self.assertIsNone(payload["accepted_at"])
        self.assertEqual(payload["totals"], {"worker_seconds": 60.0, "reviewer_seconds": 0.0})

    def test_an_unknown_job_id_is_a_404(self):
        fake = FakeClickHouse(timeline=self._one_rejection())

        response = self._get(fake, job_id=MISSING_JOB_ID)

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        # Postgres decides the miss; the analytics store is never consulted.
        self.assertEqual(fake.statements, [])

    def test_activity_after_the_first_acceptance_is_reported_as_trailing(self):
        # Three jobs in the production dump were reverted to `annotation` after acceptance
        # and worked on again. That time belongs to no round, and hiding it would leave the
        # round times mysteriously short of the job total.
        payload = self._payload(
            self._one_rejection()
            + [
                transition(self.T6, "stage", "annotation", self.annotator.id),
                working(self.T6 + timedelta(minutes=5), self.annotator.id, 90_000),
            ]
        )

        self.assertEqual(len(payload["rounds"]), 4)
        self.assertEqual(payload["rounds"][-1]["ended_at"], self._iso(self.T5))
        self.assertEqual(payload["accepted_at"], self._iso(self.T5))

        self.assertEqual(payload["trailing"]["started_at"], self._iso(self.T5))
        self.assertIsNone(payload["trailing"]["ended_at"])
        self.assertEqual(payload["trailing"]["worker_seconds"], 90.0)

        in_rounds = sum(
            entry["worker_seconds"] + entry["reviewer_seconds"] for entry in payload["rounds"]
        )
        self.assertEqual(in_rounds, 1080.0)
        self.assertEqual(
            payload["totals"]["worker_seconds"] + payload["totals"]["reviewer_seconds"],
            in_rounds + payload["trailing"]["worker_seconds"],
        )

    def test_the_final_round_of_an_in_flight_job_has_no_end(self):
        # Never "now": the drilldown has to be reproducible, and two page loads of the same
        # job must not disagree.
        payload = self._payload(
            [
                transition(self.T1, "state", "in progress", self.annotator.id),
                working(self.T1 + timedelta(minutes=30), self.annotator.id, 600_000),
                transition(self.T2, "state", "completed", self.annotator.id),
            ]
        )

        self.assertIsNone(payload["rounds"][-1]["ended_at"])
        self.assertIsNone(payload["accepted_at"])
        self.assertIsNone(payload["trailing"])

    def test_on_a_never_accepted_job_the_rejecter_is_the_reviewer(self):
        payload = self._payload(
            [
                transition(self.T1, "state", "in progress", self.annotator.id),
                transition(self.T2, "state", "completed", self.annotator.id),
                working(self.T2 + timedelta(minutes=10), self.reviewer.id, 300_000),
                transition(self.T3, "state", "rejected", self.reviewer.id),
            ]
        )

        self.assertEqual(payload["reviewer_source"], "rejection")
        self.assertEqual(payload["reviewer"], {"id": self.reviewer.id, "username": "reviewer"})
        self.assertEqual(payload["rounds"][1]["reviewer_seconds"], 300.0)

    def test_on_an_accepted_job_the_assignees_own_rejection_is_ignored(self):
        # Treating any rejecter as a reviewer moved ~567 hours of annotation into the review
        # axis of the production dump, because annotators flip their own job to `rejected`.
        payload = self._payload(
            [
                transition(self.T1, "state", "in progress", self.annotator.id),
                working(self.T1 + timedelta(minutes=30), self.annotator.id, 600_000),
                transition(self.T2, "state", "rejected", self.annotator.id),
                transition(self.T3, "state", "completed", self.annotator.id),
                transition(self.T5, "stage", "acceptance", self.reviewer.id),
            ]
        )

        self.assertEqual(payload["reviewer_source"], "acceptance")
        self.assertEqual(payload["reviewers"], [{"id": self.reviewer.id, "username": "reviewer"}])
        self.assertEqual(payload["totals"], {"worker_seconds": 600.0, "reviewer_seconds": 0.0})

    def test_a_job_accepted_by_its_own_assignee_keeps_its_annotation_time(self):
        # The assignee is a Postgres fact ClickHouse does not have, so this is also the test
        # that the view threads it into the query layer: without it the accepter is their
        # own reviewer, and every second of a job nobody else ever touched is review time.
        payload = self._payload(
            [
                transition(self.T1, "state", "in progress", self.annotator.id),
                working(self.T1 + timedelta(minutes=30), self.annotator.id, 600_000),
                transition(self.T2, "state", "completed", self.annotator.id),
                working(self.T2 + timedelta(minutes=10), self.annotator.id, 300_000),
                transition(self.T5, "stage", "acceptance", self.annotator.id),
            ]
        )

        # Identity is unchanged: they are still displayed as whoever accepted it.
        self.assertEqual(payload["reviewer_source"], "acceptance")
        self.assertEqual(payload["reviewer"], {"id": self.annotator.id, "username": "annotator"})

        self.assertEqual(
            [(entry["worker_seconds"], entry["reviewer_seconds"]) for entry in payload["rounds"]],
            [(600.0, 0.0), (300.0, 0.0)],
        )
        self.assertEqual(payload["totals"], {"worker_seconds": 900.0, "reviewer_seconds": 0.0})

    def test_a_second_reviewer_who_only_rejected_is_reported_as_review_time(self):
        # `reviewers` is the accepters, so the person who sent this job back never appears
        # there. Cutting the split on that set booked their fifteen minutes to the worker
        # side - the annotator's own axis - of the round they spent rejecting it.
        payload = self._payload(
            [
                transition(self.T1, "state", "in progress", self.annotator.id),
                working(self.T1 + timedelta(minutes=30), self.annotator.id, 600_000),
                transition(self.T2, "state", "completed", self.annotator.id),
                working(self.T2 + timedelta(minutes=10), self.second_reviewer.id, 900_000),
                transition(self.T3, "state", "rejected", self.second_reviewer.id),
                working(self.T3 + timedelta(minutes=10), self.annotator.id, 120_000),
                transition(self.T4, "state", "completed", self.annotator.id),
                working(self.T4 + timedelta(minutes=10), self.reviewer.id, 60_000),
                transition(self.T5, "stage", "acceptance", self.reviewer.id),
            ]
        )

        self.assertEqual(payload["reviewers"], [{"id": self.reviewer.id, "username": "reviewer"}])
        self.assertEqual(
            [(entry["worker_seconds"], entry["reviewer_seconds"]) for entry in payload["rounds"]],
            [(600.0, 0.0), (0.0, 900.0), (120.0, 0.0), (0.0, 60.0)],
        )
        self.assertEqual(payload["totals"], {"worker_seconds": 720.0, "reviewer_seconds": 960.0})

    def test_the_response_carries_the_jobs_postgres_identity(self):
        payload = self._payload(self._one_rejection())

        self.assertEqual(payload["job_id"], self.job.id)
        self.assertEqual(payload["task_id"], self.job.segment.task_id)
        self.assertEqual(payload["task_name"], "rounds")
        self.assertEqual(payload["project_id"], self.project.id)
        self.assertEqual(payload["project_name"], "Rounds")
        self.assertEqual(payload["assignee"], {"id": self.annotator.id, "username": "annotator"})
        self.assertEqual(payload["stage"], "acceptance")
        self.assertEqual(payload["state"], "completed")

    def test_the_timeline_is_read_once_and_bounded_by_the_jobs_creation_date(self):
        # `cvat.events` is ordered by `timestamp` alone, so without this lower bound the
        # drilldown would scan the whole table every time somebody opens a job.
        fake = FakeClickHouse(timeline=self._one_rejection())

        self._get(fake)

        self.assertEqual(len(fake.statements), 1)
        sql, parameters = fake.statements[0]
        self.assertIn("timestamp >=", sql)
        self.assertEqual(
            parameters,
            {
                "job_id": self.job.id,
                "history_start": (
                    Job.objects.get(id=self.job.id)
                    .created_date.astimezone(UTC)
                    .replace(tzinfo=None)
                ),
            },
        )

    def test_clickhouse_failure_is_a_503_without_a_stack_trace(self):
        def explode(sql, parameters):
            raise ClickHouseError("connection refused to clickhouse:8123")

        with logging_disabled():
            response = self._get(explode)

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

        body = response.content.decode()
        self.assertNotIn("Traceback", body)
        self.assertNotIn("connection refused", body)

    def test_usernames_are_resolved_in_one_query_regardless_of_round_count(self):
        # A second accepter: `reviewers` carries everyone who ever accepted, so this job
        # names two accounts the assignee lookup does not already cover.
        two_reviewers = self._two_rejections() + [
            transition(self.T6, "stage", "acceptance", self.second_reviewer.id)
        ]

        # Warm up: the first request through this route pays one-off costs (content types,
        # the session backend) that would otherwise land on whichever measurement runs first.
        self._payload(self._one_rejection())

        with CaptureQueriesContext(connection) as small:
            short = self._payload(self._one_rejection())

        with CaptureQueriesContext(connection) as large:
            long = self._payload(two_reviewers)

        # Guard against a vacuous comparison: the second job really does carry more rounds
        # and more distinct accounts to resolve.
        self.assertEqual(len(short["rounds"]), 4)
        self.assertEqual(len(long["rounds"]), 6)
        self.assertEqual(len(short["reviewers"]), 1)
        self.assertEqual(len(long["reviewers"]), 2)

        self.assertEqual(
            len(large.captured_queries),
            len(small.captured_queries),
            "username resolution must not scale with the number of rounds",
        )
