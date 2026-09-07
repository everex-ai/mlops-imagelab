# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""
Round decomposition for a single job, ported from §3b of
``docs/analytics/annotation-time-metrics.sql``.

The source query reads ``cvat.events`` five or six times for one job - once per CTE - and
the drilldown re-runs it every time somebody opens a job. Here the whole timeline is read
**once** and the boundary arithmetic happens in Python, which is both cheaper against a
table whose only sort key is ``timestamp`` and testable without a ClickHouse fixture.

Round boundaries, unchanged from §3b:

* ``state -> in progress`` opens an annotation round,
* ``state -> completed`` ends it and opens review,
* ``state -> rejected`` ends review and opens rework,
* the **first** ``stage -> acceptance`` terminates the job.

Transitions do not always alternate in real data (an assignee rejecting their own job, a
``completed -> in progress`` revert with no rejection, an ``acceptance -> annotation``
revert all occur in the dump), so termination is pinned to the first acceptance and
everything after it goes into the trailing bucket instead of inventing more rounds. The
final round of a job still in flight is emitted with a null end - filling it with "now"
would make two page loads disagree.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import Any

from cvat.apps.production_stats.queries import (
    ROLE_ANNOTATION,
    ROLE_REVIEW,
    STAGE_ACCEPTANCE,
    STAGE_FIELD,
    STATE_COMPLETED,
    STATE_FIELD,
    STATE_IN_PROGRESS,
    STATE_REJECTED,
    UPDATE_JOB_SCOPE,
    WORKING_TIME_SCOPE,
    Query,
    QueryExecutor,
    default_executor,
    ms_to_seconds,
    resolve_reviewers,
    to_utc_naive,
)

# The whole timeline of one job in a single scan. `cvat.events` is ordered by timestamp
# alone with no skipping index, so this predicate is what keeps the query off the full
# 11.7M-row table; the bound comes from Postgres Job.created_date, never from the user's
# reporting period.
JOB_TIMELINE_SCAN_SQL = """
SELECT
    timestamp,
    scope,
    obj_name,
    obj_val,
    user_id,
    duration
FROM events
WHERE timestamp >= {history_start:DateTime64}
  AND job_id = {job_id:UInt64}
  AND scope IN ('update:job', 'send:working_time')
ORDER BY timestamp
"""

# Mark kinds. The strings are also the dedup tie-break order: when several marks land on
# the same timestamp §3b keeps argMin(kind, kind), i.e. the lexicographically smallest,
# so 'done' beats 'review' beats 'rework' beats 'work'.
MARK_DONE = "done"
MARK_REVIEW = "review"
MARK_REWORK = "rework"
MARK_WORK = "work"

_TRANSITION_MARKS = {
    (STATE_FIELD, STATE_IN_PROGRESS): MARK_WORK,
    (STATE_FIELD, STATE_COMPLETED): MARK_REVIEW,
    (STATE_FIELD, STATE_REJECTED): MARK_REWORK,
    (STAGE_FIELD, STAGE_ACCEPTANCE): MARK_DONE,
}

_ANNOTATION_MARKS = (MARK_WORK, MARK_REWORK)


def build_job_timeline_scan(*, job_id: int, history_start: datetime) -> Query:
    """``history_start`` is the job's Postgres ``created_date``; it only prunes partitions."""
    return Query(
        JOB_TIMELINE_SCAN_SQL,
        {"job_id": int(job_id), "history_start": to_utc_naive(history_start)},
    )


def decompose_rounds(job_id: int, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Turn one job's raw timeline into rounds, a trailing bucket and job totals."""
    transitions = []
    working = []
    for row in rows:
        if row["scope"] == UPDATE_JOB_SCOPE:
            transitions.append(row)
        elif row["scope"] == WORKING_TIME_SCOPE:
            working.append(row)

    accepters = {
        int(row["user_id"])
        for row in transitions
        if row.get("user_id") is not None
        and row.get("obj_name") == STAGE_FIELD
        and row.get("obj_val") == STAGE_ACCEPTANCE
    }
    rejecters = {
        int(row["user_id"])
        for row in transitions
        if row.get("user_id") is not None
        and row.get("obj_name") == STATE_FIELD
        and row.get("obj_val") == STATE_REJECTED
    }
    reviewers, reviewer_source = resolve_reviewers(accepters, rejecters)
    reviewer_ids = set(reviewers)

    acceptance_times = [
        row["timestamp"]
        for row in transitions
        if row.get("obj_name") == STAGE_FIELD and row.get("obj_val") == STAGE_ACCEPTANCE
    ]
    accepted_at = min(acceptance_times) if acceptance_times else None

    phases = _build_phases(transitions, working, accepted_at)
    rounds = _group_rounds(phases, working, reviewer_ids)

    trailing = None
    if accepted_at is not None:
        after_acceptance = [row for row in working if row["timestamp"] >= accepted_at]
        worker_ms, reviewer_ms = _split_working_time(after_acceptance, reviewer_ids)
        trailing = {
            "started_at": accepted_at,
            "ended_at": None,
            "worker_seconds": ms_to_seconds(worker_ms),
            "reviewer_seconds": ms_to_seconds(reviewer_ms),
        }

    total_worker_ms, total_reviewer_ms = _split_working_time(working, reviewer_ids)

    return {
        "job_id": int(job_id),
        "reviewer_user_ids": reviewers,
        "reviewer_source": reviewer_source,
        "accepted_at": accepted_at,
        "rounds": rounds,
        "trailing": trailing,
        # Rounds plus trailing can be less than the totals (activity outside every phase),
        # so the totals are reported separately rather than being implied.
        "totals": {
            "worker_seconds": ms_to_seconds(total_worker_ms),
            "reviewer_seconds": ms_to_seconds(total_reviewer_ms),
        },
    }


def _build_phases(
    transitions: Sequence[Mapping[str, Any]],
    working: Sequence[Mapping[str, Any]],
    accepted_at: datetime | None,
) -> list[dict[str, Any]]:
    """Cut the timeline into phases at the transition marks, terminating at acceptance."""
    marks: dict[datetime, str] = {}

    def add(timestamp: datetime, kind: str) -> None:
        current = marks.get(timestamp)
        if current is None or kind < current:
            marks[timestamp] = kind

    has_start = False
    for row in transitions:
        kind = _TRANSITION_MARKS.get((row.get("obj_name"), row.get("obj_val")))
        if kind is None:
            continue
        if kind == MARK_WORK:
            has_start = True
        add(row["timestamp"], kind)

    # A job that never reached `in progress` has no rounds. That is a legitimate answer,
    # not an error - the view layer reports it as "never started", not as a failure.
    if not has_start:
        return []

    # §3b opens the first phase at the earliest sign of life rather than at the
    # `in progress` transition, so work done before the annotator flipped the state is not
    # silently dropped.
    openers = [row["timestamp"] for row in transitions]
    openers.extend(row["timestamp"] for row in working)
    add(min(openers), MARK_WORK)

    ordered = sorted(marks.items())

    # Termination is the FIRST acceptance. Marks after it are not rounds; the working time
    # after it is the trailing bucket.
    terminator = None
    kept = []
    for timestamp, kind in ordered:
        if kind == MARK_DONE:
            terminator = timestamp
            break
        kept.append((timestamp, kind))

    if accepted_at is not None and terminator is None:
        # Defensive: acceptance was recorded but its mark fell outside `kept`.
        terminator = accepted_at

    phases = []
    reviews_seen = 0
    for index, (timestamp, kind) in enumerate(kept):
        if kind == MARK_REVIEW:
            reviews_seen += 1

        if index + 1 < len(kept):
            end = kept[index + 1][0]
        else:
            end = terminator

        phases.append(
            {
                "kind": kind,
                "start": timestamp,
                # None means "still open". Never filled with now(): the numbers would
                # change between two page loads.
                "end": end if end is not None and end > timestamp else None,
                "round": reviews_seen + (1 if kind in _ANNOTATION_MARKS else 0),
                "is_annotation": kind in _ANNOTATION_MARKS,
            }
        )

    return phases


def _group_rounds(
    phases: Sequence[Mapping[str, Any]],
    working: Sequence[Mapping[str, Any]],
    reviewer_ids: set[int],
) -> list[dict[str, Any]]:
    """Collapse phases onto (round, role) pairs the way §3b's final GROUP BY does."""
    grouped: dict[tuple[int, bool], dict[str, Any]] = {}

    for phase in phases:
        key = (phase["round"], phase["is_annotation"])
        events = [
            row
            for row in working
            if row["timestamp"] >= phase["start"]
            and (phase["end"] is None or row["timestamp"] < phase["end"])
        ]
        worker_ms, reviewer_ms = _split_working_time(events, reviewer_ids)

        entry = grouped.get(key)
        if entry is None:
            grouped[key] = {
                "round": phase["round"],
                "phase": ROLE_ANNOTATION if phase["is_annotation"] else ROLE_REVIEW,
                "started_at": phase["start"],
                "ended_at": phase["end"],
                "worker_ms": worker_ms,
                "reviewer_ms": reviewer_ms,
            }
            continue

        entry["started_at"] = min(entry["started_at"], phase["start"])
        # The end of the LAST phase in the group, not max(): a still-open final phase must
        # keep its null end even when an earlier phase of the same round already closed.
        entry["ended_at"] = phase["end"]
        entry["worker_ms"] += worker_ms
        entry["reviewer_ms"] += reviewer_ms

    rounds = []
    # Annotation before review inside a round: annotation -> review -> rework -> re-review.
    ordered_keys = sorted(grouped, key=lambda key: (key[0], not key[1]))
    for key in ordered_keys:
        entry = grouped[key]
        rounds.append(
            {
                "round": entry["round"],
                "phase": entry["phase"],
                "started_at": entry["started_at"],
                "ended_at": entry["ended_at"],
                "worker_seconds": ms_to_seconds(entry["worker_ms"]),
                "reviewer_seconds": ms_to_seconds(entry["reviewer_ms"]),
            }
        )

    return rounds


def _split_working_time(
    events: Iterable[Mapping[str, Any]], reviewer_ids: set[int]
) -> tuple[int, int]:
    """
    Split working time into worker and reviewer milliseconds.

    §3b's caveat still applies: a 90-second batch can straddle a boundary, or somebody can
    genuinely open a job outside their phase, so a little time shows up on the other side.
    """
    worker_ms = 0
    reviewer_ms = 0
    for row in events:
        duration = int(row.get("duration") or 0)
        user_id = row.get("user_id")
        if user_id is not None and int(user_id) in reviewer_ids:
            reviewer_ms += duration
        else:
            worker_ms += duration

    return worker_ms, reviewer_ms


def fetch_job_rounds(
    *,
    job_id: int,
    history_start: datetime,
    execute: QueryExecutor | None = None,
) -> dict[str, Any]:
    """Read one job's timeline and decompose it. ``history_start`` is its ``created_date``."""
    execute = execute or default_executor()
    query = build_job_timeline_scan(job_id=job_id, history_start=history_start)

    return decompose_rounds(job_id, execute(query.sql, query.parameters))
