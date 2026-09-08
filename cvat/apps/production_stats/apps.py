# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.apps import AppConfig


class ProductionStatsConfig(AppConfig):
    name = "cvat.apps.production_stats"
    verbose_name = "Production Stats"

    def ready(self) -> None:
        # Without this call the app's .rego files never make it into the OPA
        # bundle, and every request to this app is denied by an empty policy.
        from cvat.apps.iam.permissions import load_app_iam_rules

        load_app_iam_rules(self)
