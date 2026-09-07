# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from django.contrib.auth.models import User
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.response import Response

from cvat.apps.engine.models import Job
from cvat.apps.engine.pagination import CustomPagination
from cvat.apps.engine.types import ExtendedRequest
from cvat.apps.production_stats.permissions import ProductionStatsPermission
from cvat.apps.production_stats.queries import freshness, job_facts
from cvat.apps.production_stats.queries.clickhouse import handle_clickhouse_exceptions
from cvat.apps.production_stats.serializers import (
    FreshnessSerializer,
    JobFactSerializer,
    JobFactsQuerySerializer,
)

# These view sets are deliberately excluded from the OpenAPI schema: CI
# regenerates cvat/schema.yml and diffs it against the checked-in copy, and
# these endpoints are consumed by Beacon rather than by the generated clients.


class SingleResponsePagination(CustomPagination):
    """
    Emits the whole result set as one page.

    Paginating this list would be actively harmful. The rows are assembled in Python on top
    of a ClickHouse aggregation that runs in full for every request, so DRF's default page
    size of 10 would re-run that aggregation once per page - 279 times over at the ~2,790
    jobs the production dump holds. Subclassing CustomPagination keeps the envelope
    identical to every other list in this API ("count"/"next"/"previous"/"results") and
    pins nothing but the page size.
    """

    def get_page_size(self, request: ExtendedRequest) -> int:
        # The branch CustomPagination takes for ?page_size=all, except that here it is not
        # negotiable by the client.
        return sys.maxsize


def _as_utc(value: datetime | None) -> datetime | None:
    """
    Normalise a ClickHouse timestamp before it is serialised.

    ClickHouse hands back UTC wall clocks, and whether the driver attaches a tzinfo depends
    on its version and settings. A naive value would be rendered by DRF with no offset at
    all, and Beacon would read it as a local time - a nine hour error in this deployment.
    """
    if value is None:
        return None

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def _fetch_jobs(job_ids: Sequence[int]) -> dict[int, Job]:
    """
    The Postgres half of a row.

    ``segment__task__data`` is not decoration: ``Segment.frame_count`` is a Python property
    that walks ``task.data`` (its start/stop frame and any ``step=`` frame filter), and it
    is the only correct frame count - ``stop_frame - start_frame + 1`` is wrong both for
    SPECIFIC_FRAMES segments and for any task carrying a frame step. Without the
    select_related the property would issue two extra queries per row.
    """
    queryset = Job.objects.select_related(
        "assignee", "segment__task__data", "segment__task__project"
    ).filter(id__in=list(job_ids))

    return {job.id: job for job in queryset}


def _resolve_usernames(
    jobs: Mapping[int, Job], facts: Mapping[int, Mapping[str, Any]]
) -> dict[int, str]:
    """
    Resolve every user id the response mentions in a single query.

    Reviewers, estimated workers and working-time entries arrive from ClickHouse as bare
    ``user_id`` integers (the source rounds query keyed on the event-time username snapshot,
    which orphaned a person's history the moment they were renamed). Looking each one up per
    row would mean thousands of queries per request. Assignees need no query at all -
    select_related has already fetched them.
    """
    resolved = {
        job.assignee_id: job.assignee.username
        for job in jobs.values()
        if job.assignee_id is not None
    }

    wanted: set[int] = set()
    for fact in facts.values():
        wanted.update(fact["reviewer_user_ids"])
        wanted.update(element["user_id"] for element in fact["days"])
        if fact["estimated_worker_user_id"] is not None:
            wanted.add(fact["estimated_worker_user_id"])

    wanted -= resolved.keys()
    if wanted:
        resolved.update(User.objects.filter(id__in=sorted(wanted)).values_list("id", "username"))

    return resolved


def _user_ref(user_id: int | None, usernames: Mapping[int, str]) -> dict[str, Any] | None:
    if user_id is None:
        return None

    return {"id": int(user_id), "username": usernames.get(int(user_id))}


def _build_row(
    job_id: int,
    job: Job | None,
    fact: Mapping[str, Any],
    usernames: Mapping[int, str],
) -> dict[str, Any]:
    """Merge one job's Postgres identity with its ClickHouse derived values."""
    task = job.segment.task if job is not None else None
    project = task.project if task is not None else None

    # The query layer left both of these to the caller on purpose: ClickHouse knows neither
    # the frame count nor who the assignee is.
    frame_count = job.segment.frame_count if job is not None else None
    assignee_id = job.assignee_id if job is not None else None

    reviewers = [_user_ref(user_id, usernames) for user_id in fact["reviewer_user_ids"]]

    return {
        "job_id": job_id,
        "deleted": job is None,
        "task_id": task.id if task is not None else None,
        "task_name": task.name if task is not None else None,
        "project_id": project.id if project is not None else None,
        "project_name": project.name if project is not None else None,
        "assignee": _user_ref(assignee_id, usernames),
        "stage": job.stage if job is not None else None,
        "state": job.state if job is not None else None,
        "frame_count": frame_count,
        "accepted_at": _as_utc(fact["accepted_at"]),
        "reviewer": reviewers[0] if reviewers else None,
        "reviewers": reviewers,
        "reviewer_source": fact["reviewer_source"],
        "days": job_facts.distribute_frames(fact["days"], frame_count),
        "estimated_worker": _user_ref(fact["estimated_worker_user_id"], usernames),
        "non_assignee_seconds": job_facts.non_assignee_seconds(fact, assignee_id),
        "assignee_changed_at": _as_utc(fact["assignee_changed_at"]),
    }


def _normalize_freshness(payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "scope": payload["scope"],
        "days": [
            {
                "date": day["date"],
                "events": day["events"],
                "last_seen": _as_utc(day["last_seen"]),
            }
            for day in payload["days"]
        ],
        "last_seen": _as_utc(payload["last_seen"]),
    }


def _user_directory(usernames: Mapping[int, str]) -> list[dict[str, Any]]:
    """
    Every account named anywhere in the response, resolved once.

    The day/role entries carry bare user ids, and Beacon's last-resort mapping for an
    account with no Worker record is to display the CVAT username as-is. Without this
    directory that fallback is impossible for anyone who is neither assignee nor reviewer.
    """
    return [{"id": user_id, "username": usernames[user_id]} for user_id in sorted(usernames)]


@extend_schema(exclude=True)
class JobFactsViewSet(viewsets.GenericViewSet):
    """
    Per-job production facts (working time split by KST day and role).

    The whole result set comes back in one response - see SingleResponsePagination.
    """

    serializer_class = JobFactSerializer
    pagination_class = SingleResponsePagination
    # Without this attribute PolicyEnforcer raises AssertionError, which surfaces
    # as HTTP 500 on every request instead of a permission decision.
    iam_permission_class = ProductionStatsPermission
    # ImageLab manages privileges with global Django groups only; there is no organization
    # axis for OrganizationFilterBackend to filter on.
    iam_organization_field = None

    def get_queryset(self):
        # Not a model view set: the rows are assembled in Python from a ClickHouse
        # aggregation plus one Postgres lookup. RequestViewSet does the same thing.
        return None

    @method_decorator(never_cache)
    @handle_clickhouse_exceptions
    def list(self, request: ExtendedRequest) -> Response:
        params = JobFactsQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        period_start = params.validated_data["period_start"]
        period_end = params.validated_data["period_end"]
        project_id = params.validated_data.get("project_id")

        # Stage 1 is the only query that sees the caller's period: it selects the job ids
        # whose acceptance OR whose activity falls inside the window.
        job_ids = job_facts.fetch_job_ids(
            period_start=period_start, period_end=period_end, project_id=project_id
        )

        jobs = _fetch_jobs(job_ids)

        # Stage 2's lower bound exists purely to prune partitions - `cvat.events` is ordered
        # by `timestamp` alone - and never changes the derived values, because neither a
        # transition nor a working-time event can predate the job's creation. Jobs whose
        # Postgres row is gone contribute no bound of their own; their history is clipped at
        # the oldest surviving job, which is acceptable because those rows are diagnostic.
        history_start = min(
            (job.created_date for job in jobs.values()),
            default=period_start,
        )

        facts = job_facts.fetch_job_facts(job_ids=job_ids, history_start=history_start)
        usernames = _resolve_usernames(jobs, facts)

        rows = [
            _build_row(job_id, jobs.get(job_id), facts[job_id], usernames) for job_id in job_ids
        ]

        collection_freshness = _normalize_freshness(
            freshness.fetch_freshness(
                period_start=period_start, period_end=period_end, project_id=project_id
            )
        )

        page = self.paginate_queryset(rows)
        response = self.get_paginated_response(self.get_serializer(page, many=True).data)

        response.data["period"] = {
            "start": period_start,
            "end": period_end,
            "project_id": project_id,
        }
        response.data["users"] = _user_directory(usernames)
        response.data["freshness"] = FreshnessSerializer(collection_freshness).data

        return response


@extend_schema(exclude=True)
class JobRoundsViewSet(viewsets.ViewSet):
    """
    Round-by-round breakdown of a single job's timeline.

    U1 ships the routing and permission wiring only; the response body is a
    placeholder until the ClickHouse query layer lands.
    """

    serializer_class = None
    iam_permission_class = ProductionStatsPermission
    lookup_value_regex = r"\d+"

    def retrieve(self, request: ExtendedRequest, pk: str) -> Response:
        # PolicyEnforcer.has_permission() returns True unconditionally for detail
        # routes and defers to has_object_permission(), which DRF only invokes
        # from check_object_permissions(). A non-model view set that never calls
        # it is therefore completely unguarded, so call it explicitly - the same
        # thing RequestViewSet.retrieve() does for its non-model detail route.
        # TODO(U4): pass the Job instance here once it is looked up (404 on miss).
        self.check_object_permissions(request, None)

        # TODO(U4): return the real rounds and the post-acceptance remainder.
        return Response(
            {"job_id": int(pk), "rounds": [], "trailing": None},
            status=status.HTTP_200_OK,
        )
