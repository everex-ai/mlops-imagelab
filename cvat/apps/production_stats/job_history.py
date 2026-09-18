# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Read API over the job history ImageLab records for Beacon's job viewer:
round-boundary snapshots (engine.JobAnnotationSnapshot) and issues with their
comments, resolve/reopen history and issue snapshots.

Admin-only through ProductionStatsPermission, excluded from the OpenAPI schema
like the rest of production_stats.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from typing import Any

from django.db.migrations.recorder import MigrationRecorder
from django.db.models import Prefetch
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound
from rest_framework.response import Response

from cvat.apps.engine.models import (
    Comment,
    Issue,
    IssueAnnotationSnapshot,
    IssueResolutionChange,
    Job,
    JobAnnotationSnapshot,
    Label,
    Skeleton,
)
from cvat.apps.engine.types import ExtendedRequest
from cvat.apps.production_stats.permissions import ProductionStatsPermission

# A 24-keypoint skeleton frame is a few KB; 20 frames keeps a response small
# enough for a viewer that pages through frames.
MAX_SNAPSHOT_FRAMES = 20


def skeleton_edges(svg: str, sublabel_names_by_id: dict[int, str]) -> list[list[str]]:
    """A skeleton's edges as sublabel-name pairs.

    Parses the svg the CVAT skeleton editor stores, the same format
    dataset_manager.bindings reads: circles map node ids to sublabels, lines
    join node ids. Circles do not always carry data-label-name, so the label id
    is the fallback. Anything unreadable yields no edges rather than an error:
    the viewer still draws the points.
    """
    if not svg:
        return []
    try:
        root = ET.fromstring(f"<root>{svg}</root>")
    except ET.ParseError:
        return []

    names: dict[str, str] = {}
    for element in root:
        if element.tag != "circle":
            continue
        node = element.attrib.get("data-node-id")
        name = element.attrib.get("data-label-name")
        if name is None and element.attrib.get("data-label-id", "").isdigit():
            name = sublabel_names_by_id.get(int(element.attrib["data-label-id"]))
        if node is not None and name is not None:
            names[node] = name

    edges = []
    for element in root:
        if element.tag != "line":
            continue
        start = names.get(element.attrib.get("data-node-from", ""))
        end = names.get(element.attrib.get("data-node-to", ""))
        if start is not None and end is not None:
            edges.append([start, end])
    return edges


def _skeleton_svg(label: Label) -> str:
    try:
        return label.skeleton.svg or ""
    except Skeleton.DoesNotExist:
        return ""


def _job_labels(db_task) -> list[dict[str, Any]]:
    # A task in a project uses the project's labels, as everywhere else in CVAT.
    owner = {"project_id": db_task.project_id} if db_task.project_id else {"task_id": db_task.id}
    roots = (
        Label.objects.filter(parent__isnull=True, **owner)
        .select_related("skeleton")
        .prefetch_related(Prefetch("sublabels", queryset=Label.objects.order_by("id")))
        .order_by("id")
    )
    labels = []
    for label in roots:
        sublabels = list(label.sublabels.all())
        labels.append(
            {
                "id": label.id,
                "name": label.name,
                "type": label.type,
                "color": label.color,
                "sublabels": [
                    {"id": s.id, "name": s.name, "type": s.type, "color": s.color}
                    for s in sublabels
                ],
                "edges": skeleton_edges(_skeleton_svg(label), {s.id: s.name for s in sublabels}),
            }
        )
    return labels


def _visible_frames(db_job: Job) -> list[int]:
    """Task-relative frames the job shows: its segment minus deleted and excluded
    frames. Uses dataset_manager's own rule with an empty annotation set, so
    nothing is loaded but the frame metadata."""
    from cvat.apps.dataset_manager.annotation import AnnotationIR
    from cvat.apps.dataset_manager.bindings import JobData

    db_task = db_job.segment.task
    job_data = JobData(annotation_ir=AnnotationIR(db_task.dimension), db_job=db_job, host="")
    return sorted(job_data.get_included_frames())


_HISTORY_MIGRATIONS = {
    "snapshots": "0101_job_annotation_snapshot",
    "resolutions": "0102_issue_resolution_change",
}


def _history_since() -> dict[str, Any]:
    """When recording started: the time each history table's migration was applied.

    Not the first row's time: the first row is the first event after the start,
    so anything between the start and that event would read as "before
    recording" and a feedback's past resolution state as unknown."""
    applied = dict(
        MigrationRecorder.Migration.objects.filter(
            app="engine", name__in=_HISTORY_MIGRATIONS.values()
        ).values_list("name", "applied")
    )
    return {key: applied.get(name) for key, name in _HISTORY_MIGRATIONS.items()}


def _user_ref(user) -> dict[str, Any] | None:
    return None if user is None else {"id": user.id, "username": user.username}


class JobIdQuerySerializer(serializers.Serializer):
    job_id = serializers.IntegerField(min_value=1)


class FrameRangeQuerySerializer(serializers.Serializer):
    frame_from = serializers.IntegerField(min_value=0)
    frame_to = serializers.IntegerField(min_value=0)

    def validate(self, attrs):
        if attrs["frame_to"] < attrs["frame_from"]:
            raise serializers.ValidationError("frame_to must not be before frame_from")
        if attrs["frame_to"] - attrs["frame_from"] + 1 > MAX_SNAPSHOT_FRAMES:
            raise serializers.ValidationError(
                f"at most {MAX_SNAPSHOT_FRAMES} frames can be read at once"
            )
        return attrs


@extend_schema(exclude=True)
class JobSnapshotsViewSet(viewsets.ViewSet):
    iam_permission_class = ProductionStatsPermission
    iam_organization_field = None
    lookup_value_regex = r"\d+"

    @method_decorator(never_cache)
    def list(self, request: ExtendedRequest) -> Response:
        query = JobIdQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        job_id = query.validated_data["job_id"]
        snapshots = (
            JobAnnotationSnapshot.objects.filter(job_id=job_id)
            .select_related("actor")
            .order_by("transitioned_at", "id")
        )
        return Response(
            {
                "job_id": job_id,
                "snapshots": [
                    {
                        "id": s.id,
                        "trigger": s.trigger,
                        "from_stage": s.from_stage,
                        "from_state": s.from_state,
                        "to_stage": s.to_stage,
                        "to_state": s.to_state,
                        "actor": _user_ref(s.actor),
                        "transitioned_at": s.transitioned_at,
                        # pending: capture not finished (still pending long after
                        # transitioned_at means it was lost); failed: capture raised.
                        # Only captured snapshots have frames.
                        "status": s.status,
                        "captured_at": s.captured_at,
                        "frame_count": s.frame_count,
                    }
                    for s in snapshots
                ],
            }
        )

    @method_decorator(never_cache)
    def retrieve(self, request: ExtendedRequest, pk: str) -> Response:
        snapshot = JobAnnotationSnapshot.objects.filter(pk=int(pk)).select_related("job").first()
        # Permission before 404, as in JobRoundsViewSet: admin-only and
        # object-independent, so a 404 first would leak which ids exist. Checked
        # against the parent Job rather than the snapshot itself: PolicyEnforcer's
        # get_organization() resolves `obj.organization_id` to build iam_context,
        # and JobAnnotationSnapshot has no such property (it isn't an
        # organization-scoped model) - Job already implements it correctly.
        self.check_object_permissions(request, snapshot.job if snapshot else None)
        if snapshot is None:
            raise NotFound()

        query = FrameRangeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        frames = snapshot.frames.filter(
            frame__gte=query.validated_data["frame_from"],
            frame__lte=query.validated_data["frame_to"],
        ).order_by("frame")
        return Response(
            {
                "id": snapshot.id,
                "job_id": snapshot.job_id,
                "trigger": snapshot.trigger,
                "transitioned_at": snapshot.transitioned_at,
                "status": snapshot.status,
                "frames": [f.data for f in frames],
            }
        )


@extend_schema(exclude=True)
class JobIssuesViewSet(viewsets.ViewSet):
    iam_permission_class = ProductionStatsPermission
    iam_organization_field = None

    @method_decorator(never_cache)
    def list(self, request: ExtendedRequest) -> Response:
        query = JobIdQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        job_id = query.validated_data["job_id"]

        issues = (
            Issue.objects.filter(job_id=job_id)
            .select_related("owner")
            .prefetch_related(
                Prefetch(
                    "comments",
                    queryset=Comment.objects.select_related("owner").order_by("created_date", "id"),
                ),
                Prefetch(
                    "resolution_changes",
                    queryset=IssueResolutionChange.objects.select_related("actor"),
                ),
                Prefetch(
                    "annotation_snapshots",
                    queryset=IssueAnnotationSnapshot.objects.order_by("created_date", "id"),
                ),
            )
            .order_by("id")
        )
        return Response(
            {
                "job_id": job_id,
                "issues": [
                    {
                        "id": issue.id,
                        "frame": issue.frame,
                        "position": list(issue.position),
                        "resolved": issue.resolved,
                        "created_at": issue.created_date,
                        "owner": _user_ref(issue.owner),
                        "comments": [
                            {
                                "id": c.id,
                                "owner": _user_ref(c.owner),
                                "message": c.message,
                                "created_at": c.created_date,
                            }
                            for c in issue.comments.all()
                        ],
                        "resolution_changes": [
                            {
                                "id": r.id,
                                "resolved": r.resolved,
                                "actor": _user_ref(r.actor),
                                "changed_at": r.changed_at,
                            }
                            for r in issue.resolution_changes.all()
                        ],
                        "snapshots": [
                            {
                                # Raw string on purpose: a short-lived build stored
                                # `after`, which IssueSnapshotTrigger no longer lists.
                                "id": s.id,
                                "trigger": s.trigger,
                                "created_at": s.created_date,
                                "data": s.data,
                            }
                            for s in issue.annotation_snapshots.all()
                        ],
                    }
                    for issue in issues
                ],
            }
        )


@extend_schema(exclude=True)
class JobOutlineViewSet(viewsets.ViewSet):
    iam_permission_class = ProductionStatsPermission
    iam_organization_field = None
    lookup_value_regex = r"\d+"

    @method_decorator(never_cache)
    def retrieve(self, request: ExtendedRequest, pk: str) -> Response:
        db_job = (
            Job.objects.filter(pk=int(pk))
            .select_related("segment__task__project", "segment__task__data")
            .first()
        )
        # Permission before 404, as in JobSnapshotsViewSet.retrieve.
        self.check_object_permissions(request, db_job)
        if db_job is None:
            raise NotFound()

        db_task = db_job.segment.task
        return Response(
            {
                "job_id": db_job.id,
                "task_id": db_task.id,
                "task_name": db_task.name,
                "project_id": db_task.project_id,
                "project_name": db_task.project.name if db_task.project_id else None,
                "stage": db_job.stage,
                "state": db_job.state,
                "frames": _visible_frames(db_job),
                "labels": _job_labels(db_task),
                "history_since": _history_since(),
            }
        )
