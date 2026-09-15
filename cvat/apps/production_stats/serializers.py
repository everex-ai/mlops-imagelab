# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""
Request and response contracts for the production stats endpoints.

These endpoints are excluded from the generated OpenAPI schema (see views.py), so there is
no generated client keeping Beacon and ImageLab in sync. The row shape is therefore
declared here explicitly rather than being whatever a dict comprehension happened to
build - this module is the contract Beacon asserts against at runtime.
"""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from rest_framework import serializers

from cvat.apps.production_stats.queries import ROLE_ANNOTATION, ROLE_REVIEW

# The reporting period is the only unbounded input these endpoints take, and the query
# behind it is heavy: stage 1 scans `cvat.events`, whose only sort key is `timestamp`, over
# the whole window. Without a server-side cap the UI default (four weeks) would be the sole
# bound, and any caller could ask for 1970-2100 in one request.
#
# 366 days is one full calendar year including a leap day: it covers the widest window that
# still makes sense as a weekly heatmap (53 columns) while keeping the scan to at most 13
# monthly partitions. The plan defers the production-tuned number to a measurement against
# real data, so this is deliberately a single constant to change.
MAX_PERIOD = timedelta(days=366)


class JobFactsQuerySerializer(serializers.Serializer):
    """Query parameters accepted by the job facts list route."""

    period_start = serializers.DateTimeField(
        help_text="Inclusive lower bound of the reporting window."
    )
    period_end = serializers.DateTimeField(
        help_text="Exclusive upper bound of the reporting window."
    )
    # Optional on purpose: the screen's default filter is "all projects", so the unfiltered
    # path is the one users take on first load.
    project_id = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        period_start = attrs["period_start"]
        period_end = attrs["period_end"]

        if period_end <= period_start:
            raise serializers.ValidationError("period_end must be later than period_start")

        if period_end - period_start > MAX_PERIOD:
            raise serializers.ValidationError(
                f"The reporting period must not exceed {MAX_PERIOD.days} days"
            )

        return attrs


class UserRefSerializer(serializers.Serializer):
    """A CVAT account. Beacon matches on the numeric id first and the username second."""

    id = serializers.IntegerField()
    # None when the auth_user row is gone but the events referencing it are not.
    username = serializers.CharField(allow_null=True)


class WorkingTimeEntrySerializer(serializers.Serializer):
    """One (KST day, person, role) slice of a job's working time."""

    date = serializers.CharField(help_text="KST calendar day, YYYY-MM-DD.")
    user_id = serializers.IntegerField()
    role = serializers.ChoiceField(choices=[ROLE_ANNOTATION, ROLE_REVIEW])
    seconds = serializers.FloatField()
    # Pro-rata share of the job's frame count within the same role; null when the frame
    # count is unknown because the Postgres row is gone. The two roles' shares each sum to
    # the job's frame count, so they must never be added together.
    frames = serializers.FloatField(allow_null=True)


class JobFactSerializer(serializers.Serializer):
    """One job row: Postgres identity merged with the ClickHouse derived values."""

    job_id = serializers.IntegerField()
    # True for a job ClickHouse still remembers but Postgres no longer has. Tasks and
    # projects hard delete via CASCADE while `cvat.events` has no TTL, so this set only
    # grows. Such rows count towards the approved job total and are excluded from worker
    # attribution; dropping them would poison the gap between those two numbers, which is
    # Beacon's only signal that attribution is missing.
    deleted = serializers.BooleanField()

    task_id = serializers.IntegerField(allow_null=True)
    task_name = serializers.CharField(allow_null=True)
    project_id = serializers.IntegerField(allow_null=True)
    project_name = serializers.CharField(allow_null=True)

    assignee = UserRefSerializer(allow_null=True)
    stage = serializers.CharField(allow_null=True)
    state = serializers.CharField(allow_null=True)
    # Segment.frame_count, never stop_frame - start_frame + 1. Null on a deleted job.
    frame_count = serializers.IntegerField(allow_null=True)
    # Top-level annotated objects in the job: shapes and tracks whose `parent` is null, so
    # a 24-keypoint skeleton counts once rather than 25 times. `0` means the job really is
    # empty; null means its Postgres row is gone, the same split `frame_count` draws.
    object_count = serializers.IntegerField(allow_null=True)
    # Null on a job that has never reached the acceptance stage. Such jobs stay in the
    # list; the union window selects them on activity alone.
    accepted_at = serializers.DateTimeField(allow_null=True)

    # The person who accepted the job; on a job that was never accepted, whoever rejected
    # it. `reviewers` carries every one of them - a job can be rejected by one person and
    # accepted by another - and `reviewer` is the first of that list for the common case.
    reviewer = UserRefSerializer(allow_null=True)
    reviewers = UserRefSerializer(many=True)
    reviewer_source = serializers.CharField(allow_null=True)

    days = WorkingTimeEntrySerializer(many=True)

    # Attribution cross-check. Beacon flags a job when the event-based guess at who worked
    # on it disagrees with the assignee, when time was booked by somebody who is neither
    # the assignee nor a reviewer nor a rejecter, or when the assignee changed mid-flight.
    estimated_worker = UserRefSerializer(allow_null=True)
    non_assignee_seconds = serializers.FloatField()
    assignee_changed_at = serializers.DateTimeField(allow_null=True)


class FreshnessDaySerializer(serializers.Serializer):
    date = serializers.CharField(help_text="KST calendar day, YYYY-MM-DD.")
    events = serializers.IntegerField()
    last_seen = serializers.DateTimeField(allow_null=True)


class FreshnessSerializer(serializers.Serializer):
    """
    Whether the working-time collection pipeline is alive.

    Only days that carry events are listed; the caller knows the window and decides what an
    absent day means. Without this, Beacon cannot tell a real zero from a dead collector.
    """

    scope = serializers.CharField()
    days = FreshnessDaySerializer(many=True)
    last_seen = serializers.DateTimeField(allow_null=True)


class JobRoundSerializer(serializers.Serializer):
    """
    One (round, role) segment of a job's timeline.

    A round is a pass over the job: round 1 is the first annotation and the review that
    followed it, round 2 is the rework a rejection triggered and its re-review, and so on.
    Each round therefore appears twice - once as `annotation`, once as `review` - so a job
    that was rejected once comes back as four entries.
    """

    round = serializers.IntegerField(min_value=1)
    phase = serializers.ChoiceField(choices=[ROLE_ANNOTATION, ROLE_REVIEW])
    started_at = serializers.DateTimeField()
    # Null while the segment is still open. Never filled with the time of the request:
    # doing so would make two page loads of the same drilldown disagree.
    ended_at = serializers.DateTimeField(allow_null=True)
    # Split by whoever booked the time: reviewers (identified by acceptance, or by
    # rejection on a job that was never accepted) on one side, everybody else on the
    # other. A ~90s working-time batch can straddle a boundary, so a little time leaks
    # into the neighbouring segment - the screen says so (R37).
    worker_seconds = serializers.FloatField()
    reviewer_seconds = serializers.FloatField()


class TrailingActivitySerializer(serializers.Serializer):
    """
    Working time recorded after the job was first accepted.

    Rounds terminate at the *first* `stage -> acceptance`; three jobs in the production
    dump were then reverted to `annotation` and worked on again. That activity is real but
    belongs to no round, so it is surfaced here instead of being folded into one - which
    is also the answer to "why do the round times not add up to the job total?".
    """

    started_at = serializers.DateTimeField()
    # Always null: the trailing bucket is open-ended by construction.
    ended_at = serializers.DateTimeField(allow_null=True)
    worker_seconds = serializers.FloatField()
    reviewer_seconds = serializers.FloatField()


class JobTotalsSerializer(serializers.Serializer):
    """
    The job's whole working time, reported separately rather than implied.

    Rounds plus trailing can be *less* than these totals: time booked before the first
    transition of a job that never reached `in progress` sits outside every segment.
    """

    worker_seconds = serializers.FloatField()
    reviewer_seconds = serializers.FloatField()


class JobRoundsSerializer(serializers.Serializer):
    """One job's round decomposition. The identity block mirrors JobFactSerializer."""

    job_id = serializers.IntegerField()

    task_id = serializers.IntegerField()
    task_name = serializers.CharField()
    project_id = serializers.IntegerField(allow_null=True)
    project_name = serializers.CharField(allow_null=True)

    assignee = UserRefSerializer(allow_null=True)
    stage = serializers.CharField()
    state = serializers.CharField()
    # Null on a job that has never reached the acceptance stage; the rounds then end with
    # an open segment rather than with a terminator.
    accepted_at = serializers.DateTimeField(allow_null=True)

    reviewer = UserRefSerializer(allow_null=True)
    reviewers = UserRefSerializer(many=True)
    reviewer_source = serializers.CharField(allow_null=True)

    # Empty for a job that never reached `state -> in progress`. That is a legitimate 200,
    # not a failure: the screen renders it as "no work recorded" (R33), which it can only
    # do if an empty list is distinguishable from a failed lookup.
    rounds = JobRoundSerializer(many=True)
    # Null when the job was never accepted, so there is no "after acceptance" yet.
    trailing = TrailingActivitySerializer(allow_null=True)
    totals = JobTotalsSerializer()


class ObjectCountsQuerySerializer(serializers.Serializer):
    """
    Query parameters accepted by the object counts list route.

    **No period.** Unlike the job facts route, nothing here reads `cvat.events`, so there
    is no scan to bound and no window to declare. That absence is the whole point of the
    endpoint: annotation rows live in Postgres and survive regardless of how far back the
    event log still reaches, so a project whose labelling finished before the log's horizon
    still has a real, countable object total.
    """

    # Optional for the same reason job facts makes it optional, and because the unfiltered
    # call is the cheap one here: the aggregate is grouped in Postgres either way, so
    # fetching every project costs the same three statements as fetching one.
    project_id = serializers.IntegerField(required=False, min_value=1)


class ProjectObjectCountSerializer(serializers.Serializer):
    """How many annotated objects a project holds, and over how many jobs."""

    project_id = serializers.IntegerField()

    # Top-level rows only, shapes and tracks summed - the same rule `object_count` follows
    # on a job facts row, so the two are directly comparable for a project whose work is
    # still inside the event log's horizon.
    total_objects = serializers.IntegerField()

    # Every job the project holds, annotated or not.
    job_count = serializers.IntegerField()

    # The jobs that actually carry at least one object. Beacon divides by this rather than
    # by `job_count` to answer "how heavy is a job here": a project half of whose jobs are
    # not started yet would otherwise report a difficulty diluted by the untouched half.
    jobs_with_objects = serializers.IntegerField()
