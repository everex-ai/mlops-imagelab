# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.response import Response

from cvat.apps.engine.types import ExtendedRequest
from cvat.apps.production_stats.permissions import ProductionStatsPermission

# These view sets are deliberately excluded from the OpenAPI schema: CI
# regenerates cvat/schema.yml and diffs it against the checked-in copy, and
# these endpoints are consumed by Beacon rather than by the generated clients.


@extend_schema(exclude=True)
class JobFactsViewSet(viewsets.ViewSet):
    """
    Per-job production facts (working time split by date and role).

    U1 ships the routing and permission wiring only; the response body is a
    placeholder until the ClickHouse query layer lands.
    """

    serializer_class = None
    # Without this attribute PolicyEnforcer raises AssertionError, which surfaces
    # as HTTP 500 on every request instead of a permission decision.
    iam_permission_class = ProductionStatsPermission

    def list(self, request: ExtendedRequest) -> Response:
        # TODO(U3): return the real job fact rows.
        return Response({"count": 0, "results": []}, status=status.HTTP_200_OK)


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
