# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.urls import include, path
from rest_framework import routers

from cvat.apps.production_stats import job_history, views

router = routers.DefaultRouter(trailing_slash=False)
router.register("job_facts", views.JobFactsViewSet, basename="production_stats_job_facts")
router.register("job_rounds", views.JobRoundsViewSet, basename="production_stats_job_rounds")
router.register(
    "object_counts",
    views.ObjectCountsViewSet,
    basename="production_stats_object_counts",
)
router.register(
    "job_snapshots", job_history.JobSnapshotsViewSet, basename="production_stats_job_snapshots"
)
router.register("job_issues", job_history.JobIssuesViewSet, basename="production_stats_job_issues")

urlpatterns = [
    # The "api/" prefix is added by cvat/urls.py.
    path("production_stats/", include(router.urls)),
]
