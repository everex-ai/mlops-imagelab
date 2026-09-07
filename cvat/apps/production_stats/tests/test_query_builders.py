# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""
Unit tests for the production stats query layer.

There is no ClickHouse fixture infrastructure in this repository, so these tests target
the two halves the query layer is deliberately split into: the SQL builders (pure string
+ parameter construction) and the row mappers (pure row -> dict folding). The executor is
injected rather than reached for, so nothing here needs a database, OPA, Django settings
or the network.
"""

import re
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock
from zoneinfo import ZoneInfo

from cvat.apps.production_stats.queries import (
    REPORT_TIMEZONE,
    REVIEWER_FROM_ACCEPTANCE,
    REVIEWER_FROM_REJECTION,
    ROLE_ANNOTATION,
    ROLE_REVIEW,
    UPDATE_JOB_SCOPE,
    WORKING_TIME_SCOPE,
    freshness,
    job_facts,
    job_rounds,
    resolve_review_role_ids,
    resolve_reviewers,
    to_utc_naive,
)

UTC = timezone.utc

PERIOD_START = datetime(2026, 8, 3, 0, 0, tzinfo=UTC)
PERIOD_END = datetime(2026, 8, 31, 0, 0, tzinfo=UTC)
HISTORY_START = datetime(2026, 7, 1, 0, 0, tzinfo=UTC)

PROJECT_ID = 147
JOB_ID = 4242
OTHER_JOB_ID = 4243

ASSIGNEE = 11
REVIEWER = 77
SECOND_REVIEWER = 78
OUTSIDER = 99

PLACEHOLDER_RE = re.compile(r"\{(\w+):([^{}]+)\}")

# The nginx config the two endpoints are served through. Not a query builder, but it is
# part of the same deadline contract: the ClickHouse client timeouts are derived from what
# this file grants these routes (see queries/clickhouse.py).
NGINX_CONF = Path(__file__).resolve().parents[3] / "nginx.conf"
PRODUCTION_STATS_LOCATION = "/api/production_stats/"

# `location <prefix> { ... }`. No location block in this file nests another one.
LOCATION_RE = re.compile(r"location\s+(\S+)\s*\{([^{}]*)\}")
READ_TIMEOUT_RE = re.compile(r"proxy_read_timeout\s+(\d+)s;")


def nginx_locations():
    """Every ``location`` block of cvat/nginx.conf, keyed by its prefix."""
    return dict(LOCATION_RE.findall(NGINX_CONF.read_text()))


def nginx_read_timeout(prefix):
    """One block's ``proxy_read_timeout`` in seconds, or None when it sets none."""
    match = READ_TIMEOUT_RE.search(nginx_locations()[prefix])

    return int(match.group(1)) if match else None


def _all_queries():
    """Every query this package can issue, with representative values bound."""
    return {
        "job_id_scan": job_facts.build_job_id_scan(
            period_start=PERIOD_START, period_end=PERIOD_END
        ),
        "job_id_scan_scoped": job_facts.build_job_id_scan(
            period_start=PERIOD_START, period_end=PERIOD_END, project_id=PROJECT_ID
        ),
        "job_lifecycle": job_facts.build_job_lifecycle_scan(
            job_ids=[JOB_ID, OTHER_JOB_ID], history_start=HISTORY_START
        ),
        "working_time": job_facts.build_working_time_scan(
            job_ids=[JOB_ID, OTHER_JOB_ID], history_start=HISTORY_START
        ),
        "job_timeline": job_rounds.build_job_timeline_scan(
            job_id=JOB_ID, history_start=HISTORY_START
        ),
        "daily_presence": freshness.build_daily_presence_scan(
            period_start=PERIOD_START, period_end=PERIOD_END, project_id=PROJECT_ID
        ),
        "last_seen": freshness.build_last_seen_scan(since=HISTORY_START),
    }


def _lifecycle_row(job_id, **overrides):
    row = {
        "job_id": job_id,
        "started_at": None,
        "first_submit_at": None,
        "accepted_at": None,
        "assignee_changed_at": None,
        "rejections": 0,
        "accepter_user_ids": [],
        "rejecter_user_ids": [],
    }
    row.update(overrides)
    return row


def _working_time_row(job_id, user_id, day, working_ms):
    return {"job_id": job_id, "user_id": user_id, "day": day, "working_ms": working_ms}


def _transition(timestamp, obj_name, obj_val, user_id):
    return {
        "timestamp": timestamp,
        "scope": UPDATE_JOB_SCOPE,
        "obj_name": obj_name,
        "obj_val": obj_val,
        "user_id": user_id,
        "duration": 0,
    }


def _working(timestamp, user_id, duration_ms):
    return {
        "timestamp": timestamp,
        "scope": WORKING_TIME_SCOPE,
        "obj_name": None,
        "obj_val": None,
        "user_id": user_id,
        "duration": duration_ms,
    }


class _StubExecutor:
    """
    Stands in for cvat.apps.production_stats.queries.clickhouse.run_query.

    It dispatches on a distinctive fragment of each query so a test can hand back canned
    rows per query, and records every call so a test can assert what was actually bound.
    """

    def __init__(self, *, job_ids=(), lifecycle=(), working_time=(), timeline=()):
        self.job_ids = list(job_ids)
        self.lifecycle = list(lifecycle)
        self.working_time = list(working_time)
        self.timeline = list(timeline)
        self.calls = []

    def __call__(self, sql, parameters):
        self.calls.append((sql, dict(parameters)))

        if "SELECT DISTINCT job_id" in sql:
            return [{"job_id": job_id} for job_id in self.job_ids]
        if "accepter_user_ids" in sql:
            return list(self.lifecycle)
        if "AS working_ms" in sql:
            return list(self.working_time)
        if "{job_id:UInt64}" in sql:
            return list(self.timeline)

        raise AssertionError(f"unexpected query: {sql}")

    def parameters_for(self, fragment):
        for sql, parameters in self.calls:
            if fragment in sql:
                return parameters

        raise AssertionError(f"no query contained {fragment!r}")


class SqlBuilderContractTest(unittest.TestCase):
    def test_every_placeholder_is_bound_as_a_server_side_parameter(self):
        for name, query in _all_queries().items():
            with self.subTest(query=name):
                placeholders = {match[0] for match in PLACEHOLDER_RE.findall(query.sql)}

                self.assertTrue(placeholders, "query binds nothing server-side")
                self.assertEqual(placeholders, set(query.parameters))

    def test_no_caller_supplied_value_is_interpolated_into_the_sql(self):
        interpolated = (
            str(PROJECT_ID),
            str(JOB_ID),
            str(OTHER_JOB_ID),
            "2026-08-03",
            "2026-08-31",
            "2026-07-01",
        )

        for name, query in _all_queries().items():
            for value in interpolated:
                with self.subTest(query=name, value=value):
                    self.assertNotIn(value, query.sql)

    def test_every_scan_carries_a_time_predicate(self):
        # cvat.events is ordered by timestamp alone, so a scan without a lower bound reads
        # the whole table. The rounds query is no exception.
        for name, query in _all_queries().items():
            with self.subTest(query=name):
                self.assertIn("timestamp >= {", query.sql)

    def test_aware_datetimes_are_bound_as_utc(self):
        # clickhouse_connect renders bind values with strftime() and never converts them.
        kst_start = PERIOD_START.astimezone(ZoneInfo(REPORT_TIMEZONE))
        query = job_facts.build_job_id_scan(period_start=kst_start, period_end=PERIOD_END)

        self.assertEqual(query.parameters["period_start"], PERIOD_START.replace(tzinfo=None))
        self.assertIsNone(query.parameters["period_start"].tzinfo)

    def test_naive_datetimes_are_left_alone(self):
        naive = datetime(2026, 8, 3, 0, 0)

        self.assertEqual(to_utc_naive(naive), naive)


class StageOneTest(unittest.TestCase):
    def test_period_filter_is_the_union_of_approval_and_activity(self):
        sql = job_facts.build_job_id_scan(period_start=PERIOD_START, period_end=PERIOD_END).sql

        # Both branches sit inside one OR that the period brackets, so a job whose only
        # acceptance falls in the window qualifies and so does one whose only working time
        # does. Filtering on acceptance alone would drop a job worked in one week and
        # accepted in another.
        self.assertIn("scope = 'send:working_time'", sql)
        self.assertIn(
            "(scope = 'update:job' AND obj_name = 'stage' AND obj_val = 'acceptance')", sql
        )
        self.assertIn(" OR ", sql)
        self.assertIn("timestamp >= {period_start:DateTime64}", sql)
        self.assertIn("timestamp < {period_end:DateTime64}", sql)

    def test_approval_only_and_activity_only_jobs_both_come_back(self):
        approved_only = 5001
        active_only = 5002
        executor = _StubExecutor(job_ids=[approved_only, active_only])

        job_ids = job_facts.fetch_job_ids(
            period_start=PERIOD_START, period_end=PERIOD_END, execute=executor
        )

        self.assertEqual(job_ids, [approved_only, active_only])

    def test_project_id_is_optional(self):
        without = job_facts.build_job_id_scan(period_start=PERIOD_START, period_end=PERIOD_END)
        with_project = job_facts.build_job_id_scan(
            period_start=PERIOD_START, period_end=PERIOD_END, project_id=PROJECT_ID
        )

        self.assertNotIn("project_id", without.sql)
        self.assertNotIn("project_id", without.parameters)
        self.assertIn("project_id = {project_id:UInt64}", with_project.sql)
        self.assertEqual(with_project.parameters["project_id"], PROJECT_ID)

    def test_period_is_passed_through_to_the_scan(self):
        executor = _StubExecutor(job_ids=[JOB_ID])

        job_facts.fetch_job_ids(
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            project_id=PROJECT_ID,
            execute=executor,
        )

        parameters = executor.parameters_for("SELECT DISTINCT job_id")
        self.assertEqual(parameters["period_start"], PERIOD_START.replace(tzinfo=None))
        self.assertEqual(parameters["period_end"], PERIOD_END.replace(tzinfo=None))
        self.assertEqual(parameters["project_id"], PROJECT_ID)


class StageTwoIndependenceTest(unittest.TestCase):
    def _canned_executor(self):
        return _StubExecutor(
            lifecycle=[
                _lifecycle_row(
                    JOB_ID,
                    accepted_at=datetime(2026, 8, 20, 1, 0, tzinfo=UTC),
                    accepter_user_ids=[REVIEWER],
                )
            ],
            working_time=[
                _working_time_row(JOB_ID, ASSIGNEE, "2026-08-18", 3_600_000),
                _working_time_row(JOB_ID, REVIEWER, "2026-08-20", 600_000),
                _working_time_row(JOB_ID, OUTSIDER, "2026-08-20", 120_000),
            ],
        )

    def test_stage_two_queries_bind_no_period(self):
        for query in (
            job_facts.build_job_lifecycle_scan(job_ids=[JOB_ID], history_start=HISTORY_START),
            job_facts.build_working_time_scan(job_ids=[JOB_ID], history_start=HISTORY_START),
            job_rounds.build_job_timeline_scan(job_id=JOB_ID, history_start=HISTORY_START),
        ):
            with self.subTest(sql=query.sql[:40]):
                self.assertNotIn("period_start", query.sql)
                self.assertNotIn("period_end", query.sql)
                self.assertNotIn("period_start", query.parameters)
                self.assertNotIn("period_end", query.parameters)
                self.assertIn("history_start", query.parameters)

    def test_same_job_under_two_periods_yields_identical_derived_values(self):
        narrow = job_facts.fetch_job_facts(
            job_ids=[JOB_ID], history_start=HISTORY_START, execute=self._canned_executor()
        )[JOB_ID]
        wide = job_facts.fetch_job_facts(
            job_ids=[JOB_ID],
            history_start=HISTORY_START - timedelta(days=365),
            execute=self._canned_executor(),
        )[JOB_ID]

        self.assertEqual(narrow["days"], wide["days"])
        self.assertEqual(narrow["reviewer_user_ids"], wide["reviewer_user_ids"])
        self.assertEqual(
            job_facts.distribute_frames(narrow["days"], 100),
            job_facts.distribute_frames(wide["days"], 100),
        )
        self.assertEqual(
            job_facts.non_assignee_seconds(narrow, ASSIGNEE),
            job_facts.non_assignee_seconds(wide, ASSIGNEE),
        )

    def test_history_start_is_the_only_bound_stage_two_takes(self):
        executor = self._canned_executor()

        job_facts.fetch_job_facts(job_ids=[JOB_ID], history_start=HISTORY_START, execute=executor)

        for fragment in ("accepter_user_ids", "AS working_ms"):
            parameters = executor.parameters_for(fragment)
            self.assertEqual(set(parameters), {"job_ids", "history_start"}, msg=f"in {fragment}")
            self.assertEqual(parameters["job_ids"], [JOB_ID])


class DayRoleArrayTest(unittest.TestCase):
    def test_a_job_spanning_two_dates_yields_two_elements_that_sum_to_the_job_total(self):
        facts = job_facts.build_facts(
            [JOB_ID],
            [_lifecycle_row(JOB_ID)],
            [
                _working_time_row(JOB_ID, ASSIGNEE, "2026-08-18", 3_600_000),
                _working_time_row(JOB_ID, ASSIGNEE, "2026-08-19", 1_800_000),
            ],
        )
        days = facts[JOB_ID]["days"]

        self.assertEqual([element["date"] for element in days], ["2026-08-18", "2026-08-19"])
        self.assertAlmostEqual(sum(element["seconds"] for element in days), 5400.0, places=3)

    def test_two_reviewers_split_into_per_person_elements(self):
        facts = job_facts.build_facts(
            [JOB_ID],
            [_lifecycle_row(JOB_ID, accepter_user_ids=[REVIEWER, SECOND_REVIEWER])],
            [
                _working_time_row(JOB_ID, REVIEWER, "2026-08-20", 600_000),
                _working_time_row(JOB_ID, SECOND_REVIEWER, "2026-08-20", 300_000),
            ],
        )
        days = facts[JOB_ID]["days"]

        self.assertEqual(len(days), 2)
        self.assertEqual({element["user_id"] for element in days}, {REVIEWER, SECOND_REVIEWER})
        self.assertEqual({element["role"] for element in days}, {ROLE_REVIEW})

    def test_roles_are_split_by_the_reviewer_set(self):
        facts = job_facts.build_facts(
            [JOB_ID],
            [_lifecycle_row(JOB_ID, accepter_user_ids=[REVIEWER])],
            [
                _working_time_row(JOB_ID, ASSIGNEE, "2026-08-18", 3_600_000),
                _working_time_row(JOB_ID, REVIEWER, "2026-08-20", 600_000),
            ],
        )
        roles = {element["user_id"]: element["role"] for element in facts[JOB_ID]["days"]}

        self.assertEqual(roles, {ASSIGNEE: ROLE_ANNOTATION, REVIEWER: ROLE_REVIEW})

    def test_requested_jobs_with_no_events_still_get_an_entry(self):
        facts = job_facts.build_facts([JOB_ID, OTHER_JOB_ID], [_lifecycle_row(JOB_ID)], [])

        self.assertEqual(set(facts), {JOB_ID, OTHER_JOB_ID})
        self.assertEqual(facts[OTHER_JOB_ID]["days"], [])

    def test_date_keys_are_kst_calendar_days(self):
        sql = job_facts.build_working_time_scan(job_ids=[JOB_ID], history_start=HISTORY_START).sql

        self.assertIn("toString(toDate(toTimeZone(timestamp, 'Asia/Seoul')))", sql)
        self.assertEqual(REPORT_TIMEZONE, "Asia/Seoul")

        # 04:00 UTC is 13:00 the same day in KST, and 20:00 UTC is 05:00 the NEXT day.
        # Both must land on the KST calendar day, which is what the expression above does.
        seoul = ZoneInfo(REPORT_TIMEZONE)
        self.assertEqual(
            datetime(2026, 8, 18, 4, 0, tzinfo=UTC).astimezone(seoul).strftime("%Y-%m-%d"),
            "2026-08-18",
        )
        self.assertEqual(
            datetime(2026, 8, 17, 20, 0, tzinfo=UTC).astimezone(seoul).strftime("%Y-%m-%d"),
            "2026-08-18",
        )

    def test_no_week_boundary_is_baked_into_the_query(self):
        # Beacon owns the week axis; ImageLab only ever knows days.
        sql = job_facts.build_working_time_scan(job_ids=[JOB_ID], history_start=HISTORY_START).sql

        for weekly in ("toMonday", "toStartOfWeek", "toWeek", "toISOWeek"):
            self.assertNotIn(weekly, sql)


class FrameDistributionTest(unittest.TestCase):
    def _days(self):
        return [
            {
                "date": "2026-08-18",
                "user_id": ASSIGNEE,
                "role": ROLE_ANNOTATION,
                "seconds": 10800.0,
                "frames": None,
            },
            {
                "date": "2026-08-19",
                "user_id": ASSIGNEE,
                "role": ROLE_ANNOTATION,
                "seconds": 3600.0,
                "frames": None,
            },
            {
                "date": "2026-08-20",
                "user_id": REVIEWER,
                "role": ROLE_REVIEW,
                "seconds": 1800.0,
                "frames": None,
            },
        ]

    def test_frames_are_distributed_by_the_same_role_time_share(self):
        distributed = job_facts.distribute_frames(self._days(), 50)

        self.assertAlmostEqual(distributed[0]["frames"], 37.5, places=3)
        self.assertAlmostEqual(distributed[1]["frames"], 12.5, places=3)
        # The review axis divides by review time only, so a single reviewer day gets the
        # whole frame count rather than a fraction of the annotator's hours.
        self.assertAlmostEqual(distributed[2]["frames"], 50.0, places=3)

    def test_each_role_sums_to_the_job_frame_count(self):
        distributed = job_facts.distribute_frames(self._days(), 50)

        for role in (ROLE_ANNOTATION, ROLE_REVIEW):
            with self.subTest(role=role):
                total = sum(e["frames"] for e in distributed if e["role"] == role)
                self.assertAlmostEqual(total, 50.0, places=3)

    def test_a_role_with_zero_seconds_does_not_divide_by_zero(self):
        days = self._days()
        days[2]["seconds"] = 0.0

        distributed = job_facts.distribute_frames(days, 50)

        self.assertEqual(distributed[2]["frames"], 0.0)
        self.assertAlmostEqual(distributed[0]["frames"], 37.5, places=3)

    def test_an_unknown_frame_count_leaves_a_null_share(self):
        distributed = job_facts.distribute_frames(self._days(), None)

        self.assertTrue(all(element["frames"] is None for element in distributed))

    def test_the_input_elements_are_not_mutated(self):
        days = self._days()

        job_facts.distribute_frames(days, 50)

        self.assertTrue(all(element["frames"] is None for element in days))


class ReviewerIdentityTest(unittest.TestCase):
    def test_the_reviewer_is_whoever_accepted(self):
        reviewers, source = resolve_reviewers([REVIEWER], [ASSIGNEE])

        self.assertEqual(reviewers, [REVIEWER])
        self.assertEqual(source, REVIEWER_FROM_ACCEPTANCE)

    def test_a_rejecter_is_the_reviewer_only_when_nobody_accepted(self):
        reviewers, source = resolve_reviewers([], [REVIEWER])

        self.assertEqual(reviewers, [REVIEWER])
        self.assertEqual(source, REVIEWER_FROM_REJECTION)

    def test_a_job_with_neither_has_no_reviewer(self):
        self.assertEqual(resolve_reviewers([], []), ([], None))

    def test_reviewers_are_keyed_on_user_id_not_user_name(self):
        # user_name is an event-time snapshot: a rename orphaned that person's history in
        # the original §3b query. None of these scans even select it.
        for query in (
            job_facts.build_job_lifecycle_scan(job_ids=[JOB_ID], history_start=HISTORY_START),
            job_facts.build_working_time_scan(job_ids=[JOB_ID], history_start=HISTORY_START),
            job_rounds.build_job_timeline_scan(job_id=JOB_ID, history_start=HISTORY_START),
        ):
            with self.subTest(sql=query.sql[:40]):
                self.assertNotIn("user_name", query.sql)
                self.assertIn("user_id", query.sql)

    def test_a_rename_mid_history_still_resolves_to_one_person(self):
        # Two acceptances by the same account under two different display names collapse
        # to one reviewer, and both of that person's days keep the review role.
        facts = job_facts.build_facts(
            [JOB_ID],
            [_lifecycle_row(JOB_ID, accepter_user_ids=[REVIEWER, REVIEWER])],
            [
                _working_time_row(JOB_ID, REVIEWER, "2026-08-19", 300_000),
                _working_time_row(JOB_ID, REVIEWER, "2026-08-20", 300_000),
            ],
        )
        fact = facts[JOB_ID]

        self.assertEqual(fact["reviewer_user_ids"], [REVIEWER])
        self.assertEqual(fact["working_ms_by_user"], {REVIEWER: 600_000})
        self.assertEqual({element["role"] for element in fact["days"]}, {ROLE_REVIEW})


class ReviewAxisTest(unittest.TestCase):
    """
    Whose working time belongs on the review axis - a different question from who reviewed.

    ``resolve_reviewers`` answers identity: acceptance-primary, rejection as a fallback,
    and it is what the response displays. The axis is "accepted or rejected this job, and
    is not its assignee". Deriving the second from the first misfiled time both ways.
    """

    def _fact(self, *, accepters, rejecters, working_time, assignee=ASSIGNEE):
        return job_facts.build_facts(
            [JOB_ID],
            [_lifecycle_row(JOB_ID, accepter_user_ids=accepters, rejecter_user_ids=rejecters)],
            working_time,
            {JOB_ID: assignee},
        )[JOB_ID]

    def test_the_axis_and_the_identity_answer_different_questions(self):
        # An assignee accepting their own job is the reviewer for display purposes and
        # nothing more; a rejecter of an accepted job is on the axis without ever being
        # the displayed reviewer.
        self.assertEqual(resolve_review_role_ids([ASSIGNEE], [], ASSIGNEE), [])
        self.assertEqual(resolve_reviewers([ASSIGNEE], []), ([ASSIGNEE], REVIEWER_FROM_ACCEPTANCE))

        self.assertEqual(
            resolve_review_role_ids([REVIEWER], [SECOND_REVIEWER], ASSIGNEE),
            [REVIEWER, SECOND_REVIEWER],
        )
        self.assertEqual(resolve_reviewers([REVIEWER], [SECOND_REVIEWER])[0], [REVIEWER])

    def test_a_job_accepted_by_its_own_assignee_keeps_its_annotation_time(self):
        fact = self._fact(
            accepters=[ASSIGNEE],
            rejecters=[],
            working_time=[_working_time_row(JOB_ID, ASSIGNEE, "2026-08-18", 3_600_000)],
        )

        # Identity is untouched - they really are the account that accepted it.
        self.assertEqual(fact["reviewer_user_ids"], [ASSIGNEE])
        self.assertEqual(fact["reviewer_source"], REVIEWER_FROM_ACCEPTANCE)

        # Their hours are annotation, so the frames land on the annotation axis and the
        # review axis stays empty instead of collecting the whole job.
        distributed = job_facts.distribute_frames(fact["days"], 100)
        self.assertEqual([element["role"] for element in distributed], [ROLE_ANNOTATION])
        self.assertAlmostEqual(
            sum(element["frames"] for element in distributed if element["role"] == ROLE_ANNOTATION),
            100.0,
            places=3,
        )
        self.assertEqual([e for e in distributed if e["role"] == ROLE_REVIEW], [])

        # And the estimated-worker cross-check still has something to say about the job.
        self.assertEqual(fact["estimated_worker_user_id"], ASSIGNEE)

    def test_a_reviewer_who_only_rejected_an_accepted_job_is_on_the_review_axis(self):
        fact = self._fact(
            accepters=[REVIEWER],
            rejecters=[SECOND_REVIEWER],
            working_time=[
                _working_time_row(JOB_ID, ASSIGNEE, "2026-08-18", 3_600_000),
                _working_time_row(JOB_ID, REVIEWER, "2026-08-20", 600_000),
                _working_time_row(JOB_ID, SECOND_REVIEWER, "2026-08-20", 900_000),
                _working_time_row(JOB_ID, OUTSIDER, "2026-08-21", 120_000),
            ],
        )
        roles = {element["user_id"]: element["role"] for element in fact["days"]}

        self.assertEqual(
            roles,
            {
                ASSIGNEE: ROLE_ANNOTATION,
                REVIEWER: ROLE_REVIEW,
                SECOND_REVIEWER: ROLE_REVIEW,
                OUTSIDER: ROLE_ANNOTATION,
            },
        )
        # The displayed reviewer is still the accepter alone.
        self.assertEqual(fact["reviewer_user_ids"], [REVIEWER])

        # The non-assignee total is built from the same set, so the rejecter's 900 seconds
        # stay out of it: only the outsider's time is unattributed.
        self.assertAlmostEqual(job_facts.non_assignee_seconds(fact, ASSIGNEE), 120.0, places=3)


class NonAssigneeTotalTest(unittest.TestCase):
    def _fact(self):
        return job_facts.build_facts(
            [JOB_ID],
            [
                _lifecycle_row(
                    JOB_ID,
                    accepter_user_ids=[REVIEWER],
                    rejecter_user_ids=[SECOND_REVIEWER],
                    rejections=1,
                )
            ],
            [
                _working_time_row(JOB_ID, ASSIGNEE, "2026-08-18", 3_600_000),
                _working_time_row(JOB_ID, REVIEWER, "2026-08-20", 600_000),
                _working_time_row(JOB_ID, SECOND_REVIEWER, "2026-08-20", 900_000),
                _working_time_row(JOB_ID, OUTSIDER, "2026-08-21", 120_000),
            ],
        )[JOB_ID]

    def test_someone_who_only_rejected_is_excluded(self):
        # Without this exclusion a second reviewer who only sent the job back would make an
        # ordinary job look attribution-suspect.
        total = job_facts.non_assignee_seconds(self._fact(), ASSIGNEE)

        self.assertAlmostEqual(total, 120.0, places=3)

    def test_the_assignee_and_the_reviewer_are_excluded_too(self):
        fact = self._fact()

        self.assertAlmostEqual(job_facts.non_assignee_seconds(fact, ASSIGNEE), 120.0, places=3)
        # With no assignee at all only the reviewer and the rejecter drop out.
        self.assertAlmostEqual(job_facts.non_assignee_seconds(fact, None), 3600.0 + 120.0, places=3)

    def test_the_estimated_worker_is_the_busiest_non_reviewer(self):
        fact = self._fact()

        self.assertEqual(fact["estimated_worker_user_id"], ASSIGNEE)

    def test_the_estimated_worker_is_none_when_only_reviewers_worked(self):
        fact = job_facts.build_facts(
            [JOB_ID],
            [_lifecycle_row(JOB_ID, accepter_user_ids=[REVIEWER])],
            [_working_time_row(JOB_ID, REVIEWER, "2026-08-20", 600_000)],
        )[JOB_ID]

        self.assertIsNone(fact["estimated_worker_user_id"])


class RoundDecompositionTest(unittest.TestCase):
    T1 = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)
    T2 = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    T3 = datetime(2026, 8, 18, 6, 0, tzinfo=UTC)
    T4 = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
    T5 = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)
    T6 = datetime(2026, 8, 19, 1, 0, tzinfo=UTC)

    def _two_round_timeline(self):
        return [
            _transition(self.T1, "state", "in progress", ASSIGNEE),
            _working(self.T1 + timedelta(minutes=30), ASSIGNEE, 600_000),
            _transition(self.T2, "state", "completed", ASSIGNEE),
            _working(self.T2 + timedelta(minutes=10), REVIEWER, 300_000),
            _transition(self.T3, "state", "rejected", REVIEWER),
            _working(self.T3 + timedelta(minutes=10), ASSIGNEE, 120_000),
            _transition(self.T4, "state", "completed", ASSIGNEE),
            _working(self.T4 + timedelta(minutes=10), REVIEWER, 60_000),
            _transition(self.T5, "stage", "acceptance", REVIEWER),
        ]

    def test_rounds_come_back_as_annotation_review_rework_rereview(self):
        result = job_rounds.decompose_rounds(JOB_ID, self._two_round_timeline())

        self.assertEqual(
            [(entry["round"], entry["phase"]) for entry in result["rounds"]],
            [
                (1, ROLE_ANNOTATION),
                (1, ROLE_REVIEW),
                (2, ROLE_ANNOTATION),
                (2, ROLE_REVIEW),
            ],
        )

    def test_round_boundaries_follow_the_transitions(self):
        rounds = job_rounds.decompose_rounds(JOB_ID, self._two_round_timeline())["rounds"]

        self.assertEqual(
            [(entry["started_at"], entry["ended_at"]) for entry in rounds],
            [
                (self.T1, self.T2),
                (self.T2, self.T3),
                (self.T3, self.T4),
                (self.T4, self.T5),
            ],
        )

    def test_working_time_is_split_between_worker_and_reviewer(self):
        rounds = job_rounds.decompose_rounds(JOB_ID, self._two_round_timeline())["rounds"]

        self.assertAlmostEqual(rounds[0]["worker_seconds"], 600.0, places=3)
        self.assertAlmostEqual(rounds[0]["reviewer_seconds"], 0.0, places=3)
        self.assertAlmostEqual(rounds[1]["reviewer_seconds"], 300.0, places=3)
        self.assertAlmostEqual(rounds[2]["worker_seconds"], 120.0, places=3)
        self.assertAlmostEqual(rounds[3]["reviewer_seconds"], 60.0, places=3)

    def test_the_final_round_of_a_job_still_in_flight_has_no_end(self):
        timeline = [
            _transition(self.T1, "state", "in progress", ASSIGNEE),
            _working(self.T1 + timedelta(minutes=30), ASSIGNEE, 600_000),
            _transition(self.T2, "state", "completed", ASSIGNEE),
        ]

        result = job_rounds.decompose_rounds(JOB_ID, timeline)

        self.assertIsNone(result["accepted_at"])
        self.assertIsNone(result["rounds"][-1]["ended_at"])
        self.assertIsNone(result["trailing"])

    def test_activity_after_the_first_acceptance_lands_in_the_trailing_bucket(self):
        timeline = self._two_round_timeline() + [
            _transition(self.T6, "stage", "annotation", ASSIGNEE),
            _working(self.T6 + timedelta(minutes=5), ASSIGNEE, 90_000),
        ]

        result = job_rounds.decompose_rounds(JOB_ID, timeline)

        self.assertEqual(len(result["rounds"]), 4)
        self.assertAlmostEqual(result["trailing"]["worker_seconds"], 90.0, places=3)
        self.assertIsNone(result["trailing"]["ended_at"])
        self.assertEqual(result["trailing"]["started_at"], self.T5)

        in_rounds = sum(
            entry["worker_seconds"] + entry["reviewer_seconds"] for entry in result["rounds"]
        )
        self.assertAlmostEqual(
            in_rounds
            + result["trailing"]["worker_seconds"]
            + result["trailing"]["reviewer_seconds"],
            result["totals"]["worker_seconds"] + result["totals"]["reviewer_seconds"],
            places=3,
        )

    def test_a_job_that_never_reached_in_progress_returns_zero_rounds(self):
        timeline = [
            _working(self.T1, ASSIGNEE, 60_000),
            _transition(self.T5, "stage", "acceptance", REVIEWER),
        ]

        result = job_rounds.decompose_rounds(JOB_ID, timeline)

        self.assertEqual(result["rounds"], [])
        self.assertEqual(result["accepted_at"], self.T5)

    def test_work_before_the_in_progress_transition_is_kept(self):
        early = self.T1 - timedelta(hours=2)
        timeline = [
            _working(early, ASSIGNEE, 300_000),
            _transition(self.T1, "state", "in progress", ASSIGNEE),
            _transition(self.T2, "state", "completed", ASSIGNEE),
        ]

        rounds = job_rounds.decompose_rounds(JOB_ID, timeline)["rounds"]

        self.assertEqual(rounds[0]["started_at"], early)
        self.assertAlmostEqual(rounds[0]["worker_seconds"], 300.0, places=3)

    def test_on_a_never_accepted_job_the_rejecter_becomes_the_reviewer(self):
        timeline = [
            _transition(self.T1, "state", "in progress", ASSIGNEE),
            _transition(self.T2, "state", "completed", ASSIGNEE),
            _transition(self.T3, "state", "rejected", REVIEWER),
            _working(self.T2 + timedelta(minutes=10), REVIEWER, 300_000),
        ]

        result = job_rounds.decompose_rounds(JOB_ID, timeline)

        self.assertEqual(result["reviewer_user_ids"], [REVIEWER])
        self.assertEqual(result["reviewer_source"], REVIEWER_FROM_REJECTION)
        self.assertAlmostEqual(result["rounds"][1]["reviewer_seconds"], 300.0, places=3)

    def test_on_an_accepted_job_the_assignees_own_rejection_is_ignored(self):
        # The dump contains annotators who flipped their own job to `rejected`. Treating
        # that as review evidence moved ~567 hours of annotation into the review axis.
        timeline = [
            _transition(self.T1, "state", "in progress", ASSIGNEE),
            _working(self.T1 + timedelta(minutes=30), ASSIGNEE, 600_000),
            _transition(self.T2, "state", "rejected", ASSIGNEE),
            _transition(self.T3, "state", "completed", ASSIGNEE),
            _transition(self.T5, "stage", "acceptance", REVIEWER),
        ]

        result = job_rounds.decompose_rounds(JOB_ID, timeline)

        self.assertEqual(result["reviewer_user_ids"], [REVIEWER])
        self.assertEqual(result["reviewer_source"], REVIEWER_FROM_ACCEPTANCE)
        self.assertAlmostEqual(result["totals"]["worker_seconds"], 600.0, places=3)
        self.assertAlmostEqual(result["totals"]["reviewer_seconds"], 0.0, places=3)

    def test_the_timeline_is_read_in_a_single_scan(self):
        executor = _StubExecutor(timeline=self._two_round_timeline())

        result = job_rounds.fetch_job_rounds(
            job_id=JOB_ID, history_start=HISTORY_START, execute=executor
        )

        self.assertEqual(len(executor.calls), 1)
        self.assertEqual(
            executor.calls[0][1],
            {"job_id": JOB_ID, "history_start": HISTORY_START.replace(tzinfo=None)},
        )
        self.assertEqual(result["job_id"], JOB_ID)


class RoundReviewAxisTest(unittest.TestCase):
    """
    Whose seconds a round puts on the review side - not the same question as who reviewed.

    ``resolve_reviewers`` answers identity: acceptance-primary, and it is what ``reviewer``
    / ``reviewers`` / ``reviewer_source`` display. The axis is "accepted or rejected this
    job, and is not its assignee". Cutting the split on identity misfiled time both ways,
    so both directions are pinned here, along with the identity fields staying put.
    """

    T1 = datetime(2026, 8, 18, 1, 0, tzinfo=UTC)
    T2 = datetime(2026, 8, 18, 5, 0, tzinfo=UTC)
    T3 = datetime(2026, 8, 18, 6, 0, tzinfo=UTC)
    T4 = datetime(2026, 8, 18, 8, 0, tzinfo=UTC)
    T5 = datetime(2026, 8, 18, 9, 0, tzinfo=UTC)

    def _self_accepted_timeline(self):
        """One person start to finish: the assignee submits and accepts their own job."""
        return [
            _transition(self.T1, "state", "in progress", ASSIGNEE),
            _working(self.T1 + timedelta(minutes=30), ASSIGNEE, 600_000),
            _transition(self.T2, "state", "completed", ASSIGNEE),
            _working(self.T2 + timedelta(minutes=10), ASSIGNEE, 300_000),
            _transition(self.T5, "stage", "acceptance", ASSIGNEE),
            _working(self.T5 + timedelta(minutes=5), ASSIGNEE, 90_000),
        ]

    def _rejected_by_a_second_reviewer_timeline(self):
        """Accepted by one reviewer, but sent back once by a different one."""
        return [
            _transition(self.T1, "state", "in progress", ASSIGNEE),
            _working(self.T1 + timedelta(minutes=30), ASSIGNEE, 600_000),
            _transition(self.T2, "state", "completed", ASSIGNEE),
            _working(self.T2 + timedelta(minutes=10), SECOND_REVIEWER, 900_000),
            _transition(self.T3, "state", "rejected", SECOND_REVIEWER),
            _working(self.T3 + timedelta(minutes=10), ASSIGNEE, 120_000),
            _transition(self.T4, "state", "completed", ASSIGNEE),
            _working(self.T4 + timedelta(minutes=10), REVIEWER, 60_000),
            _transition(self.T5, "stage", "acceptance", REVIEWER),
        ]

    def test_a_job_accepted_by_its_own_assignee_keeps_its_annotation_time(self):
        result = job_rounds.decompose_rounds(JOB_ID, self._self_accepted_timeline(), ASSIGNEE)

        # Identity is untouched by the split: they really are the account that accepted it.
        self.assertEqual(result["reviewer_user_ids"], [ASSIGNEE])
        self.assertEqual(result["reviewer_source"], REVIEWER_FROM_ACCEPTANCE)

        self.assertEqual(
            [(entry["worker_seconds"], entry["reviewer_seconds"]) for entry in result["rounds"]],
            [(600.0, 0.0), (300.0, 0.0)],
        )
        self.assertEqual(
            (result["trailing"]["worker_seconds"], result["trailing"]["reviewer_seconds"]),
            (90.0, 0.0),
        )
        self.assertEqual(result["totals"], {"worker_seconds": 990.0, "reviewer_seconds": 0.0})

        # Nobody is on the axis - a person cannot review themselves onto it.
        self.assertEqual(result["review_role_user_ids"], [])

    def test_a_reviewer_who_only_rejected_an_accepted_job_is_on_the_review_axis(self):
        result = job_rounds.decompose_rounds(
            JOB_ID, self._rejected_by_a_second_reviewer_timeline(), ASSIGNEE
        )

        # The displayed reviewer is still the accepter alone - accepters win identity.
        self.assertEqual(result["reviewer_user_ids"], [REVIEWER])
        self.assertEqual(result["reviewer_source"], REVIEWER_FROM_ACCEPTANCE)

        # The rejecter's fifteen minutes are review time, not the annotator's.
        self.assertEqual(
            [(entry["worker_seconds"], entry["reviewer_seconds"]) for entry in result["rounds"]],
            [(600.0, 0.0), (0.0, 900.0), (120.0, 0.0), (0.0, 60.0)],
        )
        self.assertEqual(result["totals"], {"worker_seconds": 720.0, "reviewer_seconds": 960.0})

        # Both of them reviewed something, so both are on the axis.
        self.assertEqual(result["review_role_user_ids"], [REVIEWER, SECOND_REVIEWER])

    def test_with_no_assignee_the_axis_falls_back_to_the_reviewer_identity(self):
        # Nothing in a timeline says who the job belongs to, and on an accepted job a
        # rejection is as likely to be the annotator's own mis-click as a second reviewer's
        # verdict - only the assignee tells them apart. A caller that cannot supply one
        # therefore gets the identity set, which is what this function answered before the
        # assignee was threaded in: never better, but never worse either.
        result = job_rounds.decompose_rounds(JOB_ID, self._rejected_by_a_second_reviewer_timeline())

        self.assertEqual(result["review_role_user_ids"], [REVIEWER])
        self.assertAlmostEqual(result["rounds"][1]["worker_seconds"], 900.0, places=3)


class FreshnessTest(unittest.TestCase):
    def test_daily_presence_and_last_seen_come_back_together(self):
        collected_at = datetime(2026, 8, 19, 8, 30, tzinfo=UTC)

        result = freshness.map_freshness(
            [
                {"day": "2026-08-18", "events": 120, "last_seen": collected_at},
                {"day": "2026-08-19", "events": 4, "last_seen": collected_at},
            ],
            [{"last_seen": collected_at, "events": 124}],
        )

        self.assertEqual(result["scope"], WORKING_TIME_SCOPE)
        self.assertEqual([day["date"] for day in result["days"]], ["2026-08-18", "2026-08-19"])
        self.assertEqual([day["events"] for day in result["days"]], [120, 4])
        self.assertEqual(result["last_seen"], collected_at)

    def test_an_empty_result_reports_no_last_seen(self):
        # ClickHouse returns the type default for max() over zero rows; count() is what
        # tells that apart from a real 1970 timestamp.
        result = freshness.map_freshness([], [{"last_seen": datetime(1970, 1, 1), "events": 0}])

        self.assertEqual(result["days"], [])
        self.assertIsNone(result["last_seen"])

    def test_both_scans_are_issued(self):
        executor = mock.Mock(return_value=[])

        freshness.fetch_freshness(
            period_start=PERIOD_START,
            period_end=PERIOD_END,
            last_seen_since=HISTORY_START,
            execute=executor,
        )

        self.assertEqual(executor.call_count, 2)
        daily_sql, daily_parameters = executor.call_args_list[0].args
        last_seen_sql, last_seen_parameters = executor.call_args_list[1].args

        self.assertIn("GROUP BY day", daily_sql)
        self.assertEqual(
            daily_parameters,
            {
                "period_start": PERIOD_START.replace(tzinfo=None),
                "period_end": PERIOD_END.replace(tzinfo=None),
            },
        )
        self.assertIn("{since:DateTime64}", last_seen_sql)
        self.assertEqual(last_seen_parameters, {"since": HISTORY_START.replace(tzinfo=None)})

    def test_last_seen_falls_back_to_the_period_start(self):
        executor = mock.Mock(return_value=[])

        freshness.fetch_freshness(
            period_start=PERIOD_START, period_end=PERIOD_END, execute=executor
        )

        self.assertEqual(
            executor.call_args_list[1].args[1], {"since": PERIOD_START.replace(tzinfo=None)}
        )


class ExecutorInjectionTest(unittest.TestCase):
    def test_fetch_helpers_use_the_injected_executor(self):
        executor = mock.Mock(return_value=[])

        job_facts.fetch_job_ids(period_start=PERIOD_START, period_end=PERIOD_END, execute=executor)

        executor.assert_called_once()

    def test_an_empty_id_set_issues_no_stage_two_query(self):
        executor = mock.Mock(return_value=[])

        self.assertEqual(
            job_facts.fetch_job_facts(job_ids=[], history_start=HISTORY_START, execute=executor),
            {},
        )
        executor.assert_not_called()

    def test_the_real_executor_is_resolved_lazily(self):
        # The pure builders must stay importable without the ClickHouse driver, so the
        # driver-backed executor is only imported when it is actually needed.
        with mock.patch(
            "cvat.apps.production_stats.queries.job_facts.default_executor"
        ) as resolve_default:
            resolve_default.return_value = mock.Mock(return_value=[])

            job_facts.fetch_job_ids(period_start=PERIOD_START, period_end=PERIOD_END)

        resolve_default.assert_called_once()


class NginxRoutingTest(unittest.TestCase):
    """
    The longer upstream read timeout belongs to these two endpoints, not to all of CVAT.

    The ClickHouse aggregations behind /api/production_stats/ need more than nginx's 60s
    default; nothing else in this API does. Granting it in the catch-all doubled the
    upstream read timeout of every route in the server for the sake of two of them.
    """

    def test_production_stats_has_its_own_location_block(self):
        self.assertIn(PRODUCTION_STATS_LOCATION, nginx_locations())
        self.assertEqual(nginx_read_timeout(PRODUCTION_STATS_LOCATION), 120)

    def test_the_catch_all_keeps_the_nginx_default_read_timeout(self):
        self.assertIsNone(nginx_read_timeout("/"))

    def test_the_dedicated_block_proxies_exactly_like_the_catch_all(self):
        # A location block inherits nothing from the sibling it was split out of, so every
        # directive the catch-all carries has to be repeated here - otherwise these two
        # routes would quietly lose their forwarded headers, their buffering or their
        # upstream.
        locations = nginx_locations()
        dedicated = locations[PRODUCTION_STATS_LOCATION]

        for line in locations["/"].splitlines():
            directive = line.strip()
            if not directive or directive.startswith("#"):
                continue

            with self.subTest(directive=directive):
                self.assertIn(directive, dedicated)


if __name__ == "__main__":
    unittest.main()
