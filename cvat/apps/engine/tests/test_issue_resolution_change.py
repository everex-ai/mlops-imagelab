# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Issue resolve / reopen history (label_supporter requirements KD8, R23).

`update:issue` events do record `resolved` changes, but `handle_update` sets
`obj_id` from `<prop>_id`, which is empty for `resolved`, so a job with 17 issues
has 17 resolve events and no way to tell them apart (production job 78299).
This table keeps the issue id.
"""

from types import SimpleNamespace

from django.test import TestCase

from cvat.apps.engine import models
from cvat.apps.engine.models import IssueResolutionChange
from cvat.apps.engine.serializers import IssueWriteSerializer
from cvat.apps.engine.views import IssueViewSet


class IssueResolutionChangeTest(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.reviewer = models.User.objects.create_user(username="rev", password="x")
        task = models.Task.objects.create(name="resolution", mode="annotation")
        segment = models.Segment.objects.create(task=task, start_frame=0, stop_frame=5)
        cls.job = models.Job.objects.create(segment=segment, type=models.JobType.ANNOTATION)

    def _issue(self, resolved=False):
        return models.Issue.objects.create(
            job=self.job, frame=0, position=[0.0, 0.0, 1.0, 1.0], resolved=resolved
        )

    def _set_resolved(self, issue, resolved):
        view = IssueViewSet()
        view.request = SimpleNamespace(user=self.reviewer)
        serializer = IssueWriteSerializer(instance=issue, data={"resolved": resolved}, partial=True)
        serializer.is_valid(raise_exception=True)
        with self.captureOnCommitCallbacks(execute=False):
            view.perform_update(serializer)

    def test_resolve_and_reopen_are_recorded_with_issue_and_actor(self):
        issue = self._issue()
        self._set_resolved(issue, True)
        self._set_resolved(issue, False)
        self._set_resolved(issue, True)
        self.assertEqual(
            list(issue.resolution_changes.values_list("resolved", "actor_id")),
            [(True, self.reviewer.id), (False, self.reviewer.id), (True, self.reviewer.id)],
        )

    def test_updates_that_do_not_change_resolved_record_nothing(self):
        issue = self._issue(resolved=True)
        self._set_resolved(issue, True)
        self.assertEqual(IssueResolutionChange.objects.count(), 0)

    def test_changes_are_kept_per_issue(self):
        first, second = self._issue(), self._issue()
        self._set_resolved(first, True)
        self._set_resolved(second, True)
        self.assertEqual(first.resolution_changes.count(), 1)
        self.assertEqual(second.resolution_changes.count(), 1)

    def test_cascade_on_issue_delete(self):
        issue = self._issue()
        self._set_resolved(issue, True)
        issue.delete()
        self.assertEqual(IssueResolutionChange.objects.count(), 0)
