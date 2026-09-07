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


class ProductionStatsPermission(OpenPolicyAgentPermission):
    """
    Admin-only access to the production stats endpoints.

    The OPA package name ("production_stats") must stay in sync with the last
    path segment of `self.url` and with the name of the .rego file under
    `rules/`; OPA resolves the policy by that path.
    """

    class Scopes(StrEnum):
        LIST = "list"
        VIEW = "view"

    @classmethod
    def create(
        cls,
        request: ExtendedRequest,
        view: ViewSet,
        obj: Any | None,
        iam_context: IamContext | None,
    ) -> Sequence[ProductionStatsPermission]:
        permissions = []
        for scope in cls.get_scopes(request, view, obj):
            permissions.append(cls.create_base_perm(request, view, scope, iam_context, obj))

        return permissions

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.url = settings.IAM_OPA_DATA_URL + "/production_stats/allow"

    @classmethod
    def _get_scopes(cls, request: ExtendedRequest, view: ViewSet, obj: Any) -> list:
        Scopes = cls.Scopes
        return [
            {
                "list": Scopes.LIST,
                "retrieve": Scopes.VIEW,
            }[view.action]
        ]

    def get_resource(self):
        return None
