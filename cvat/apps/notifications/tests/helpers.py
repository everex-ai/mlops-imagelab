# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

from __future__ import annotations

from contextlib import ExitStack
from unittest import mock

from django.contrib.auth.models import Group, User

from cvat.apps.engine import models
from cvat.apps.engine.tests.test_issue_snapshots_capture import _make_job
from cvat.apps.organizations.models import Membership, Organization

_ENQUEUE_SNAPSHOT = "cvat.apps.engine.job_snapshots.enqueue_job_snapshot"
_CURRENT_USER = "cvat.apps.engine.job_snapshots.get_current_user"


def make_user(username: str, *groups: str, **kwargs) -> User:
    """A user in exactly these IAM groups. The signup signal adds the default "user"
    group, which would outrank "reviewer"; real reviewers are set up without it."""
    user = User.objects.create_user(username=username, password=username, **kwargs)
    user.groups.clear()
    for name in groups:
        user.groups.add(Group.objects.get_or_create(name=name)[0])
    return user


def make_org(slug: str, owner: User) -> Organization:
    return Organization.objects.create(slug=slug, name=slug, owner=owner)


def add_member(org: Organization, user: User, role: str, *, is_active: bool = True):
    return Membership.objects.create(organization=org, user=user, role=role, is_active=is_active)


def make_job(*, assignee: User | None = None, org: Organization | None = None, state="new"):
    task, job, _ = _make_job()
    if org is not None:
        models.Task.objects.filter(pk=task.pk).update(organization=org)
    models.Job.objects.filter(pk=job.pk).update(assignee=assignee, state=state)
    job.refresh_from_db()
    return job


def transition(testcase, job, *, actor: User | None, **fields) -> None:
    """Save a stage/state change the way a request does, and run its on_commit hooks.

    The snapshot enqueue is stubbed: it needs Redis and is covered by the engine tests.
    """
    with ExitStack() as stack:
        stack.enter_context(mock.patch(_ENQUEUE_SNAPSHOT))
        stack.enter_context(mock.patch(_CURRENT_USER, return_value=actor))
        stack.enter_context(testcase.captureOnCommitCallbacks(execute=True))
        for name, value in fields.items():
            setattr(job, name, value)
        job.save()
