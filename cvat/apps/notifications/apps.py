# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.apps import AppConfig


class NotificationsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "cvat.apps.notifications"
    verbose_name = "Job Notifications"

    def ready(self) -> None:
        from django.conf import settings

        from . import default_settings

        for key in dir(default_settings):
            if key.isupper() and not hasattr(settings, key):
                setattr(settings, key, getattr(default_settings, key))

        # Connects the job_round_boundary receiver.
        # Without this call the app's .rego files never make it into the OPA
        # bundle, and every request to this app is denied by an empty policy.
        from cvat.apps.iam.permissions import load_app_iam_rules

        from . import signals  # noqa: F401

        load_app_iam_rules(self)
