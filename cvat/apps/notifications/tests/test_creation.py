# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Job round boundaries create one notification per recipient once they commit (U2)."""

from unittest import mock

from django.db import transaction
from django.test import TestCase
from django.utils import timezone

from cvat.apps.engine import models
from cvat.apps.engine.job_snapshots import job_round_boundary
from cvat.apps.engine.models import JobAnnotationSnapshot
from cvat.apps.notifications.models import JobNotification
from cvat.apps.organizations.models import Membership

from .helpers import add_member, make_job, make_org, make_user, transition


def _rows():
    return sorted(JobNotification.objects.values_list("recipient__username", "event", "actor_id"))


class AssigneeEventsTest(TestCase):
    def setUp(self):
        self.annotator = make_user("annotator", "worker")
        self.reviewer = make_user("reviewer", "reviewer")

    def test_reviewer_rejection_notifies_the_assignee_only(self):
        # AE1
        job = make_job(assignee=self.annotator, state="completed")
        transition(self, job, actor=self.reviewer, state="rejected")
        self.assertEqual(_rows(), [("annotator", "rejected", self.reviewer.id)])

    def test_completed_to_in_progress_is_a_rejection_too(self):
        job = make_job(assignee=self.annotator, state="completed")
        transition(self, job, actor=self.reviewer, state="in progress")
        self.assertEqual(_rows(), [("annotator", "rejected", self.reviewer.id)])

    def test_assignee_reopening_their_own_job_notifies_nobody(self):
        # AE2
        job = make_job(assignee=self.annotator, state="completed")
        transition(self, job, actor=self.annotator, state="in progress")
        self.assertEqual(_rows(), [])

    def test_acceptance_notifies_the_assignee(self):
        job = make_job(assignee=self.annotator, state="completed")
        transition(self, job, actor=self.reviewer, stage="acceptance")
        self.assertEqual(_rows(), [("annotator", "accepted", self.reviewer.id)])

    def test_unassigned_job_notifies_nobody(self):
        job = make_job(assignee=None, state="completed")
        transition(self, job, actor=self.reviewer, state="rejected")
        self.assertEqual(_rows(), [])

    def test_inactive_assignee_is_skipped(self):
        self.annotator.is_active = False
        self.annotator.save()
        job = make_job(assignee=self.annotator, state="completed")
        transition(self, job, actor=self.reviewer, state="rejected")
        self.assertEqual(_rows(), [])

    def test_event_time_is_the_transition_time(self):
        job = make_job(assignee=self.annotator, state="completed")
        before = timezone.now()
        transition(self, job, actor=self.reviewer, state="rejected")
        after = timezone.now()
        self.assertTrue(before <= JobNotification.objects.get().created_date <= after)


class SubmissionTest(TestCase):
    def setUp(self):
        self.owner = make_user("owner", "user")
        self.annotator = make_user("annotator", "worker")

    def test_org_job_notifies_the_orgs_active_reviewers(self):
        org = make_org("org", self.owner)
        other_org = make_org("other", self.owner)
        r1, r2 = make_user("r1", "worker"), make_user("r2", "worker")
        add_member(org, r1, Membership.REVIEWER)
        add_member(org, r2, Membership.REVIEWER)
        add_member(org, make_user("inactive_member"), Membership.REVIEWER, is_active=False)
        add_member(org, make_user("org_worker"), Membership.WORKER)
        add_member(other_org, make_user("other_reviewer"), Membership.REVIEWER)
        add_member(org, make_user("disabled", is_active=False), Membership.REVIEWER)
        add_member(org, self.annotator, Membership.REVIEWER)  # the actor

        job = make_job(assignee=self.annotator, org=org, state="in progress")
        transition(self, job, actor=self.annotator, state="completed")

        self.assertEqual(
            _rows(),
            [("r1", "submitted", self.annotator.id), ("r2", "submitted", self.annotator.id)],
        )

    def test_org_less_job_notifies_the_global_reviewer_group(self):
        make_user("global_reviewer", "reviewer")
        make_user("plain_user", "user")
        job = make_job(assignee=self.annotator, state="in progress")
        transition(self, job, actor=self.annotator, state="completed")
        self.assertEqual(_rows(), [("global_reviewer", "submitted", self.annotator.id)])

    def test_org_less_job_skips_reviewers_outranked_by_the_user_group(self):
        make_user("global_reviewer", "reviewer")
        make_user("user_and_reviewer", "user", "reviewer")
        make_user("admin_and_reviewer", "admin", "reviewer")
        job = make_job(assignee=self.annotator, state="in progress")
        transition(self, job, actor=self.annotator, state="completed")
        self.assertEqual([r[0] for r in _rows()], ["admin_and_reviewer", "global_reviewer"])

    def test_a_reviewer_submitting_is_not_notified_of_it(self):
        reviewer = make_user("global_reviewer", "reviewer")
        job = make_job(assignee=reviewer, state="in progress")
        transition(self, job, actor=reviewer, state="completed")
        self.assertEqual(_rows(), [])

    def test_resubmission_after_rejection_notifies_again(self):
        # Q4: one event, one row - never merged per job.
        make_user("global_reviewer", "reviewer")
        job = make_job(assignee=self.annotator, state="in progress")
        transition(self, job, actor=self.annotator, state="completed")
        models.Job.objects.filter(pk=job.pk).update(state="rejected")
        job.refresh_from_db()
        transition(self, job, actor=self.annotator, state="completed")
        self.assertEqual(JobNotification.objects.filter(event="submitted").count(), 2)


class NonBoundaryTest(TestCase):
    def setUp(self):
        make_user("global_reviewer", "reviewer")
        self.annotator = make_user("annotator", "worker")

    def test_non_boundaries_notify_nobody(self):
        job = make_job(assignee=self.annotator, state="new")
        transition(self, job, actor=self.annotator, state="in progress")
        transition(self, job, actor=self.annotator, stage="validation")
        transition(self, job, actor=self.annotator)  # plain re-save
        job.touch()
        self.assertEqual(_rows(), [])


class CommitSemanticsTest(TestCase):
    def setUp(self):
        self.annotator = make_user("annotator", "worker")
        self.reviewer = make_user("reviewer", "reviewer")

    def test_rolled_back_transition_notifies_nobody(self):
        # A request denied or failed after save (e.g. INNO-126's worker -> rejected 403
        # raised inside the transaction) must not leave a notification behind.
        job = make_job(assignee=self.annotator, state="completed")
        with self.captureOnCommitCallbacks(execute=True):
            with mock.patch("cvat.apps.engine.job_snapshots.enqueue_job_snapshot"):
                try:
                    with transaction.atomic():
                        job.state = "rejected"
                        job.save()
                        raise RuntimeError("denied")
                except RuntimeError:
                    pass
        self.assertEqual(_rows(), [])

    def test_notification_failure_does_not_break_the_transition_or_the_snapshot(self):
        job = make_job(assignee=self.annotator, state="completed")
        with (
            mock.patch(
                "cvat.apps.notifications.signals.create_job_notifications",
                side_effect=RuntimeError("db hiccup"),
            ),
            mock.patch("cvat.apps.engine.job_snapshots.django_rq.get_queue"),
            self.captureOnCommitCallbacks(execute=True),
        ):
            job.state = "rejected"
            job.save()
        job.refresh_from_db()
        self.assertEqual(job.state, "rejected")
        self.assertEqual(JobAnnotationSnapshot.objects.get(job=job).trigger, "rejected")
        self.assertEqual(_rows(), [])

    def test_a_failing_receiver_does_not_stop_the_others(self):
        calls = []

        def broken(**kwargs):
            raise RuntimeError("boom")

        def healthy(**kwargs):
            calls.append(kwargs["job_id"])

        job_round_boundary.connect(broken, dispatch_uid="test-broken")
        job_round_boundary.connect(healthy, dispatch_uid="test-healthy")
        try:
            job = make_job(assignee=self.annotator, state="completed")
            transition(self, job, actor=self.reviewer, state="rejected")
        finally:
            job_round_boundary.disconnect(dispatch_uid="test-broken")
            job_round_boundary.disconnect(dispatch_uid="test-healthy")
        self.assertEqual(calls, [job.id])
        self.assertEqual(_rows(), [("annotator", "rejected", self.reviewer.id)])

    def test_deleted_job_is_a_noop(self):
        from cvat.apps.notifications.services import create_job_notifications

        self.assertEqual(
            create_job_notifications(
                job_id=999999, trigger="rejected", actor_id=None, transitioned_at=None
            ),
            [],
        )
