# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Record a job snapshot before capturing it, and say how the capture went.

Rows that exist already were written only after a successful capture, so they
are backfilled as `captured` with `captured_at = created_date`; new rows start
`pending`.
"""

from django.db import migrations, models
from django.db.models import F

_STATUS_CHOICES = [("pending", "pending"), ("captured", "captured"), ("failed", "failed")]


def backfill_captured_at(apps, schema_editor):
    JobAnnotationSnapshot = apps.get_model("engine", "JobAnnotationSnapshot")
    JobAnnotationSnapshot.objects.filter(captured_at__isnull=True).update(
        captured_at=F("created_date")
    )


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0102_issue_resolution_change"),
    ]

    operations = [
        migrations.AddField(
            model_name="jobannotationsnapshot",
            name="captured_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.RunPython(backfill_captured_at, migrations.RunPython.noop),
        migrations.AddField(
            model_name="jobannotationsnapshot",
            name="status",
            field=models.CharField(choices=_STATUS_CHOICES, default="captured", max_length=16),
        ),
        migrations.AlterField(
            model_name="jobannotationsnapshot",
            name="status",
            field=models.CharField(choices=_STATUS_CHOICES, default="pending", max_length=16),
        ),
    ]
