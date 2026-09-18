# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Read API that Beacon's job viewer needs besides the round history.

`job_outline` gives what drawing a job needs once (labels, skeleton edges, the
frames the job shows, when history recording started); `job_frames` gives the
live annotations in the same shape as a snapshot frame, so the viewer draws the
present and the past with one renderer. Admin-only like the rest of
production_stats. These tests talk to a real OPA instance.
"""

from __future__ import annotations

from django.db.migrations.recorder import MigrationRecorder
from django.test import SimpleTestCase
from django.utils.dateparse import parse_datetime
from rest_framework import status

from cvat.apps.engine import models
from cvat.apps.engine.models import Label, Project, Skeleton
from cvat.apps.engine.tests.test_issue_snapshots_capture import _make_job
from cvat.apps.engine.tests.utils import ApiTestBase
from cvat.apps.production_stats.job_history import skeleton_edges
from cvat.apps.production_stats.tests.test_endpoints import create_db_users

OUTLINE = "/api/production_stats/job_outline"
FRAMES = "/api/production_stats/job_frames"


def _skeleton_svg(nose_id: int, eye_id: int) -> str:
    # The shape the CVAT skeleton editor stores: circles carry node and label
    # ids (the label name is sometimes missing), lines reference node ids.
    return (
        '<line x1="1" y1="1" x2="2" y2="2" data-type="edge"'
        ' data-node-from="1" data-node-to="2"></line>'
        '<circle r="0.75" cx="1" cy="1" data-type="element node" data-element-id="1"'
        f' data-node-id="1" data-label-id="{nose_id}" data-label-name="nose"></circle>'
        '<circle r="0.75" cx="2" cy="2" data-type="element node" data-element-id="2"'
        f' data-node-id="2" data-label-id="{eye_id}"></circle>'
    )


def _viewer_job(*, size: int = 4, deleted: tuple[int, ...] = ()):
    """A job in a project with a two-point skeleton label and a points label."""
    project = Project.objects.create(name="Viewer")
    task, job, _ = _make_job(size=size, label_names=())
    models.Task.objects.filter(pk=task.pk).update(project=project)
    models.Data.objects.filter(pk=task.data_id).update(deleted_frames=list(deleted))
    person = Label.objects.create(project=project, name="person", type="skeleton", color="#ff0000")
    nose = Label.objects.create(
        project=project, parent=person, name="nose", type="points", color="#00ff00"
    )
    eye = Label.objects.create(
        project=project, parent=person, name="left_eye", type="points", color="#0000ff"
    )
    Skeleton.objects.create(root=person, svg=_skeleton_svg(nose.id, eye.id))
    ball = Label.objects.create(project=project, name="ball", type="points", color="#ffff00")
    job.refresh_from_db()
    return job, {"person": person, "nose": nose, "eye": eye, "ball": ball}


class SkeletonEdgesTest(SimpleTestCase):
    def test_edges_are_sublabel_name_pairs(self):
        self.assertEqual(
            skeleton_edges(_skeleton_svg(11, 12), {11: "nose", 12: "left_eye"}),
            [["nose", "left_eye"]],
        )

    def test_a_circle_without_a_name_falls_back_to_its_label_id(self):
        # The second circle in _skeleton_svg has no data-label-name.
        self.assertEqual(skeleton_edges(_skeleton_svg(11, 12), {12: "left_eye"})[0][1], "left_eye")

    def test_unreadable_svg_gives_no_edges(self):
        for svg in ("", "<line", '<line data-node-from="1" data-node-to="9"></line>'):
            with self.subTest(svg=svg):
                self.assertEqual(skeleton_edges(svg, {}), [])


class JobOutlineApiTest(ApiTestBase):
    @classmethod
    def setUpTestData(cls):
        create_db_users(cls)
        cls.job, cls.labels = _viewer_job(size=4, deleted=(2,))

    def test_outline_lists_labels_edges_and_visible_frames(self):
        response = self._get_request(f"{OUTLINE}/{self.job.id}", self.admin)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual(body["job_id"], self.job.id)
        self.assertEqual(body["project_name"], "Viewer")
        self.assertEqual(body["frames"], [0, 1, 3])  # frame 2 is deleted

        labels = {label["name"]: label for label in body["labels"]}
        self.assertEqual(set(labels), {"person", "ball"})  # sublabels are nested, not top level
        self.assertEqual([s["name"] for s in labels["person"]["sublabels"]], ["nose", "left_eye"])
        self.assertEqual(labels["person"]["edges"], [["nose", "left_eye"]])
        self.assertEqual((labels["ball"]["color"], labels["ball"]["edges"]), ("#ffff00", []))

    def test_history_since_is_when_each_history_table_was_created(self):
        applied = dict(
            MigrationRecorder.Migration.objects.filter(
                app="engine",
                name__in=["0101_job_annotation_snapshot", "0102_issue_resolution_change"],
            ).values_list("name", "applied")
        )
        body = self._get_request(f"{OUTLINE}/{self.job.id}", self.admin).json()
        self.assertEqual(
            {k: parse_datetime(v) for k, v in body["history_since"].items()},
            {
                "snapshots": applied["0101_job_annotation_snapshot"],
                "resolutions": applied["0102_issue_resolution_change"],
            },
        )

    def test_missing_job_is_404_for_admin_and_403_for_others(self):
        self.assertEqual(
            self._get_request(f"{OUTLINE}/99999999", self.admin).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        for user in (self.user, self.worker):
            with self.subTest(user=user.username):
                self.assertEqual(
                    self._get_request(f"{OUTLINE}/{self.job.id}", user).status_code,
                    status.HTTP_403_FORBIDDEN,
                )
                self.assertEqual(
                    self._get_request(f"{OUTLINE}/99999999", user).status_code,
                    status.HTTP_403_FORBIDDEN,
                )
