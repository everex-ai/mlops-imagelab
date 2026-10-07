# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest import mock

from django.test import SimpleTestCase
from rest_framework import status

from cvat.apps.engine.tests.utils import ApiTestBase
from cvat.apps.production_stats.queries.clickhouse import ClickHouseError
from cvat.apps.production_stats.queries.user_day import (
    build_user_day_activity_scan,
    map_user_day_activity,
)
from cvat.apps.production_stats.serializers import MAX_PERIOD
from cvat.apps.production_stats.tests.test_endpoints import (
    PERIOD,
    PERIOD_END,
    PERIOD_START,
    RUN_QUERY,
    USER_DAY_ACTIVITY_PATH,
    FakeClickHouse,
    create_db_users,
)

KST = timezone(timedelta(hours=9))


class UserDayActivityScanTest(SimpleTestCase):
    """The SQL is the contract here: which events count toward a person's day."""

    def setUp(self):
        self.scan = build_user_day_activity_scan(
            period_start=datetime(2026, 9, 1, tzinfo=KST),
            period_end=datetime(2026, 10, 1, tzinfo=KST),
        )

    def test_only_client_events_count(self):
        # Server scopes such as send:working_time are emitted when the client flushes,
        # not when the person works.
        self.assertIn("source = 'client'", self.scan.sql)

    def test_events_that_fire_without_a_person_are_excluded(self):
        self.assertIn("scope NOT IN ('debug:info', 'send:exception')", self.scan.sql)

    def test_events_before_six_kst_are_ignored(self):
        # A lone overnight event would otherwise drag the first activity to 01:28.
        self.assertIn("toHour(toTimeZone(timestamp, 'Asia/Seoul')) >= 6", self.scan.sql)

    def test_days_and_times_are_kst(self):
        self.assertIn("toDate(toTimeZone(timestamp, 'Asia/Seoul'))", self.scan.sql)
        self.assertIn("min(toTimeZone(timestamp, 'Asia/Seoul')), '%H:%i'", self.scan.sql)

    def test_window_is_half_open_and_bound_in_utc(self):
        self.assertIn("timestamp >= {period_start:DateTime64}", self.scan.sql)
        self.assertIn("timestamp < {period_end:DateTime64}", self.scan.sql)
        # 2026-09-01 00:00 KST is 2026-08-31 15:00 UTC; the driver sends the wall clock.
        self.assertEqual(self.scan.parameters["period_start"], datetime(2026, 8, 31, 15, 0))
        self.assertEqual(self.scan.parameters["period_end"], datetime(2026, 9, 30, 15, 0))

    def test_rows_are_mapped_to_plain_values(self):
        rows = map_user_day_activity(
            [
                {
                    "user_id": 10,
                    "day": "2026-09-21",
                    "first_at": "09:13",
                    "last_at": "13:02",
                    "events": "42",
                }
            ]
        )

        self.assertEqual(
            rows,
            [
                {
                    "user_id": 10,
                    "date": "2026-09-21",
                    "first_at": "09:13",
                    "last_at": "13:02",
                    "events": 42,
                }
            ],
        )


class UserDayActivityEndpointTest(ApiTestBase):
    @classmethod
    def setUpTestData(cls):
        create_db_users(cls)

    def _read(self, fake: FakeClickHouse, **query_params) -> Any:
        with mock.patch(RUN_QUERY, fake):
            return self._get_request(
                USER_DAY_ACTIVITY_PATH, user=self.admin, query_params={**PERIOD, **query_params}
            )

    def test_rows_come_back_in_one_response(self):
        fake = FakeClickHouse(
            user_days=[
                {
                    "user_id": 10,
                    "day": "2026-08-04",
                    "first_at": "09:01",
                    "last_at": "18:00",
                    "events": 900,
                },
                {
                    "user_id": 10,
                    "day": "2026-08-05",
                    "first_at": "14:27",
                    "last_at": "18:00",
                    "events": 300,
                },
                {
                    "user_id": 11,
                    "day": "2026-08-04",
                    "first_at": "08:52",
                    "last_at": "13:01",
                    "events": 400,
                },
            ]
        )

        response = self._read(fake)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        self.assertIsNone(payload["next"])
        self.assertEqual(
            payload["results"][2],
            {
                "user_id": 11,
                "date": "2026-08-04",
                "first_at": "08:52",
                "last_at": "13:01",
                "events": 400,
            },
        )

    def test_the_requested_window_is_bound(self):
        fake = FakeClickHouse()

        self._read(fake)

        parameters = fake.parameters_for("AS first_at")
        self.assertEqual(parameters["period_start"], PERIOD_START.replace(tzinfo=None))
        self.assertEqual(parameters["period_end"], PERIOD_END.replace(tzinfo=None))

    def test_the_period_is_echoed_back(self):
        payload = self._read(FakeClickHouse()).json()

        self.assertEqual(
            datetime.fromisoformat(payload["period"]["start"].replace("Z", "+00:00")),
            PERIOD_START,
        )

    def test_a_clickhouse_outage_is_a_503(self):
        def broken(sql, parameters):
            raise ClickHouseError("connection refused")

        with mock.patch(RUN_QUERY, broken):
            response = self._get_request(
                USER_DAY_ACTIVITY_PATH, user=self.admin, query_params=PERIOD
            )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)

    def test_a_missing_period_is_rejected(self):
        with mock.patch(RUN_QUERY, FakeClickHouse()):
            response = self._get_request(USER_DAY_ACTIVITY_PATH, user=self.admin)

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_a_period_longer_than_the_cap_is_rejected(self):
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)

        response = self._read(
            FakeClickHouse(),
            period_start=start.isoformat(),
            period_end=(start + MAX_PERIOD + timedelta(days=1)).isoformat(),
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
