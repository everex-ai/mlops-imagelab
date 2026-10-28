# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Who gets a job notification, and which of their notifications they may still see."""

from __future__ import annotations

import logging
from datetime import datetime

from django.contrib.auth.models import User
from django.db.models import Case, Exists, F, IntegerField, OuterRef, Q, Subquery, When
from django.db.models.functions import Coalesce

from cvat.apps.engine.models import Issue, Job, JobSnapshotTrigger
from cvat.apps.organizations.models import Membership

from .models import JobNotification, JobNotificationQuerySet

logger = logging.getLogger(__name__)

# Django group of global (organization-less) reviewers, see IAM_ROLES.
REVIEWER_GROUP = "reviewer"

_ASSIGNEE_EVENTS = (JobSnapshotTrigger.REJECTED.value, JobSnapshotTrigger.ACCEPTED.value)


def resolve_recipient_ids(job: Job, trigger: str, actor_id: int | None) -> list[int]:
    """Recipients of one boundary. The actor is never notified of their own action (R4)."""
    if trigger in _ASSIGNEE_EVENTS:
        # R1, R2: the assignee. No assignee -> nobody.
        assignee = job.assignee
        if assignee is None or assignee.id == actor_id or not assignee.is_active:
            return []
        return [assignee.id]

    if trigger == JobSnapshotTrigger.SUBMITTED.value:
        # R3 / 가정 Q1(사용자 확인 대기): the job organization's active reviewer
        # members, or the global reviewer group for organization-less jobs.
        org_id = job.segment.task.organization_id
        if org_id is not None:
            users = User.objects.filter(
                memberships__organization_id=org_id,
                memberships__is_active=True,
                memberships__role=Membership.REVIEWER,
            )
        else:
            users = User.objects.filter(groups__name=REVIEWER_GROUP)
        users = users.filter(is_active=True)
        if actor_id is not None:
            users = users.exclude(pk=actor_id)
        return sorted(set(users.values_list("pk", flat=True)))

    return []


def create_job_notifications(
    *, job_id: int, trigger: str, actor_id: int | None, transitioned_at: datetime
) -> list[JobNotification]:
    """One row per recipient for one committed boundary (Q4: one event = one row)."""
    job = Job.objects.select_related("assignee", "segment__task").filter(pk=job_id).first()
    if job is None:
        logger.info("Job %s no longer exists; skipping %s notifications", job_id, trigger)
        return []

    recipient_ids = resolve_recipient_ids(job, trigger, actor_id)
    if not recipient_ids:
        return []

    return JobNotification.objects.bulk_create(
        JobNotification(
            recipient_id=recipient_id,
            job_id=job_id,
            event=trigger,
            actor_id=actor_id,
            created_date=transitioned_at,
        )
        for recipient_id in recipient_ids
    )


def visible_notifications(user: User) -> JobNotificationQuerySet:
    """The user's notifications they can still act on (R19, R26).

    Hidden, not deleted: a job removed from the user's reach (left the
    organization, reassigned, removed from the reviewer group) drops out of the
    list and the badge. Deleted jobs cascade their notifications away.
    """
    qs = JobNotification.objects.active().filter(recipient=user)

    has_membership = Exists(
        Membership.objects.filter(
            organization_id=OuterRef("job__segment__task__organization_id"),
            user_id=user.id,
            is_active=True,
        )
    )
    qs = qs.filter(Q(job__segment__task__organization__isnull=True) | Q(has_membership))

    # The worker-facing events stay visible only while the user is still the assignee.
    qs = qs.exclude(Q(event__in=_ASSIGNEE_EVENTS) & ~Q(job__assignee_id=user.id))

    if not user.groups.filter(name=REVIEWER_GROUP).exists():
        qs = qs.exclude(
            event=JobSnapshotTrigger.SUBMITTED.value,
            job__segment__task__organization__isnull=True,
        )

    return qs


def with_target_frame(qs: JobNotificationQuerySet) -> JobNotificationQuerySet:
    """Annotate `target_frame`, the frame a click opens (R17, R18), computed now.

    Rejections open the first unresolved issue's frame; everything else, or a
    rejection whose issues are all resolved, opens the job's first frame. Both
    `Issue.frame` and `segment.start_frame` are task-relative frame numbers.
    """
    first_open_issue = (
        Issue.objects.filter(job_id=OuterRef("job_id"), resolved=False)
        .order_by("frame")
        .values("frame")[:1]
    )
    return qs.annotate(
        target_frame=Coalesce(
            Case(
                When(
                    event=JobSnapshotTrigger.REJECTED.value,
                    then=Subquery(first_open_issue, output_field=IntegerField()),
                ),
                output_field=IntegerField(),
            ),
            F("job__segment__start_frame"),
            output_field=IntegerField(),
        )
    )
