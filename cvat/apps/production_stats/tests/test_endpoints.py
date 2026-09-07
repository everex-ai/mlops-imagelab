# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.contrib.auth.models import Group, User
from rest_framework import status

from cvat.apps.engine.tests.utils import ApiTestBase

JOB_FACTS_PATH = "/api/production_stats/job_facts"
JOB_ROUNDS_PATH = "/api/production_stats/job_rounds/1"
ALL_PATHS = (JOB_FACTS_PATH, JOB_ROUNDS_PATH)


class ProductionStatsPermissionTest(ApiTestBase):
    """
    Checks that the production stats endpoints are reachable by admins only.

    These tests talk to a real OPA instance at settings.IAM_OPA_HOST, like the
    rest of the permission tests in this repository.
    """

    @classmethod
    def setUpTestData(cls):
        group_admin, _ = Group.objects.get_or_create(name="admin")
        group_user, _ = Group.objects.get_or_create(name="user")
        group_worker, _ = Group.objects.get_or_create(name="worker")

        # OPA reads the privilege from the Django auth group, not from
        # User.is_superuser, so create_superuser() alone would still be denied.
        cls.admin = User.objects.create_superuser(username="admin", email="", password="admin")
        cls.admin.groups.add(group_admin)

        cls.user = User.objects.create_user(username="user", password="user")
        cls.user.groups.add(group_user)

        cls.worker = User.objects.create_user(username="worker", password="worker")
        cls.worker.groups.add(group_worker)

    def test_admin_can_read_production_stats(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                response = self._get_request(path, user=self.admin)
                self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_job_facts_returns_a_list_payload(self):
        response = self._get_request(JOB_FACTS_PATH, user=self.admin)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("results", response.json())

    def test_job_rounds_returns_a_rounds_payload(self):
        response = self._get_request(JOB_ROUNDS_PATH, user=self.admin)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("rounds", response.json())

    def test_regular_user_cannot_read_production_stats(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                response = self._get_request(path, user=self.user)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_worker_cannot_read_production_stats(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                response = self._get_request(path, user=self.worker)
                self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)

    def test_anonymous_user_cannot_read_production_stats(self):
        for path in ALL_PATHS:
            with self.subTest(path=path):
                response = self._get_request(path, user=None)
                self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
