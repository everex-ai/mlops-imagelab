# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.urls import include, path
from rest_framework import routers

from cvat.apps.production_stats import views

router = routers.DefaultRouter(trailing_slash=False)
router.register("job_facts", views.JobFactsViewSet, basename="production_stats_job_facts")
router.register("job_rounds", views.JobRoundsViewSet, basename="production_stats_job_rounds")

urlpatterns = [
    # The "api/" prefix is added by cvat/urls.py.
    path("production_stats/", include(router.urls)),
]
