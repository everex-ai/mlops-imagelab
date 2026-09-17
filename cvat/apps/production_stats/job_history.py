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

from typing import Any

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
    JobAnnotationSnapshot,
)
from cvat.apps.engine.types import ExtendedRequest
from cvat.apps.production_stats.permissions import ProductionStatsPermission

# A 24-keypoint skeleton frame is a few KB; 20 frames keeps a response small
# enough for a viewer that pages through frames.
MAX_SNAPSHOT_FRAMES = 20


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
                        "captured_at": s.created_date,
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
