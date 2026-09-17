# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Add IssueResolutionChange. Pure additive — one new table.

Keeps the issue id on every resolve/reopen, which the `update:issue` event log
cannot (see the model docstring). Written synchronously in
`IssueViewSet.perform_update`.
"""

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("engine", "0101_job_annotation_snapshot"),
    ]

    operations = [
        migrations.CreateModel(
            name="IssueResolutionChange",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("resolved", models.BooleanField()),
                ("changed_at", models.DateTimeField(auto_now_add=True)),
                (
                    "actor",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "issue",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="resolution_changes",
                        to="engine.issue",
                    ),
                ),
            ],
            options={
                "ordering": ["changed_at", "id"],
            },
        ),
    ]
