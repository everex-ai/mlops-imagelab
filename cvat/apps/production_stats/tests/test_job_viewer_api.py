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
from django.test import SimpleTestCase, TestCase
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework import status

from cvat.apps.engine import models
from cvat.apps.engine.job_snapshots import build_job_snapshot_frames
from cvat.apps.engine.models import Label, Project, Skeleton
from cvat.apps.engine.tests.test_issue_snapshots_capture import _make_job
from cvat.apps.engine.tests.utils import ApiTestBase
from cvat.apps.production_stats.job_history import _job_labels, skeleton_edges
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

    def test_a_circle_without_a_name_uses_its_label_id(self):
        # The second circle in _skeleton_svg carries no data-label-name at all,
        # so the id lookup is its only source of a name.
        self.assertEqual(skeleton_edges(_skeleton_svg(11, 12), {12: "left_eye"})[0][1], "left_eye")

    def test_id_wins_over_a_stale_label_name(self):
        # The first circle in _skeleton_svg carries BOTH data-label-id and a
        # literal data-label-name="nose". If the sublabel was renamed since
        # this svg was captured, data-label-name is the stale one: the id, via
        # the caller's current id-to-name map, must win.
        self.assertEqual(
            skeleton_edges(_skeleton_svg(11, 12), {11: "nose_tip", 12: "left_eye"})[0][0],
            "nose_tip",
        )

    def test_an_unknown_id_falls_back_to_the_label_name(self):
        # id 11 is not in the map (unknown to the caller): the stale-but-only
        # available data-label-name="nose" is used rather than dropping the node.
        self.assertEqual(skeleton_edges(_skeleton_svg(11, 12), {12: "left_eye"})[0][0], "nose")

    def test_unreadable_svg_gives_no_edges(self):
        for svg in ("", "<line", '<line data-node-from="1" data-node-to="9"></line>'):
            with self.subTest(svg=svg):
                self.assertEqual(skeleton_edges(svg, {}), [])


class JobLabelsTaskOnlyLabelsTest(TestCase):
    """`_job_labels` has a branch for a task that is NOT in a project (uses the
    task's own labels rather than the project's); nothing else exercises it."""

    def test_a_task_without_a_project_uses_its_own_labels(self):
        task, _, labels = _make_job(label_names=("car",))
        self.assertIsNone(task.project_id)
        result = _job_labels(task)
        self.assertEqual([label["name"] for label in result], ["car"])
        self.assertEqual(result[0]["id"], labels["car"].id)


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

    def test_a_deleted_frame_is_reported_separately_from_frames(self):
        # R24: job_snapshots can hold a frame deleted since it was captured;
        # the viewer needs a slot for it even though it can't be drawn live.
        body = self._get_request(f"{OUTLINE}/{self.job.id}", self.admin).json()
        self.assertEqual(body["segment"], {"start_frame": 0, "stop_frame": 3})
        self.assertEqual(body["deleted_frames"], [2])
        self.assertEqual(body["frames"], [0, 1, 3])  # frames and deleted_frames are disjoint
        self.assertEqual(
            sorted(body["frames"] + body["deleted_frames"]),
            list(range(body["segment"]["start_frame"], body["segment"]["stop_frame"] + 1)),
        )

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


class JobFramesApiTest(ApiTestBase):
    @classmethod
    def setUpTestData(cls):
        create_db_users(cls)
        cls.job, cls.labels = _viewer_job(size=4, deleted=(2,))
        models.LabeledShape.objects.create(
            job=cls.job,
            label=cls.labels["ball"],
            frame=1,
            type="points",
            points=[10.0, 20.0],
            occluded=False,
            outside=False,
            z_order=0,
            group=0,
            rotation=0.0,
            source="manual",
        )

    def _frames(self, user, **params):
        return self._get_request(f"{FRAMES}/{self.job.id}", user, query_params=params)

    def test_live_frames_use_the_snapshot_payload_shape(self):
        response = self._frames(self.admin, frame_from=0, frame_to=3)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        body = response.json()
        self.assertEqual((body["frame_from"], body["frame_to"]), (0, 3))
        self.assertEqual([f["frame"] for f in body["frames"]], [0, 1, 3])  # 2 is deleted
        frame1 = next(f for f in body["frames"] if f["frame"] == 1)
        self.assertEqual(set(frame1), {"frame", "abs_frame", "name", "width", "height", "objects"})
        self.assertEqual(
            (frame1["objects"][0]["label"], frame1["objects"][0]["points"]),
            ("ball", [10.0, 20.0]),
        )

    def test_a_frame_without_objects_is_listed_empty(self):
        body = self._frames(self.admin, frame_from=0, frame_to=0).json()
        self.assertEqual([(f["frame"], f["objects"]) for f in body["frames"]], [(0, [])])

    def test_only_the_requested_range_is_returned(self):
        body = self._frames(self.admin, frame_from=1, frame_to=1).json()
        self.assertEqual([f["frame"] for f in body["frames"]], [1])

    def test_a_track_is_densified_between_keyframes(self):
        # job_frames goes through dataset_manager precisely so tracks are
        # interpolated; a raw LabeledShape-only query would leave frame 1 (no
        # keyframe there) with nothing for this object.
        project = self.job.segment.task.project
        car = models.Label.objects.create(
            project=project, name="car", type="rectangle", color="#123456"
        )
        track = models.LabeledTrack.objects.create(
            job=self.job, label=car, frame=0, group=0, source="manual"
        )
        models.TrackedShape.objects.create(
            track=track,
            frame=0,
            type="rectangle",
            points=[0.0, 0.0, 10.0, 10.0],
            occluded=False,
            outside=False,
        )
        models.TrackedShape.objects.create(
            track=track,
            frame=3,
            type="rectangle",
            points=[30.0, 30.0, 40.0, 40.0],
            occluded=False,
            outside=False,
        )

        body = self._frames(self.admin, frame_from=0, frame_to=3).json()
        frame1 = next(f for f in body["frames"] if f["frame"] == 1)
        car_obj = next(o for o in frame1["objects"] if o["label"] == "car")
        self.assertIn("track_id", car_obj)  # confirms it came from a track, not a plain shape
        for got, want in zip(car_obj["points"], [10.0, 10.0, 20.0, 20.0]):
            self.assertAlmostEqual(got, want, places=3)

    def test_a_skeleton_shape_returns_its_elements(self):
        # Every other object in this suite is a flat points shape; the viewer's
        # primary object type is a skeleton with per-keypoint elements.
        parent = models.LabeledShape.objects.create(
            job=self.job,
            label=self.labels["person"],
            frame=0,
            type="skeleton",
            points=[],
            occluded=False,
            outside=False,
            z_order=0,
            group=0,
            rotation=0.0,
            source="manual",
        )
        models.LabeledShape.objects.create(
            job=self.job,
            label=self.labels["nose"],
            frame=0,
            type="points",
            parent=parent,
            points=[5.0, 5.0],
            occluded=False,
            outside=False,
            z_order=0,
            group=0,
            rotation=0.0,
            source="manual",
        )
        models.LabeledShape.objects.create(
            job=self.job,
            label=self.labels["eye"],
            frame=0,
            type="points",
            parent=parent,
            points=[6.0, 6.0],
            occluded=False,
            outside=False,
            z_order=0,
            group=0,
            rotation=0.0,
            source="manual",
        )

        body = self._frames(self.admin, frame_from=0, frame_to=0).json()
        skeleton_obj = next(o for o in body["frames"][0]["objects"] if o["label"] == "person")
        self.assertEqual(
            {element["label"] for element in skeleton_obj["elements"]}, {"nose", "left_eye"}
        )

    def test_job_frames_and_a_stored_snapshot_frame_share_the_same_keys(self):
        # One renderer draws both past and present: a job_frames frame and a
        # stored JobAnnotationSnapshotFrame's data must have the same key set.
        snapshot = models.JobAnnotationSnapshot.objects.create(
            job=self.job,
            trigger=models.JobSnapshotTrigger.SUBMITTED,
            from_stage="annotation",
            from_state="in progress",
            to_stage="annotation",
            to_state="completed",
            transitioned_at=timezone.now(),
        )
        captured = {frame["frame"]: frame for frame in build_job_snapshot_frames(self.job)}
        stored = models.JobAnnotationSnapshotFrame.objects.create(
            snapshot=snapshot, frame=1, data=captured[1]
        )

        body = self._frames(self.admin, frame_from=1, frame_to=1).json()
        self.assertEqual(set(body["frames"][0]), set(stored.data))

    def test_range_is_validated(self):
        for params in (
            {"frame_from": 0, "frame_to": 20},  # 21 frames
            {"frame_from": 2, "frame_to": 1},
            {"frame_from": 0},
        ):
            with self.subTest(params=params):
                self.assertEqual(
                    self._frames(self.admin, **params).status_code,
                    status.HTTP_400_BAD_REQUEST,
                )

    def test_admin_only_and_missing_job_is_404(self):
        self.assertEqual(
            self._get_request(
                f"{FRAMES}/99999999", self.admin, query_params={"frame_from": 0, "frame_to": 0}
            ).status_code,
            status.HTTP_404_NOT_FOUND,
        )
        self.assertEqual(
            self._frames(self.user, frame_from=0, frame_to=0).status_code,
            status.HTTP_403_FORBIDDEN,
        )
