# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.utils import timezone

from cvat.apps.notifications.cron import soft_delete_expired_job_notifications
from cvat.apps.notifications.models import JobNotification

from .helpers import make_job, make_user
from .test_models import notify


class SoftDeleteCronTest(TestCase):
    def setUp(self):
        self.user = make_user("annotator", "worker")
        self.job = make_job(assignee=self.user)

    def _aged(self, days, **kwargs):
        return notify(
            self.user, self.job, created_date=timezone.now() - timedelta(days=days), **kwargs
        )

    def test_old_notifications_are_soft_deleted_not_removed(self):
        # AE6
        old = self._aged(31)
        self.assertEqual(soft_delete_expired_job_notifications(), 1)
        old.refresh_from_db()
        self.assertIsNotNone(old.deleted_at)
        self.assertFalse(JobNotification.objects.active().exists())

    def test_read_state_does_not_matter(self):
        self._aged(31, read_at=timezone.now())
        self.assertEqual(soft_delete_expired_job_notifications(), 1)

    def test_recent_notifications_are_kept(self):
        recent = self._aged(29)
        self.assertEqual(soft_delete_expired_job_notifications(), 0)
        recent.refresh_from_db()
        self.assertIsNone(recent.deleted_at)

    def test_already_deleted_rows_keep_their_deletion_time(self):
        deleted_at = timezone.now() - timedelta(days=5)
        row = self._aged(40, deleted_at=deleted_at)
        self.assertEqual(soft_delete_expired_job_notifications(), 0)
        row.refresh_from_db()
        self.assertEqual(row.deleted_at, deleted_at)

    def test_processes_in_chunks(self):
        for _ in range(5):
            self._aged(31)
        self.assertEqual(soft_delete_expired_job_notifications(chunk_size=2), 5)
        self.assertFalse(JobNotification.objects.active().exists())

    def test_registered_as_a_daily_cleaning_job(self):
        job = next(
            j
            for j in settings.PERIODIC_RQ_JOBS
            if j["id"] == "soft_delete_expired_job_notifications"
        )
        self.assertEqual(job["queue"], settings.CVAT_QUEUES.CLEANING.value)
        self.assertEqual(
            job["func"], "cvat.apps.notifications.cron.soft_delete_expired_job_notifications"
        )
