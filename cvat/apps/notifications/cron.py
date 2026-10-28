# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.conf import settings
from django.utils import timezone

from cvat.apps.dataset_manager.util import current_function_name
from cvat.apps.engine.log import ServerLogManager

from .models import JobNotification


def soft_delete_expired_job_notifications(*, chunk_size: int = 1000) -> int:
    """Hide notifications older than the retention period (R26). Rows are kept:
    hard purge is deferred follow-up work."""
    now = timezone.now()
    expired = JobNotification.objects.filter(
        deleted_at__isnull=True,
        created_date__lt=now - settings.JOB_NOTIFICATION_RETENTION,
    )

    total = 0
    while True:
        ids = list(expired.values_list("pk", flat=True)[:chunk_size])
        if not ids:
            break
        total += JobNotification.objects.filter(pk__in=ids).update(deleted_at=now)

    slogger = ServerLogManager(__name__ + "." + current_function_name())
    slogger.glob.info(f"Soft-deleted expired job notifications: {total}")
    return total
