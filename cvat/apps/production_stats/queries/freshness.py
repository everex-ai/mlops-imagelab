# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""
Collection freshness for ``send:working_time``, ported from §6 of
``docs/analytics/annotation-time-metrics.sql``.

Two signals travel together, because either one alone is ambiguous:

* per-day event presence over the reporting window - a day with no events is a candidate
  "collection stopped" cell rather than a real zero, and
* the last time an event was seen at all - which tells a stalled pipeline (last seen weeks
  ago) apart from a quiet weekend.

Days are keyed by the KST calendar day, like every other date this package emits. Only
days that actually carry events are returned; the caller knows the window and decides what
an absent day means.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from cvat.apps.production_stats.queries import (
    WORKING_TIME_SCOPE,
    Query,
    QueryExecutor,
    default_executor,
    to_utc_naive,
)

DAILY_PRESENCE_SQL = """
SELECT
    toString(toDate(toTimeZone(timestamp, 'Asia/Seoul'))) AS day,
    count() AS events,
    max(timestamp) AS last_seen
FROM events
WHERE timestamp >= {period_start:DateTime64}
  AND timestamp < {period_end:DateTime64}
  AND scope = 'send:working_time'
"""

LAST_SEEN_SQL = """
SELECT
    max(timestamp) AS last_seen,
    count() AS events
FROM events
WHERE timestamp >= {since:DateTime64}
  AND scope = 'send:working_time'
"""

PROJECT_FILTER_SQL = "  AND project_id = {project_id:UInt64}\n"

DAILY_PRESENCE_GROUP_SQL = "GROUP BY day\nORDER BY day\n"


def build_daily_presence_scan(
    *,
    period_start: datetime,
    period_end: datetime,
    project_id: int | None = None,
) -> Query:
    sql = DAILY_PRESENCE_SQL
    parameters: dict[str, Any] = {
        "period_start": to_utc_naive(period_start),
        "period_end": to_utc_naive(period_end),
    }

    if project_id is not None:
        sql += PROJECT_FILTER_SQL
        parameters["project_id"] = int(project_id)

    return Query(sql + DAILY_PRESENCE_GROUP_SQL, parameters)


def build_last_seen_scan(*, since: datetime, project_id: int | None = None) -> Query:
    """
    ``since`` bounds the scan, so a pipeline that died before it reports no last_seen at
    all. Pass a bound that reaches back further than the reporting window if you want to
    tell "stalled a while ago" from "never collected".
    """
    sql = LAST_SEEN_SQL
    parameters: dict[str, Any] = {"since": to_utc_naive(since)}

    if project_id is not None:
        sql += PROJECT_FILTER_SQL
        parameters["project_id"] = int(project_id)

    return Query(sql, parameters)


def map_freshness(
    daily_rows: Iterable[Mapping[str, Any]],
    last_seen_rows: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    days = [
        {
            "date": str(row["day"]),
            "events": int(row.get("events") or 0),
            "last_seen": row.get("last_seen"),
        }
        for row in daily_rows
    ]

    # count() is what guards against ClickHouse's zero-row default for max() (1970-01-01)
    # being read back as a real timestamp when nothing matched at all.
    last_seen = None
    last_seen_row = next(iter(last_seen_rows), None)
    if last_seen_row is not None and int(last_seen_row.get("events") or 0):
        last_seen = last_seen_row.get("last_seen")

    return {"scope": WORKING_TIME_SCOPE, "days": days, "last_seen": last_seen}


def fetch_freshness(
    *,
    period_start: datetime,
    period_end: datetime,
    last_seen_since: datetime | None = None,
    project_id: int | None = None,
    execute: QueryExecutor | None = None,
) -> dict[str, Any]:
    execute = execute or default_executor()

    daily = build_daily_presence_scan(
        period_start=period_start, period_end=period_end, project_id=project_id
    )
    last_seen = build_last_seen_scan(
        since=last_seen_since if last_seen_since is not None else period_start,
        project_id=project_id,
    )

    return map_freshness(
        execute(daily.sql, daily.parameters),
        execute(last_seen.sql, last_seen.parameters),
    )
