# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from rest_framework import serializers

from .models import JobNotification


class NotificationActorSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    first_name = serializers.CharField()
    last_name = serializers.CharField()


class JobNotificationSerializer(serializers.ModelSerializer):
    is_read = serializers.SerializerMethodField()
    job_id = serializers.IntegerField()
    task_id = serializers.IntegerField(source="job.segment.task_id")
    task_name = serializers.CharField(source="job.segment.task.name")
    actor = NotificationActorSerializer(allow_null=True)
    target_frame = serializers.IntegerField()

    class Meta:
        model = JobNotification
        fields = (
            "id",
            "event",
            "created_date",
            "is_read",
            "job_id",
            "task_id",
            "task_name",
            "actor",
            "target_frame",
        )
        read_only_fields = fields

    def get_is_read(self, obj: JobNotification) -> bool:
        return obj.read_at is not None


class JobNotificationListQuerySerializer(serializers.Serializer):
    unread_only = serializers.BooleanField(required=False, default=False)
