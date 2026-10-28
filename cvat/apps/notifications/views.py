# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.conf import settings
from django.db.models import Max
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from cvat.apps.engine.types import ExtendedRequest

from .permissions import JobNotificationPermission
from .serializers import JobNotificationListQuerySerializer, JobNotificationSerializer
from .services import visible_notifications, with_target_frame


# Excluded from the OpenAPI schema like production_stats: cvat-core calls these
# directly, and CI diffs a regenerated cvat/schema.yml against the checked-in copy.
@extend_schema(exclude=True)
@method_decorator(never_cache, name="dispatch")
class JobNotificationViewSet(viewsets.GenericViewSet):
    """The requesting user's job notifications (INNO-123).

    Always scoped to `request.user`, whatever the X-Organization context, so
    switching organizations never changes the badge.
    """

    serializer_class = JobNotificationSerializer
    iam_permission_class = JobNotificationPermission
    iam_organization_field = None
    filter_backends = []
    pagination_class = None

    def get_queryset(self):
        return visible_notifications(self.request.user)

    def list(self, request: ExtendedRequest) -> Response:
        params = JobNotificationListQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        qs = self.get_queryset()
        if params.validated_data["unread_only"]:
            qs = qs.unread()
        qs = with_target_frame(
            qs.select_related("actor", "job__segment__task").order_by("-created_date", "-id")
        )[: settings.JOB_NOTIFICATION_LIST_LIMIT]

        return Response(self.get_serializer(qs, many=True).data)

    @action(detail=False, methods=["GET"])
    def summary(self, request: ExtendedRequest) -> Response:
        qs = self.get_queryset()
        return Response(
            {
                "unread_count": qs.unread().count(),
                "latest_id": qs.aggregate(latest_id=Max("id"))["latest_id"],
            }
        )

    @action(detail=True, methods=["POST"])
    def read(self, request: ExtendedRequest, pk=None) -> Response:
        # get_object() 404s for someone else's or a hidden notification (R19).
        notification = self.get_object()
        if notification.read_at is None:
            notification.read_at = timezone.now()
            notification.save(update_fields=["read_at"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["POST"])
    def read_all(self, request: ExtendedRequest) -> Response:
        self.get_queryset().unread().update(read_at=timezone.now())
        return Response(status=status.HTTP_204_NO_CONTENT)
