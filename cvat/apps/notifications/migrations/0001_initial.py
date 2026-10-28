# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("engine", "0103_job_annotation_snapshot_status"),
    ]

    operations = [
        migrations.CreateModel(
            name="JobNotification",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                (
                    "event",
                    models.CharField(
                        choices=[
                            ("submitted", "submitted"),
                            ("rejected", "rejected"),
                            ("accepted", "accepted"),
                        ],
                        max_length=16,
                    ),
                ),
                ("created_date", models.DateTimeField()),
                ("read_at", models.DateTimeField(blank=True, null=True)),
                ("deleted_at", models.DateTimeField(blank=True, null=True)),
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
                    "job",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="notifications",
                        to="engine.job",
                    ),
                ),
                (
                    "recipient",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="job_notifications",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "default_permissions": (),
                "indexes": [
                    models.Index(
                        fields=["recipient", "deleted_at", "read_at"],
                        name="job_notif_unread_idx",
                    ),
                    models.Index(
                        fields=["recipient", "-created_date"], name="job_notif_recent_idx"
                    ),
                    models.Index(fields=["created_date"], name="job_notif_created_idx"),
                ],
            },
        ),
    ]
