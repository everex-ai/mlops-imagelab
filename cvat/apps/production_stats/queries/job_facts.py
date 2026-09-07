# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""
The two-stage job facts scan.

Stage 1 (:func:`build_job_id_scan`) is the only query that sees the caller's period. It
returns nothing but job ids: the union of "an acceptance transition happened in the
window" and "working time was recorded in the window".

Stage 2 (:func:`build_job_lifecycle_scan` and :func:`build_working_time_scan`) computes
every derived value for that id set - the day/role array, the reviewer, the rejecters, the
per-user working time - with **no** period predicate. Its time predicate is a lower bound
the caller reads from Postgres ``Job.created_date``; neither a transition nor a working
time event can predate the job's creation, so that bound is safe and still prunes
partitions.

Nothing here knows about frames or assignees: both come from Postgres. The view layer
calls :func:`distribute_frames` and :func:`non_assignee_seconds` once it has them.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from cvat.apps.production_stats.queries import (
    ROLE_ANNOTATION,
    ROLE_REVIEW,
    Query,
    QueryExecutor,
    default_executor,
    ms_to_seconds,
    resolve_reviewers,
    to_utc_naive,
)

# Stage 1. The period is a half-open interval so that adjacent windows neither overlap nor
# drop an event. A job qualifies if it was accepted in the window OR was worked on in it -
# filtering on acceptance alone would drop a job worked in W3 and accepted in W5 entirely,
# which would make W3's working time depend on the window the user happens to pick.
JOB_ID_SCAN_SQL = """
SELECT DISTINCT job_id
FROM events
WHERE timestamp >= {period_start:DateTime64}
  AND timestamp < {period_end:DateTime64}
  AND job_id IS NOT NULL
  AND (
        scope = 'send:working_time'
     OR (scope = 'update:job' AND obj_name = 'stage' AND obj_val = 'acceptance')
  )
"""

JOB_ID_SCAN_PROJECT_FILTER_SQL = "  AND project_id = {project_id:UInt64}\n"

JOB_ID_SCAN_ORDER_SQL = "ORDER BY job_id\n"

# Stage 2a: the job lifecycle, ported from §0 of docs/analytics/annotation-time-metrics.sql.
# `min(if(...))` rather than `minIf(...)` on purpose: minIf returns the type default
# (1970-01-01) when nothing matches, while the `if` form yields a real NULL.
JOB_LIFECYCLE_SCAN_SQL = """
SELECT
    job_id,
    min(if(obj_name = 'state' AND obj_val = 'in progress', timestamp, NULL)) AS started_at,
    min(if(obj_name = 'state' AND obj_val = 'completed', timestamp, NULL)) AS first_submit_at,
    min(if(obj_name = 'stage' AND obj_val = 'acceptance', timestamp, NULL)) AS accepted_at,
    max(if(obj_name = 'assignee', timestamp, NULL)) AS assignee_changed_at,
    countIf(obj_name = 'state' AND obj_val = 'rejected') AS rejections,
    groupUniqArrayIf(
        ifNull(user_id, 0),
        obj_name = 'stage' AND obj_val = 'acceptance' AND user_id IS NOT NULL
    ) AS accepter_user_ids,
    groupUniqArrayIf(
        ifNull(user_id, 0),
        obj_name = 'state' AND obj_val = 'rejected' AND user_id IS NOT NULL
    ) AS rejecter_user_ids
FROM events
WHERE timestamp >= {history_start:DateTime64}
  AND scope = 'update:job'
  AND job_id IN {job_ids:Array(UInt64)}
GROUP BY job_id
ORDER BY job_id
"""

# Stage 2b: working time by job, person and KST calendar day. The day is emitted as a
# 'YYYY-MM-DD' string; the week axis is Beacon's business, not this fork's.
WORKING_TIME_SCAN_SQL = """
SELECT
    job_id,
    user_id,
    toString(toDate(toTimeZone(timestamp, 'Asia/Seoul'))) AS day,
    sum(duration) AS working_ms
FROM events
WHERE timestamp >= {history_start:DateTime64}
  AND scope = 'send:working_time'
  AND job_id IN {job_ids:Array(UInt64)}
  AND user_id IS NOT NULL
GROUP BY job_id, user_id, day
ORDER BY job_id, day, user_id
"""


def build_job_id_scan(
    *,
    period_start: datetime,
    period_end: datetime,
    project_id: int | None = None,
) -> Query:
    """Stage 1: the only query that applies the caller's period."""
    sql = JOB_ID_SCAN_SQL
    parameters: dict[str, Any] = {
        "period_start": to_utc_naive(period_start),
        "period_end": to_utc_naive(period_end),
    }

    if project_id is not None:
        # Optional on purpose: the screen's default is "all projects", so the unfiltered
        # path is the first one users take.
        sql += JOB_ID_SCAN_PROJECT_FILTER_SQL
        parameters["project_id"] = int(project_id)

    return Query(sql + JOB_ID_SCAN_ORDER_SQL, parameters)


def build_job_lifecycle_scan(*, job_ids: Sequence[int], history_start: datetime) -> Query:
    """Stage 2a. ``history_start`` is min(Job.created_date) over ``job_ids``, from Postgres."""
    return Query(JOB_LIFECYCLE_SCAN_SQL, _stage_two_parameters(job_ids, history_start))


def build_working_time_scan(*, job_ids: Sequence[int], history_start: datetime) -> Query:
    """Stage 2b. ``history_start`` is min(Job.created_date) over ``job_ids``, from Postgres."""
    return Query(WORKING_TIME_SCAN_SQL, _stage_two_parameters(job_ids, history_start))


def _stage_two_parameters(job_ids: Sequence[int], history_start: datetime) -> dict[str, Any]:
    return {
        "job_ids": [int(job_id) for job_id in job_ids],
        "history_start": to_utc_naive(history_start),
    }


def map_job_ids(rows: Iterable[Mapping[str, Any]]) -> list[int]:
    return [int(row["job_id"]) for row in rows]


def empty_fact(job_id: int) -> dict[str, Any]:
    """A job id that ClickHouse selected but for which no derived value was found yet."""
    return {
        "job_id": int(job_id),
        "started_at": None,
        "first_submit_at": None,
        "accepted_at": None,
        "assignee_changed_at": None,
        "rejections": 0,
        "accepter_user_ids": [],
        "rejecter_user_ids": [],
        "reviewer_user_ids": [],
        "reviewer_source": None,
        "days": [],
        "working_ms_by_user": {},
        "estimated_worker_user_id": None,
    }


def build_facts(
    job_ids: Sequence[int],
    lifecycle_rows: Iterable[Mapping[str, Any]],
    working_time_rows: Iterable[Mapping[str, Any]],
) -> dict[int, dict[str, Any]]:
    """
    Fold the two stage-2 result sets into one fact per requested job id.

    Every requested id gets an entry, even when it has no events at all, so the view layer
    can merge Postgres rows without guarding every lookup.
    """
    facts = {int(job_id): empty_fact(job_id) for job_id in job_ids}

    _apply_lifecycle(facts, lifecycle_rows)
    _apply_working_time(facts, working_time_rows)

    for fact in facts.values():
        fact["days"].sort(
            key=lambda element: (element["date"], element["role"], element["user_id"])
        )
        fact["estimated_worker_user_id"] = _estimated_worker(fact)

    return facts


def _apply_lifecycle(facts: dict[int, dict[str, Any]], rows: Iterable[Mapping[str, Any]]) -> None:
    for row in rows:
        job_id = int(row["job_id"])
        fact = facts.setdefault(job_id, empty_fact(job_id))

        accepters = sorted({int(user_id) for user_id in row.get("accepter_user_ids") or ()})
        rejecters = sorted({int(user_id) for user_id in row.get("rejecter_user_ids") or ()})
        reviewers, reviewer_source = resolve_reviewers(accepters, rejecters)

        fact.update(
            {
                "started_at": row.get("started_at"),
                "first_submit_at": row.get("first_submit_at"),
                "accepted_at": row.get("accepted_at"),
                "assignee_changed_at": row.get("assignee_changed_at"),
                "rejections": int(row.get("rejections") or 0),
                "accepter_user_ids": accepters,
                "rejecter_user_ids": rejecters,
                "reviewer_user_ids": reviewers,
                "reviewer_source": reviewer_source,
            }
        )


def _apply_working_time(
    facts: dict[int, dict[str, Any]], rows: Iterable[Mapping[str, Any]]
) -> None:
    for row in rows:
        job_id = int(row["job_id"])
        fact = facts.setdefault(job_id, empty_fact(job_id))

        user_id = int(row["user_id"])
        working_ms = int(row.get("working_ms") or 0)

        # The role is attached here rather than in SQL so that it uses exactly the same
        # reviewer determination as the rounds endpoint does.
        role = ROLE_REVIEW if user_id in fact["reviewer_user_ids"] else ROLE_ANNOTATION

        fact["days"].append(
            {
                "date": str(row["day"]),
                "user_id": user_id,
                "role": role,
                "seconds": ms_to_seconds(working_ms),
                # Filled in by distribute_frames() once Postgres has supplied the frame
                # count; stays None for jobs whose Postgres row is gone.
                "frames": None,
            }
        )
        fact["working_ms_by_user"][user_id] = (
            fact["working_ms_by_user"].get(user_id, 0) + working_ms
        )


def _estimated_worker(fact: Mapping[str, Any]) -> int | None:
    """
    The event-based guess at who annotated the job: the non-reviewer with the most working
    time. §0 used argMax(user_name, ms); this keys on user_id. Ties break on the lowest id
    so two calls never disagree.
    """
    reviewers = set(fact["reviewer_user_ids"])
    candidates = [
        (working_ms, -user_id)
        for user_id, working_ms in fact["working_ms_by_user"].items()
        if user_id not in reviewers
    ]

    if not candidates:
        return None

    return -max(candidates)[1]


def distribute_frames(
    days: Sequence[Mapping[str, Any]], frame_count: int | None
) -> list[dict[str, Any]]:
    """
    Spread a job's frame count across its day/role elements.

    The frame count is one atomic number per job, so when days and roles split it has to be
    divided. The denominator is the total working seconds **of the same role**: dividing by
    the combined total would make the review axis's per-image time the review time divided
    by the annotator's hours, which means nothing.

    Consequence, enforced downstream rather than here: each role's distributed frames sum
    to the job's frame count, so the two roles must never be added together.

    ``frame_count`` is None for a job whose Postgres row no longer exists; those elements
    keep a null frame share rather than a fabricated zero.
    """
    if frame_count is None:
        return [dict(element, frames=None) for element in days]

    role_seconds: dict[str, float] = {}
    for element in days:
        role_seconds[element["role"]] = role_seconds.get(element["role"], 0.0) + element["seconds"]

    distributed = []
    for element in days:
        total = role_seconds[element["role"]]
        # A role with no recorded working time gets no frames instead of a ZeroDivisionError.
        share = 0.0 if total <= 0 else round(frame_count * element["seconds"] / total, 4)
        distributed.append(dict(element, frames=share))

    return distributed


def non_assignee_seconds(fact: Mapping[str, Any], assignee_user_id: int | None) -> float:
    """
    Working time on this job that belongs to nobody who is supposed to be on it.

    Excluded: the assignee, the reviewers, and anyone who set ``state -> rejected``. The
    last exclusion is the point - a reviewer who only rejected is not in the reviewer set
    (that set is the accepters) and would otherwise be counted here, flagging a perfectly
    ordinary job as attribution-suspect.
    """
    excluded = set(fact["reviewer_user_ids"]) | set(fact["rejecter_user_ids"])
    if assignee_user_id is not None:
        excluded.add(int(assignee_user_id))

    return ms_to_seconds(
        sum(
            working_ms
            for user_id, working_ms in fact["working_ms_by_user"].items()
            if user_id not in excluded
        )
    )


def fetch_job_ids(
    *,
    period_start: datetime,
    period_end: datetime,
    project_id: int | None = None,
    execute: QueryExecutor | None = None,
) -> list[int]:
    """Stage 1. Returns the job ids the caller's period selects."""
    execute = execute or default_executor()
    query = build_job_id_scan(
        period_start=period_start, period_end=period_end, project_id=project_id
    )

    return map_job_ids(execute(query.sql, query.parameters))


def fetch_job_facts(
    *,
    job_ids: Sequence[int],
    history_start: datetime,
    execute: QueryExecutor | None = None,
) -> dict[int, dict[str, Any]]:
    """
    Stage 2. Derived values for ``job_ids``, independent of the caller's period.

    ``history_start`` must be a lower bound on the jobs' history - pass
    ``min(Job.created_date)`` over ``job_ids`` from Postgres. It exists only to prune
    partitions; widening it changes performance, never results.
    """
    if not job_ids:
        return {}

    execute = execute or default_executor()
    lifecycle = build_job_lifecycle_scan(job_ids=job_ids, history_start=history_start)
    working_time = build_working_time_scan(job_ids=job_ids, history_start=history_start)

    return build_facts(
        job_ids,
        execute(lifecycle.sql, lifecycle.parameters),
        execute(working_time.sql, working_time.parameters),
    )
