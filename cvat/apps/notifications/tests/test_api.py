# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""The header bell's API (U3). These tests talk to a real OPA instance, which must
have this app's notifications.rego in its bundle."""

from datetime import timedelta

from django.contrib.auth.models import Group
from django.utils import timezone
from rest_framework import status

from cvat.apps.engine import models
from cvat.apps.engine.tests.utils import ApiTestBase, ForceLogin
from cvat.apps.notifications.models import JobNotification
from cvat.apps.organizations.models import Membership

from .helpers import add_member, make_job, make_org, make_user
from .test_models import notify

LIST = "/api/notifications"
SUMMARY = "/api/notifications/summary"
READ_ALL = "/api/notifications/read_all"


def read_url(notification_id):
    return f"/api/notifications/{notification_id}/read"


class JobNotificationApiTest(ApiTestBase):
    def setUp(self):
        super().setUp()
        self.annotator = make_user("annotator", "worker")
        self.other = make_user("other", "worker")
        self.reviewer = make_user("reviewer", "reviewer")
        self.job = make_job(assignee=self.annotator, state="rejected")

    def _get(self, path, user, **params):
        response = self._get_request(path, user, query_params=params or None)
        self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
        return response.json()

    def _ids(self, user, **params):
        return [n["id"] for n in self._get(LIST, user, **params)]

    def test_list_is_own_newest_first(self):
        now = timezone.now()
        older = notify(self.annotator, self.job, created_date=now - timedelta(hours=1))
        newer = notify(self.annotator, self.job, created_date=now)
        notify(self.other, make_job(assignee=self.other))
        self.assertEqual(self._ids(self.annotator), [newer.id, older.id])

    def test_list_item_shape(self):
        n = notify(self.annotator, self.job, actor=self.reviewer)
        [item] = self._get(LIST, self.annotator)
        self.assertEqual(
            {k: item[k] for k in ("id", "event", "is_read", "job_id", "task_id", "task_name")},
            {
                "id": n.id,
                "event": "rejected",
                "is_read": False,
                "job_id": self.job.id,
                "task_id": self.job.segment.task_id,
                "task_name": self.job.segment.task.name,
            },
        )
        self.assertEqual(item["actor"]["username"], "reviewer")

    def test_unread_only_and_read_and_summary(self):
        # AE5
        a = notify(self.annotator, self.job)
        b = notify(self.annotator, self.job)
        self.assertEqual(self._get(SUMMARY, self.annotator), {"unread_count": 2, "latest_id": b.id})

        response = self._post_request(read_url(a.id), self.annotator)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        self.assertEqual(self._ids(self.annotator, unread_only="true"), [b.id])
        self.assertEqual(self._get(SUMMARY, self.annotator)["unread_count"], 1)

    def test_read_is_idempotent(self):
        n = notify(self.annotator, self.job)
        self._post_request(read_url(n.id), self.annotator)
        n.refresh_from_db()
        first = n.read_at
        response = self._post_request(read_url(n.id), self.annotator)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        n.refresh_from_db()
        self.assertEqual(n.read_at, first)

    def test_read_all_touches_only_own_notifications(self):
        notify(self.annotator, self.job)
        notify(self.annotator, self.job)
        theirs = notify(self.other, make_job(assignee=self.other))
        response = self._post_request(READ_ALL, self.annotator)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self._get(SUMMARY, self.annotator)["unread_count"], 0)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)

    def test_someone_elses_notification_is_404(self):
        theirs = notify(self.other, make_job(assignee=self.other))
        response = self._post_request(read_url(theirs.id), self.annotator)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        theirs.refresh_from_db()
        self.assertIsNone(theirs.read_at)

    def test_global_reviewer_can_use_the_api(self):
        n = notify(self.reviewer, self.job, event="submitted")
        self.assertEqual(self._ids(self.reviewer), [n.id])
        response = self._post_request(read_url(n.id), self.reviewer)
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(self._post_request(READ_ALL, self.reviewer).status_code, 204)

    def test_org_reviewer_can_use_the_api_in_org_context(self):
        org = make_org("org", make_user("owner", "user"))
        org_reviewer = make_user("org_reviewer", "worker")
        add_member(org, org_reviewer, Membership.REVIEWER)
        job = make_job(assignee=self.annotator, org=org)
        n = notify(org_reviewer, job, event="submitted")

        with ForceLogin(org_reviewer, self.client):
            response = self.client.get(LIST, HTTP_X_ORGANIZATION=org.slug)
            self.assertEqual([i["id"] for i in response.json()], [n.id])
            response = self.client.post(read_url(n.id), HTTP_X_ORGANIZATION=org.slug)
            self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
            # The organization context does not narrow the list.
            response = self.client.get(LIST)
            self.assertEqual([i["id"] for i in response.json()], [n.id])

    def test_target_frame_is_the_first_open_issue_for_rejections(self):
        # AE3
        n = notify(self.annotator, self.job)
        for frame in (4, 1):
            models.Issue.objects.create(job=self.job, frame=frame, position=[0.0, 0.0, 1.0, 1.0])
        models.Issue.objects.create(
            job=self.job, frame=0, position=[0.0, 0.0, 1.0, 1.0], resolved=True
        )
        self.assertEqual(self._get(LIST, self.annotator)[0]["target_frame"], 1)

        models.Issue.objects.filter(job=self.job).update(resolved=True)
        start = self.job.segment.start_frame
        [item] = self._get(LIST, self.annotator)
        self.assertEqual((item["id"], item["target_frame"]), (n.id, start))

    def test_target_frame_is_the_job_start_for_other_events(self):
        models.Segment.objects.filter(pk=self.job.segment_id).update(start_frame=3)
        models.Issue.objects.create(job=self.job, frame=4, position=[0.0, 0.0, 1.0, 1.0])
        models.Job.objects.filter(pk=self.job.pk).update(stage="acceptance")
        notify(self.annotator, self.job, event="accepted")
        self.assertEqual(self._get(LIST, self.annotator)[0]["target_frame"], 3)

    def test_soft_deleted_notifications_are_hidden(self):
        notify(self.annotator, self.job, deleted_at=timezone.now())
        self.assertEqual(self._ids(self.annotator), [])
        self.assertEqual(self._get(SUMMARY, self.annotator)["unread_count"], 0)

    def test_left_organization_hides_its_notifications(self):
        org = make_org("org", make_user("owner", "user"))
        membership = add_member(org, self.annotator, Membership.WORKER)
        job = make_job(assignee=self.annotator, org=org)
        n = notify(self.annotator, job)
        self.assertEqual(self._ids(self.annotator), [n.id])

        membership.is_active = False
        membership.save()
        self.assertEqual(self._ids(self.annotator), [])
        self.assertEqual(self._get(SUMMARY, self.annotator)["unread_count"], 0)
        response = self._post_request(read_url(n.id), self.annotator)
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_reassigned_job_hides_worker_events(self):
        notify(self.annotator, self.job)
        models.Job.objects.filter(pk=self.job.pk).update(assignee=self.other)
        self.assertEqual(self._ids(self.annotator), [])
        self.assertEqual(self._get(SUMMARY, self.annotator)["unread_count"], 0)

    def test_removed_from_reviewer_group_hides_org_less_submissions(self):
        notify(self.reviewer, self.job, event="submitted")
        self.reviewer.groups.clear()
        self.reviewer.groups.add(Group.objects.get_or_create(name="worker")[0])
        self.assertEqual(self._ids(self.reviewer), [])

    def test_org_reviewer_demoted_hides_org_submissions(self):
        org = make_org("org", make_user("owner", "user"))
        org_reviewer = make_user("org_reviewer", "worker")
        membership = add_member(org, org_reviewer, Membership.REVIEWER)
        n = notify(org_reviewer, make_job(assignee=self.annotator, org=org), event="submitted")
        self.assertEqual(self._ids(org_reviewer), [n.id])

        membership.role = Membership.WORKER
        membership.save()
        self.assertEqual(self._ids(org_reviewer), [])
        self.assertEqual(self._get(SUMMARY, org_reviewer)["unread_count"], 0)

    def test_reviewer_outranked_by_user_group_does_not_see_org_less_submissions(self):
        # The IAM middleware uses the highest-ranked group: "user" beats "reviewer",
        # and a "user" cannot read other people's organization-less jobs.
        both = make_user("both", "user", "reviewer")
        notify(both, self.job, event="submitted")
        self.assertEqual(self._ids(both), [])

    def test_deleted_job_takes_its_notifications(self):
        notify(self.annotator, self.job)
        self.job.delete()
        self.assertEqual(JobNotification.objects.count(), 0)

    def test_list_is_capped(self):
        JobNotification.objects.bulk_create(
            JobNotification(
                recipient=self.annotator,
                job=self.job,
                event="rejected",
                created_date=timezone.now(),
            )
            for _ in range(105)
        )
        self.assertEqual(len(self._ids(self.annotator)), 100)
        self.assertEqual(self._get(SUMMARY, self.annotator)["unread_count"], 105)

    def test_anonymous_is_rejected(self):
        self.assertEqual(self.client.get(LIST).status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(self.client.get(SUMMARY).status_code, status.HTTP_401_UNAUTHORIZED)
