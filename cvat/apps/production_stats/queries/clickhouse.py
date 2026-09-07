# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""
ClickHouse client acquisition and infrastructure-error mapping.

This is the only module in the package that touches the driver or Django settings; the
query builders and row mappers next to it are pure functions. The client is opened and
closed per call with a context manager, the same way ``cvat.apps.events.export`` does it -
there is no connection pool to share, and these endpoints are read-only.
"""

from __future__ import annotations

import functools
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from typing import Any

import clickhouse_connect
from clickhouse_connect.driver.client import Client
from clickhouse_connect.driver.exceptions import ClickHouseError
from django.conf import settings
from rest_framework import status
from rest_framework.response import Response

from cvat.apps.engine.log import ServerLogManager

slogger = ServerLogManager(__name__)

__all__ = [
    "ClickHouseError",
    "get_client",
    "handle_clickhouse_exceptions",
    "run_query",
]


@contextmanager
def get_client() -> Iterator[Client]:
    """Open a ClickHouse client for the duration of a single call."""
    clickhouse_settings = settings.CLICKHOUSE["events"]

    with clickhouse_connect.get_client(
        host=clickhouse_settings["HOST"],
        database=clickhouse_settings["NAME"],
        port=clickhouse_settings["PORT"],
        username=clickhouse_settings["USER"],
        password=clickhouse_settings["PASSWORD"],
    ) as client:
        yield client


def run_query(sql: str, parameters: Mapping[str, Any]) -> list[dict[str, Any]]:
    """
    Run one query and return its rows as dicts keyed by column name.

    ``parameters`` are always bound server-side: clickhouse_connect switches to server-side
    binding as soon as the query contains a ``{name:Type}`` placeholder, and every query in
    this package does. Nothing is ever interpolated into the SQL string.
    """
    with get_client() as client:
        result = client.query(sql, parameters=dict(parameters))

    return [dict(zip(result.column_names, row)) for row in result.result_rows]


def handle_clickhouse_exceptions(func):
    """
    Map ClickHouse driver failures to 503 instead of letting them surface as 500.

    Mirrors ``RequestViewSet._handle_redis_exceptions`` in cvat.apps.redis_handler.views:
    an unreachable analytics store is an infrastructure outage, not a server bug, and the
    driver message must not reach the client.
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except ClickHouseError as ex:
            msg = "ClickHouse service is not available"
            slogger.glob.exception(f"{msg}: {str(ex)}")
            return Response(msg, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    return wrapper
