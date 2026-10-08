# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""
Per-person, per-KST-day activity span: when someone's first and last client event of the
day happened.

Beacon uses the span to tell a half-day leave apart from a full working day. Working-time
totals alone cannot do that - a short day might be a half-day, a meeting-heavy day or a
collection gap - but *when* the activity stops or starts can: a person who stops at 13:00
with nothing after it left for the afternoon. The judgement itself lives in Beacon; this
module only reports the facts.

Only client events count: they are what a person's hands produce in the annotation UI.
``debug:info`` and ``send:exception`` are excluded because they fire without a person
acting, and server-side scopes (``send:working_time`` included) are excluded by the source
filter because they are emitted when the client flushes, not when the person works.

Events before 06:00 KST are ignored. A lone event at 01:28 - a tab left open overnight
replaying a flush - would otherwise drag the day's first activity to the middle of the
night and make a normal day look like a late start.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from cvat.apps.production_stats.queries import (
    REPORT_TIMEZONE,
    Query,
    QueryExecutor,
    default_executor,
    to_utc_naive,
)

# Earliest KST hour whose events count toward a day's span.
DAY_START_HOUR = 6

# Client scopes that are not a person acting.
EXCLUDED_CLIENT_SCOPES = ("debug:info", "send:exception")

USER_DAY_ACTIVITY_SQL = f"""
SELECT
    user_id,
    toString(toDate(toTimeZone(timestamp, '{REPORT_TIMEZONE}'))) AS day,
    formatDateTime(min(toTimeZone(timestamp, '{REPORT_TIMEZONE}')), '%H:%i') AS first_at,
    formatDateTime(max(toTimeZone(timestamp, '{REPORT_TIMEZONE}')), '%H:%i') AS last_at,
    count() AS events
FROM events
WHERE timestamp >= {{period_start:DateTime64}}
  AND timestamp < {{period_end:DateTime64}}
  AND source = 'client'
  AND scope NOT IN {EXCLUDED_CLIENT_SCOPES!r}
  AND user_id IS NOT NULL
  AND toHour(toTimeZone(timestamp, '{REPORT_TIMEZONE}')) >= {DAY_START_HOUR}
GROUP BY user_id, day
ORDER BY user_id, day
"""


def build_user_day_activity_scan(*, period_start: datetime, period_end: datetime) -> Query:
    return Query(
        USER_DAY_ACTIVITY_SQL,
        {
            "period_start": to_utc_naive(period_start),
            "period_end": to_utc_naive(period_end),
        },
    )


def map_user_day_activity(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "user_id": int(row["user_id"]),
            "date": str(row["day"]),
            "first_at": str(row["first_at"]),
            "last_at": str(row["last_at"]),
            "events": int(row.get("events") or 0),
        }
        for row in rows
    ]


def fetch_user_day_activity(
    *,
    period_start: datetime,
    period_end: datetime,
    execute: QueryExecutor | None = None,
) -> list[dict[str, Any]]:
    execute = execute or default_executor()
    scan = build_user_day_activity_scan(period_start=period_start, period_end=period_end)
    return map_user_day_activity(execute(scan.sql, scan.parameters))
