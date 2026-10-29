# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from django.contrib.auth.models import User
from django.db import models

from cvat.apps.engine.models import Job, JobSnapshotTrigger


class JobNotificationQuerySet(models.QuerySet):
    def active(self) -> JobNotificationQuerySet:
        """Not soft-deleted (R26)."""
        return self.filter(deleted_at__isnull=True)

    def unread(self) -> JobNotificationQuerySet:
        return self.filter(read_at__isnull=True)


class JobNotification(models.Model):
    """One job round boundary, delivered to one recipient (fan-out on write).

    The event kinds are the job snapshot round boundaries, so notifications,
    snapshots and job_rounds share one meaning of "round". The task name and
    job number are read live at query time, never copied here (R5).
    """

    recipient = models.ForeignKey(User, on_delete=models.CASCADE, related_name="job_notifications")
    job = models.ForeignKey(Job, on_delete=models.CASCADE, related_name="notifications")
    event = models.CharField(max_length=16, choices=JobSnapshotTrigger.choices)
    actor = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # The transition time of the boundary, not the row insert time.
    created_date = models.DateTimeField()
    read_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    objects = JobNotificationQuerySet.as_manager()

    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(
                fields=["recipient", "deleted_at", "read_at"], name="job_notif_unread_idx"
            ),
            models.Index(fields=["recipient", "-created_date"], name="job_notif_recent_idx"),
            models.Index(fields=["created_date"], name="job_notif_created_idx"),
        ]

    def __str__(self) -> str:
        return f"JobNotification({self.event}, job={self.job_id}, to={self.recipient_id})"
