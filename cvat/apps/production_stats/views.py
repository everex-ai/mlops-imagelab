# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

import sys
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timezone
from typing import Any

from django.contrib.auth.models import User
from django.db.models import Count
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from cvat.apps.engine.models import Job, LabeledShape, LabeledTrack
from cvat.apps.engine.pagination import CustomPagination
from cvat.apps.engine.types import ExtendedRequest
from cvat.apps.production_stats.permissions import ProductionStatsPermission
from cvat.apps.production_stats.queries import freshness, job_facts, job_rounds
from cvat.apps.production_stats.queries.clickhouse import handle_clickhouse_exceptions
from cvat.apps.production_stats.serializers import (
    FreshnessSerializer,
    JobFactSerializer,
    JobFactsQuerySerializer,
    JobRoundsSerializer,
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


def _fetch_object_counts(job_ids: Sequence[int]) -> dict[int, int]:
    """
    How many annotated objects each job holds.

    The other Postgres half of a row, fetched the same way ``_fetch_jobs`` is: once for the
    whole id set, never per row.

    **Only top-level rows count.** A 24-keypoint skeleton is one object stored as a parent
    row plus 24 element rows pointing back at it (``LabeledShape.parent``), so counting
    every row would report 25 objects per person. ``parent__isnull=True`` keeps the
    elements out.

    Shapes and tracks are separate tables and a project uses one or the other, so both are
    counted and summed. Leaving tracks out would report zero for an interpolated project
    and read as "nothing was labelled" rather than "we did not look there".

    The type is deliberately not filtered. Every project in this deployment labels
    skeletons, so ``type='skeleton'`` and "every top-level shape" hold the same value
    today - and not filtering means a project that starts mixing in other shapes is
    counted rather than silently under-reported.
    """
    counts: dict[int, int] = {}

    for model in (LabeledShape, LabeledTrack):
        rows = (
            model.objects.filter(job_id__in=list(job_ids), parent__isnull=True)
            .values("job_id")
            .annotate(total=Count("id"))
        )
        for row in rows:
            counts[row["job_id"]] = counts.get(row["job_id"], 0) + row["total"]

    return counts


def _fetch_usernames(user_ids: Iterable[Any], resolved: dict[int, str]) -> dict[int, str]:
    """
    Fill in every username ``resolved`` is still missing, in a single query.

    Reviewers, estimated workers and working-time entries arrive from ClickHouse as bare
    ``user_id`` integers (the source rounds query keyed on the event-time username snapshot,
    which orphaned a person's history the moment they were renamed). Looking each one up per
    row would mean thousands of queries per request. Assignees need no query at all -
    select_related has already fetched them, so seeding ``resolved`` with them keeps them
    out of the ``IN`` list.
    """
    wanted = {int(user_id) for user_id in user_ids if user_id is not None} - resolved.keys()
    if wanted:
        resolved.update(User.objects.filter(id__in=sorted(wanted)).values_list("id", "username"))

    return resolved


def _resolve_usernames(
    jobs: Mapping[int, Job], facts: Mapping[int, Mapping[str, Any]]
) -> dict[int, str]:
    """Resolve every user id the job facts response mentions."""
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

    return _fetch_usernames(wanted, resolved)


def _user_ref(user_id: int | None, usernames: Mapping[int, str]) -> dict[str, Any] | None:
    if user_id is None:
        return None

    return {"id": int(user_id), "username": usernames.get(int(user_id))}


def _build_row(
    job_id: int,
    job: Job | None,
    fact: Mapping[str, Any],
    usernames: Mapping[int, str],
    object_counts: Mapping[int, int],
) -> dict[str, Any]:
    """Merge one job's Postgres identity with its ClickHouse derived values."""
    task = job.segment.task if job is not None else None
    project = task.project if task is not None else None

    # The query layer left both of these to the caller on purpose: ClickHouse knows neither
    # the frame count nor who the assignee is.
    frame_count = job.segment.frame_count if job is not None else None
    assignee_id = job.assignee_id if job is not None else None
    # `0` and `None` say different things: a job that exists and holds nothing was really
    # observed to be empty, while a job whose Postgres row is gone has nothing to count.
    # `frame_count` above draws the same line.
    object_count = object_counts.get(job_id, 0) if job is not None else None

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
        "object_count": object_count,
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
        object_counts = _fetch_object_counts(job_ids)

        # Stage 2's lower bound exists purely to prune partitions - `cvat.events` is ordered
        # by `timestamp` alone - and must never clip evidence. Including `period_start`
        # guarantees the bound is never later than the window stage 1 qualified these jobs
        # on: a job whose Postgres row is gone contributes no `created_date`, and without
        # that term a batch of jobs all created after `period_start` would push the bound
        # past that job's in-window acceptance and working time and drop them from stage 2
        # entirely. Every surviving `created_date` can only widen it further back, and per
        # fetch_job_facts() widening this bound changes performance, never results.
        history_start = min([period_start, *(job.created_date for job in jobs.values())])

        facts = job_facts.fetch_job_facts(
            job_ids=job_ids,
            history_start=history_start,
            # ClickHouse does not know who a job is assigned to, and the review axis is
            # defined relative to the assignee; `jobs` is already in memory.
            assignee_by_job={job_id: job.assignee_id for job_id, job in jobs.items()},
        )
        usernames = _resolve_usernames(jobs, facts)

        rows = [
            _build_row(job_id, jobs.get(job_id), facts[job_id], usernames, object_counts)
            for job_id in job_ids
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


def _segment_times(entry: Mapping[str, Any]) -> dict[str, Any]:
    """Normalise the two timestamps a round or the trailing bucket carries."""
    return {
        "started_at": _as_utc(entry["started_at"]),
        # Preserved as None when the segment is still open - see JobRoundSerializer.
        "ended_at": _as_utc(entry["ended_at"]),
        "worker_seconds": entry["worker_seconds"],
        "reviewer_seconds": entry["reviewer_seconds"],
    }


def _build_rounds_payload(
    job: Job, decomposition: Mapping[str, Any], usernames: Mapping[int, str]
) -> dict[str, Any]:
    """Merge one job's Postgres identity with its ClickHouse round decomposition."""
    task = job.segment.task
    project = task.project

    reviewers = [_user_ref(user_id, usernames) for user_id in decomposition["reviewer_user_ids"]]
    trailing = decomposition["trailing"]

    return {
        "job_id": job.id,
        "task_id": task.id,
        "task_name": task.name,
        "project_id": project.id if project is not None else None,
        "project_name": project.name if project is not None else None,
        "assignee": _user_ref(job.assignee_id, usernames),
        "stage": job.stage,
        "state": job.state,
        "accepted_at": _as_utc(decomposition["accepted_at"]),
        "reviewer": reviewers[0] if reviewers else None,
        "reviewers": reviewers,
        "reviewer_source": decomposition["reviewer_source"],
        "rounds": [
            {"round": entry["round"], "phase": entry["phase"], **_segment_times(entry)}
            for entry in decomposition["rounds"]
        ],
        "trailing": _segment_times(trailing) if trailing is not None else None,
        "totals": decomposition["totals"],
    }


@extend_schema(exclude=True)
class JobRoundsViewSet(viewsets.ViewSet):
    """
    Round-by-round breakdown of a single job's timeline.

    The drilldown opens this once per job, so the whole timeline is read in one scan (see
    queries/job_rounds.py) and folded in Python.
    """

    serializer_class = JobRoundsSerializer
    # Without this attribute PolicyEnforcer raises AssertionError, which surfaces
    # as HTTP 500 on every request instead of a permission decision.
    iam_permission_class = ProductionStatsPermission
    # ImageLab manages privileges with global Django groups only; there is no organization
    # axis for OrganizationFilterBackend to filter on.
    iam_organization_field = None
    lookup_value_regex = r"\d+"

    @method_decorator(never_cache)
    @handle_clickhouse_exceptions
    def retrieve(self, request: ExtendedRequest, pk: str) -> Response:
        # Postgres first. The row is needed four times over: as the object the permission
        # check is made against, as the identity half of the response, for `created_date` -
        # the lower bound that keeps the timeline scan off the full `cvat.events` table,
        # whose only sort key is `timestamp` - and for the assignee the review axis is
        # defined against.
        job = (
            Job.objects.select_related("assignee", "segment__task__project")
            .filter(id=int(pk))
            .first()
        )

        # PolicyEnforcer.has_permission() returns True unconditionally for detail
        # routes and defers to has_object_permission(), which DRF only invokes
        # from check_object_permissions(). A non-model view set that never calls
        # it is therefore completely unguarded, so call it explicitly - the same
        # thing RequestViewSet.retrieve() does for its non-model detail route.
        #
        # Deliberately *before* the 404, unlike RequestViewSet: this policy is admin-only
        # and object-independent, so answering 404 first would turn the route into an
        # existence oracle for job ids that any authenticated user could probe.
        self.check_object_permissions(request, job)

        if job is None:
            raise NotFound(f"There is no job with id {pk}")

        decomposition = job_rounds.fetch_job_rounds(
            job_id=job.id,
            history_start=job.created_date,
            # ClickHouse does not know who a job is assigned to, and the review axis is
            # defined relative to the assignee; the row is already in memory. The same
            # thread JobFactsViewSet.list() makes with `assignee_by_job`.
            assignee_user_id=job.assignee_id,
        )

        # The assignee is already in memory; only the reviewers cost a query, and only one
        # however many rounds the job went through.
        usernames: dict[int, str] = {}
        if job.assignee_id is not None:
            usernames[job.assignee_id] = job.assignee.username
        _fetch_usernames(decomposition["reviewer_user_ids"], usernames)

        payload = _build_rounds_payload(job, decomposition, usernames)

        return Response(JobRoundsSerializer(payload).data, status=status.HTTP_200_OK)
