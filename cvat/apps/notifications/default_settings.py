# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from datetime import timedelta

# Notifications older than this are soft-deleted by the daily cron (R26).
JOB_NOTIFICATION_RETENTION = timedelta(days=30)

# The header dropdown shows at most this many notifications, newest first.
JOB_NOTIFICATION_LIST_LIMIT = 100
