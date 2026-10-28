# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING, Any

from django.conf import settings

from cvat.apps.iam.permissions import OpenPolicyAgentPermission, StrEnum

if TYPE_CHECKING:
    from rest_framework.viewsets import ViewSet

    from cvat.apps.engine.types import ExtendedRequest
    from cvat.apps.iam.permissions import IamContext


class JobNotificationPermission(OpenPolicyAgentPermission):
    """
    Every signed-in user reads and marks their own job notifications.

    The OPA package name ("notifications") must stay in sync with the last
    path segment of `self.url` and with the name of the .rego file under
    `rules/`; OPA resolves the policy by that path.
    """

    class Scopes(StrEnum):
        LIST = "list"
        UPDATE = "update"
        UPDATE_ALL = "update:all"

    @classmethod
    def create(
        cls,
        request: ExtendedRequest,
        view: ViewSet,
        obj: Any | None,
        iam_context: IamContext | None,
    ) -> Sequence[JobNotificationPermission]:
        return [
            cls.create_base_perm(request, view, scope, iam_context, obj)
            for scope in cls.get_scopes(request, view, obj)
        ]

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.url = settings.IAM_OPA_DATA_URL + "/notifications/allow"

    @classmethod
    def _get_scopes(cls, request: ExtendedRequest, view: ViewSet, obj: Any) -> list:
        Scopes = cls.Scopes
        return [
            {
                "list": Scopes.LIST,
                "summary": Scopes.LIST,
                "read": Scopes.UPDATE,
                "read_all": Scopes.UPDATE_ALL,
            }[view.action]
        ]

    def get_resource(self):
        if self.obj is None:
            return None
        return {"id": self.obj.id, "recipient": {"id": self.obj.recipient_id}}
