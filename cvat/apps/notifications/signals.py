# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import logging

from django.dispatch import receiver

from cvat.apps.engine.job_snapshots import job_round_boundary

from .services import create_job_notifications

logger = logging.getLogger(__name__)


@receiver(job_round_boundary, dispatch_uid="notifications.create_job_notifications")
def notify_job_round_boundary(sender, *, job_id, trigger, actor_id, transitioned_at, **kwargs):
    """Runs on commit of the transition (R6), so a denied or rolled-back request
    never notifies anyone. Best-effort: failures are logged, never raised."""
    try:
        create_job_notifications(
            job_id=job_id, trigger=trigger, actor_id=actor_id, transitioned_at=transitioned_at
        )
    except Exception:  # noqa: BLE001 - notifications must never break a job transition
        logger.exception("Failed to create %s notifications for job %s", trigger, job_id)
