# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from django.urls import include, path
from rest_framework import routers

from . import views

# SimpleRouter: a DefaultRouter mounted at "" would add an API root view over /api/.
router = routers.SimpleRouter(trailing_slash=False)
router.register("notifications", views.JobNotificationViewSet, basename="job_notification")

urlpatterns = [
    # The "api/" prefix is added by cvat/urls.py.
    path("", include(router.urls)),
]
