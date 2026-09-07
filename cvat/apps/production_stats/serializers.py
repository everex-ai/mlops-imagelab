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
