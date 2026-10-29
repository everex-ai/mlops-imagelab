# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.test import TestCase
from django.utils import timezone

from cvat.apps.notifications.models import JobNotification

from .helpers import make_job, make_user


def notify(recipient, job, event="rejected", **kwargs):
    kwargs.setdefault("created_date", timezone.now())
    return JobNotification.objects.create(recipient=recipient, job=job, event=event, **kwargs)


class JobNotificationModelTest(TestCase):
    def setUp(self):
        self.user = make_user("annotator", "worker")
        self.job = make_job(assignee=self.user)

    def test_active_excludes_soft_deleted_rows(self):
        kept = notify(self.user, self.job)
        notify(self.user, self.job, deleted_at=timezone.now())
        self.assertEqual(list(JobNotification.objects.active()), [kept])
        self.assertEqual(JobNotification.objects.count(), 2)

    def test_unread_excludes_read_rows(self):
        unread = notify(self.user, self.job)
        notify(self.user, self.job, read_at=timezone.now())
        self.assertEqual(list(JobNotification.objects.unread()), [unread])

    def test_job_delete_cascades(self):
        notify(self.user, self.job)
        self.job.delete()
        self.assertEqual(JobNotification.objects.count(), 0)

    def test_recipient_delete_cascades(self):
        notify(self.user, self.job)
        self.user.delete()
        self.assertEqual(JobNotification.objects.count(), 0)

    def test_actor_delete_keeps_the_notification(self):
        actor = make_user("reviewer", "reviewer")
        n = notify(self.user, self.job, actor=actor)
        actor.delete()
        n.refresh_from_db()
        self.assertIsNone(n.actor_id)
