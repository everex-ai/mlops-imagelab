# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Add JobAnnotationSnapshot/Frame. Pure additive — two new tables."""

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('engine', '0100_alter_issueannotationsnapshot_trigger'),
    ]

    operations = [
        migrations.CreateModel(
            name='JobAnnotationSnapshot',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_date', models.DateTimeField(auto_now_add=True)),
                ('updated_date', models.DateTimeField(auto_now=True)),
                ('trigger', models.CharField(choices=[('submitted', 'submitted'), ('rejected', 'rejected'), ('accepted', 'accepted')], max_length=16)),
                ('from_stage', models.CharField(max_length=32)),
                ('from_state', models.CharField(max_length=32)),
                ('to_stage', models.CharField(max_length=32)),
                ('to_state', models.CharField(max_length=32)),
                ('transitioned_at', models.DateTimeField()),
                ('frame_count', models.PositiveIntegerField(default=0)),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('job', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='annotation_snapshots', to='engine.job')),
            ],
        ),
        migrations.CreateModel(
            name='JobAnnotationSnapshotFrame',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('frame', models.PositiveIntegerField()),
                ('data', models.JSONField()),
                ('snapshot', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='frames', to='engine.jobannotationsnapshot')),
            ],
        ),
        migrations.AddConstraint(
            model_name='jobannotationsnapshotframe',
            constraint=models.UniqueConstraint(fields=('snapshot', 'frame'), name='unique_job_snapshot_frame'),
        ),
        migrations.AddIndex(
            model_name='jobannotationsnapshot',
            index=models.Index(fields=['job', 'transitioned_at'], name='engine_joba_job_id_3f9f33_idx'),
        ),
    ]
