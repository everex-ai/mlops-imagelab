# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""
Shared primitives for the production stats ClickHouse queries.

The queries in this package are ported from ``docs/analytics/annotation-time-metrics.sql``
(§0 ``job_metrics``, §3b ``job_rounds``, §6 the ``send:working_time`` freshness probe).
They are inlined here rather than deployed as ClickHouse views because nothing in this
repository deploys those parametrised views - even the Grafana dashboard next door
inlines the same CTEs.

Five deliberate divergences from the source SQL:

1. The scan runs in **two stages**. Stage 1 applies the caller's period and yields nothing
   but a set of job ids; stage 2 computes every derived value for that set with no user
   period predicate at all. Folding them into one stage would make the frame-distribution
   denominator "working time inside the window" and would strip the reviewer off any job
   whose acceptance fell outside it, which is exactly the pathology the union window was
   introduced to remove. Stage 2 still needs partition pruning (``cvat.events`` is ordered
   by ``timestamp`` alone), so it takes a *lower bound* supplied by the caller from
   Postgres ``Job.created_date`` - transitions and activity cannot predate job creation.
2. Reviewers are keyed on ``user_id``, not ``user_name``. §3b used the event-time username
   snapshot, so a rename orphaned that person's history; §0 already used ``user_id``.
   Names are resolved from Postgres by the view layer.
3. ``send:working_time`` is grouped by ``(job_id, user_id, KST calendar day)`` and a role
   is attached to each group. Week folding is **not** done here - Beacon owns the week
   axis, and baking a KST-Monday boundary into a fork query would mean reopening the fork
   every time that axis changes.
4. Frames are distributed pro-rata by an element's working seconds over the total working
   seconds *of the same role*. A combined denominator would make the review axis's
   per-image time meaningless. Consequence: the two roles' frame totals each sum to the
   job's frame count, so they must never be added together.
5. Whoever set ``state -> rejected`` is excluded from the non-assignee working-time total.
   Without that, a second reviewer who only rejected makes an ordinary job look
   attribution-suspect.

Everything else is carried over unchanged in spirit: the reviewer is whoever performed
``stage -> acceptance`` (falling back to the rejecter only on jobs that were never
accepted), round boundaries are the ``state``/``stage`` transitions, the first acceptance
terminates the rounds, and the in-flight final round is emitted with a null end rather
than being filled with "now".
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from typing import Any, NamedTuple, Protocol

from cvat.apps.events.const import WORKING_TIME_SCOPE

__all__ = [
    "ASSIGNEE_FIELD",
    "Query",
    "QueryExecutor",
    "REPORT_TIMEZONE",
    "REVIEWER_FROM_ACCEPTANCE",
    "REVIEWER_FROM_REJECTION",
    "ROLE_ANNOTATION",
    "ROLE_REVIEW",
    "STAGE_ACCEPTANCE",
    "STAGE_FIELD",
    "STATE_COMPLETED",
    "STATE_FIELD",
    "STATE_IN_PROGRESS",
    "STATE_REJECTED",
    "UPDATE_JOB_SCOPE",
    "WORKING_TIME_SCOPE",
    "default_executor",
    "ms_to_seconds",
    "resolve_reviewers",
    "to_utc_naive",
]

# Event scopes. WORKING_TIME_SCOPE is imported rather than duplicated so a rename in
# cvat.apps.events.const cannot silently desync this package.
UPDATE_JOB_SCOPE = "update:job"

# Every date key this package emits is a KST calendar day. This is the only calendar
# knowledge ImageLab has: days, never weeks (see divergence 3 above).
REPORT_TIMEZONE = "Asia/Seoul"

# `update:job` events carry the changed serializer field in obj_name and its new value
# in obj_val (see cvat.apps.events.handlers.handle_update).
STAGE_FIELD = "stage"
STATE_FIELD = "state"
ASSIGNEE_FIELD = "assignee"
STAGE_ACCEPTANCE = "acceptance"
STATE_IN_PROGRESS = "in progress"
STATE_COMPLETED = "completed"
STATE_REJECTED = "rejected"

# Roles a working-time group can carry.
ROLE_ANNOTATION = "annotation"
ROLE_REVIEW = "review"

# How the reviewer of a job was identified.
REVIEWER_FROM_ACCEPTANCE = "acceptance"
REVIEWER_FROM_REJECTION = "rejection"


class Query(NamedTuple):
    """A SQL string plus the values that must be bound to it server-side."""

    sql: str
    parameters: dict[str, Any]


class QueryExecutor(Protocol):
    """Runs one ClickHouse query and returns its rows as dicts keyed by column name."""

    def __call__(self, sql: str, parameters: Mapping[str, Any]) -> list[dict[str, Any]]: ...


def default_executor() -> QueryExecutor:
    """
    Return the real ClickHouse executor.

    Imported lazily on purpose: the SQL builders and row mappers in this package are pure
    functions and stay importable - and unit-testable - without the ClickHouse driver or a
    configured Django settings module.
    """
    from cvat.apps.production_stats.queries.clickhouse import run_query

    return run_query


def to_utc_naive(value: datetime) -> datetime:
    """
    Normalize a datetime before it is bound to a ``DateTime64`` parameter.

    ``clickhouse_connect.driver.query.format_bind_value()`` renders a datetime with
    ``strftime()`` and never converts it, so an aware value would send its *local* wall
    clock. Convert to UTC and drop the tzinfo so the wall clock we send is the UTC one.
    """
    if value.tzinfo is None:
        return value

    return value.astimezone(timezone.utc).replace(tzinfo=None)


def ms_to_seconds(milliseconds: Any) -> float:
    """
    Convert an event duration to seconds.

    ``duration`` on ``send:working_time`` is integer milliseconds
    (cvat.apps.events.handlers divides the working time by WORKING_TIME_RESOLUTION).
    Rounding to 3 decimals keeps full millisecond precision, so per-element values still
    sum to the job total.
    """
    return round(int(milliseconds or 0) / 1000, 3)


def resolve_reviewers(
    accepter_user_ids: Iterable[Any] | None,
    rejecter_user_ids: Iterable[Any] | None,
) -> tuple[list[int], str | None]:
    """
    Decide who reviewed a job.

    The primary evidence is acceptance. Treating any rejecter as a reviewer misattributed
    ~567 hours in the production dump, because an annotator who flipped their own job to
    ``rejected`` by mistake then had their whole annotation time counted as review time.
    The rejecter is used only on jobs that were never accepted (still in flight, or
    abandoned).
    """
    accepters = sorted({int(user_id) for user_id in accepter_user_ids or ()})
    if accepters:
        return accepters, REVIEWER_FROM_ACCEPTANCE

    rejecters = sorted({int(user_id) for user_id in rejecter_user_ids or ()})
    if rejecters:
        return rejecters, REVIEWER_FROM_REJECTION

    return [], None
