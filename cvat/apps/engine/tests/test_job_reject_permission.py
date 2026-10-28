# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""INNO-126: workers may not move a job to state "rejected"; everyone else may
(사용자 결정 2026-10-28, Q1: worker만 차단).

The decision is made by jobs.rego (`can_reject`), so the API tests below need the
OPA bundle served by a server that runs this source (see CLAUDE.md, "Running
Django tests against uncommitted source").
"""

from types import SimpleNamespace
from unittest import mock

from django.contrib.auth.models import Group
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.test import APIClient

from cvat.apps.engine import models
from cvat.apps.engine.models import JobAnnotationSnapshot, StateChoice
from cvat.apps.engine.permissions import JobPermission
from cvat.apps.engine.tests.test_issue_snapshots_capture import _make_job
from cvat.apps.iam.permissions import PermissionResult, PolicyEnforcer
from cvat.apps.organizations.models import Membership, Organization

REJECT_DENIED = JobPermission.REJECT_DENIED_REASON


def _perm(scope, requested_state=None):
    return JobPermission(
        scope=scope,
        user_id=1,
        group_name="worker",
        org_id=None,
        org_owner_id=None,
        org_role=None,
        obj=None,
        requested_state=requested_state,
    )


class JobPermissionPayloadTest(SimpleTestCase):
    """U1: the requested state reaches OPA under `input.request`, only for update:state."""

    def _scope_params(self, scope, data):
        request = SimpleNamespace(data=data, query_params={})
        return JobPermission.get_scope_specific_params(
            scope, request=request, view=None, obj=None, iam_context=None
        )

    def test_update_state_params_carry_requested_state(self):
        params = self._scope_params(JobPermission.Scopes.UPDATE_STATE, {"state": "rejected"})
        self.assertEqual(params, {"requested_state": "rejected"})

    def test_other_scopes_have_no_requested_state(self):
        params = self._scope_params(JobPermission.Scopes.UPDATE_ASSIGNEE, {"assignee": 1})
        self.assertNotIn("requested_state", params)

    def test_update_state_payload_has_request_key(self):
        perm = _perm(JobPermission.Scopes.UPDATE_STATE, "rejected")
        self.assertEqual(perm.payload["input"]["request"], {"state": "rejected"})

    def test_other_scope_payload_has_no_request_key(self):
        perm = _perm(JobPermission.Scopes.UPDATE_ASSIGNEE)
        self.assertNotIn("request", perm.payload["input"])

    def test_resource_is_not_touched(self):
        perm = _perm(JobPermission.Scopes.UPDATE_STATE, "rejected")
        self.assertIsNone(perm.payload["input"]["resource"])


class JobPermissionReasonTest(SimpleTestCase):
    """U3: the Korean reason is attached only to a denied reject request."""

    def _check(self, perm, allow, can_reject=False):
        with (
            mock.patch(
                "cvat.apps.iam.permissions.OpenPolicyAgentPermission.check_access",
                return_value=PermissionResult(allow=allow),
            ),
            mock.patch.object(JobPermission, "_opa_can_reject", return_value=can_reject),
        ):
            return perm.check_access()

    def test_denied_reject_gets_reason(self):
        result = self._check(_perm(JobPermission.Scopes.UPDATE_STATE, "rejected"), allow=False)
        self.assertFalse(result.allow)
        self.assertEqual(result.reasons, [REJECT_DENIED])

    def test_reject_denied_for_another_cause_has_no_reason(self):
        # can_reject holds, so the denial is not about the worker restriction
        result = self._check(
            _perm(JobPermission.Scopes.UPDATE_STATE, "rejected"), allow=False, can_reject=True
        )
        self.assertFalse(result.allow)
        self.assertEqual(result.reasons, [])

    def test_allowed_reject_has_no_reason(self):
        result = self._check(_perm(JobPermission.Scopes.UPDATE_STATE, "rejected"), allow=True)
        self.assertTrue(result.allow)
        self.assertEqual(result.reasons, [])

    def test_denied_other_state_has_no_reason(self):
        result = self._check(_perm(JobPermission.Scopes.UPDATE_STATE, "completed"), allow=False)
        self.assertEqual(result.reasons, [])

    def test_denied_other_scope_has_no_reason(self):
        result = self._check(_perm(JobPermission.Scopes.VIEW), allow=False)
        self.assertEqual(result.reasons, [])


class PolicyEnforcerReasonTest(SimpleTestCase):
    def _run(self, result):
        perm = mock.Mock()
        perm.check_access.return_value = result
        view = SimpleNamespace(iam_permission_class=mock.Mock(create=lambda *a, **k: [perm]))
        request = SimpleNamespace(method="PATCH")
        with mock.patch("cvat.apps.iam.permissions.get_iam_context", return_value={}):
            return PolicyEnforcer().check_permission(request, view, None)

    def test_reasoned_denial_raises_with_reason(self):
        with self.assertRaises(PermissionDenied) as ctx:
            self._run(PermissionResult(allow=False, reasons=["why"]))
        self.assertEqual(str(ctx.exception.detail), "why")

    def test_plain_denial_returns_false(self):
        self.assertFalse(self._run(PermissionResult(allow=False)))

    def test_allow_returns_true(self):
        self.assertTrue(self._run(PermissionResult(allow=True)))


class JobRejectApiTest(TestCase):
    """U3 end to end through DRF + OPA (sandbox, no organization)."""

    @classmethod
    def setUpTestData(cls):
        def user(name, group):
            u = models.User.objects.create_user(username=name, password="x")
            u.groups.set([Group.objects.get_or_create(name=group)[0]])
            return u

        cls.worker = user("inno126_worker", "worker")
        cls.other_worker = user("inno126_other", "worker")
        cls.reviewer = user("inno126_reviewer", "reviewer")
        cls.plain_user = user("inno126_user", "user")
        cls.admin = models.User.objects.create_superuser(
            username="inno126_admin", email="", password="x"
        )

    def setUp(self):
        _, self.job, _ = _make_job()
        self.job.assignee = self.worker
        self.job.state = StateChoice.COMPLETED.value
        self.job.save()

    def _patch(self, user, data):
        client = APIClient()
        client.force_authenticate(user)
        # Job snapshots are enqueued on commit; keep the transport out of the test.
        with mock.patch("cvat.apps.engine.job_snapshots.enqueue_job_snapshot"):
            with self.captureOnCommitCallbacks(execute=True):
                return client.patch(f"/api/jobs/{self.job.id}", data, format="json")

    def _state(self):
        self.job.refresh_from_db()
        return self.job.state

    def test_worker_reject_is_403_with_reason_and_state_unchanged(self):  # AE3
        response = self._patch(self.worker, {"state": "rejected"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(response.json()["detail"], REJECT_DENIED)
        self.assertEqual(self._state(), StateChoice.COMPLETED.value)
        self.assertFalse(JobAnnotationSnapshot.objects.filter(job=self.job).exists())

    def test_worker_reject_with_other_fields_changes_nothing(self):  # AE6
        response = self._patch(self.worker, {"state": "rejected", "assignee": self.other_worker.id})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
        self.job.refresh_from_db()
        self.assertEqual(self.job.assignee_id, self.worker.id)
        self.assertEqual(self.job.state, StateChoice.COMPLETED.value)

    def test_worker_can_leave_rejected(self):  # AE4
        models.Job.objects.filter(pk=self.job.pk).update(state=StateChoice.REJECTED.value)
        response = self._patch(self.worker, {"state": "in progress"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._state(), StateChoice.IN_PROGRESS.value)

    def test_worker_rejected_noop_is_403(self):  # 가정(사용자 확인 대기) Q2
        models.Job.objects.filter(pk=self.job.pk).update(state=StateChoice.REJECTED.value)
        response = self._patch(self.worker, {"state": "rejected"})
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_reviewer_can_reject(self):  # AE5
        response = self._patch(self.reviewer, {"state": "rejected"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._state(), StateChoice.REJECTED.value)

    def test_user_task_owner_can_reject(self):  # Q1: only workers are blocked
        models.Task.objects.filter(pk=self.job.segment.task_id).update(owner=self.plain_user)
        response = self._patch(self.plain_user, {"state": "rejected"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._state(), StateChoice.REJECTED.value)

    def test_admin_can_reject(self):
        response = self._patch(self.admin, {"state": "rejected"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._state(), StateChoice.REJECTED.value)

    def test_unrelated_denial_keeps_default_message(self):
        # A worker who is not job staff fails the `view` scope first, which carries
        # no reason, so the generic DRF detail is kept even for a reject request.
        response = self._patch(self.other_worker, {"state": "rejected"})
        self.assertIn(response.status_code, (status.HTTP_403_FORBIDDEN, status.HTTP_404_NOT_FOUND))
        self.assertNotEqual(response.json().get("detail"), REJECT_DENIED)
        self.assertEqual(self._state(), StateChoice.COMPLETED.value)


class JobRejectOrgApiTest(TestCase):
    """The organization role decides inside an organization (real OPA)."""

    @classmethod
    def setUpTestData(cls):
        cls.owner = models.User.objects.create_user(username="inno126_org_owner", password="x")
        cls.org = Organization.objects.create(slug="inno126", owner=cls.owner)
        cls.members = {}
        for role, group in [
            ("owner", "user"),
            ("maintainer", "user"),
            ("reviewer", "user"),
            ("worker", "user"),  # global "user", but a worker in this organization
            ("worker_worker", "worker"),
            ("worker_reviewer", "reviewer"),  # global reviewer, org role worker
        ]:
            if role == "owner":
                member = cls.owner
            else:
                member = models.User.objects.create_user(
                    username=f"inno126_org_{role}", password="x"
                )
            member.groups.set([Group.objects.get_or_create(name=group)[0]])
            Membership.objects.create(
                user=member,
                organization=cls.org,
                role=role.split("_")[0],
                is_active=True,
                joined_date=timezone.now(),
            )
            cls.members[role] = member

    def setUp(self):
        task, self.job, _ = _make_job()
        models.Task.objects.filter(pk=task.pk).update(organization=self.org)
        models.Job.objects.filter(pk=self.job.pk).update(state=StateChoice.COMPLETED.value)

    def _patch(self, user, data):
        models.Job.objects.filter(pk=self.job.pk).update(assignee=user)
        client = APIClient()
        client.force_authenticate(user)
        with mock.patch("cvat.apps.engine.job_snapshots.enqueue_job_snapshot"):
            with self.captureOnCommitCallbacks(execute=True):
                return client.patch(
                    f"/api/jobs/{self.job.id}?org={self.org.slug}", data, format="json"
                )

    def test_org_workers_cannot_reject(self):
        for role in ("worker", "worker_worker"):
            with self.subTest(role=role):
                response = self._patch(self.members[role], {"state": "rejected"})
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)
                self.assertEqual(response.json()["detail"], REJECT_DENIED)
                self.job.refresh_from_db()
                self.assertEqual(self.job.state, StateChoice.COMPLETED.value)

    def test_org_worker_can_still_complete(self):
        models.Job.objects.filter(pk=self.job.pk).update(state=StateChoice.IN_PROGRESS.value)
        response = self._patch(self.members["worker"], {"state": "completed"})
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_org_non_workers_can_reject(self):
        # 사용자 결정 2026-10-28: a global reviewer may reject regardless of its org role
        for role in ("owner", "maintainer", "reviewer", "worker_reviewer"):
            with self.subTest(role=role):
                models.Job.objects.filter(pk=self.job.pk).update(state=StateChoice.COMPLETED.value)
                response = self._patch(self.members[role], {"state": "rejected"})
                self.assertEqual(response.status_code, status.HTTP_200_OK, response.content)
                self.job.refresh_from_db()
                self.assertEqual(self.job.state, StateChoice.REJECTED.value)
