# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

"""Add bbox field to Shape (LabeledShape, TrackedShape) and backfill skeleton rows.

Skeleton parents previously had no persisted object bbox; the wrapping rectangle
was recomputed on the canvas each render. This migration introduces a first-class
`bbox = [xtl, ytl, xbr, ybr]` field and backfills it for every existing skeleton
parent from its child element coordinates (visible + occluded keypoints only;
outside keypoints are excluded because their coordinates are meaningless).

Backfill margin: 20px on each side, matching the pre-existing canvas
SKELETON_RECT_MARGIN so visual continuity is preserved.

If every child is outside, the parent's bbox becomes the degenerate state
[0, 0, 0, 0], which the serializer accepts as a valid state. Annotators
normalize it on their next edit.

Chunked in 5,000-row batches keyed by parent id range to keep transaction
size bounded on tables with ~644k skeleton parents.
"""

import cvat.apps.engine.models
from django.db import migrations


CHUNK_SIZE = 5_000
MARGIN = 20.0


def _backfill_table(parent_qs, child_qs_for_parents, table_label, common_logger):
    """Backfill bbox for one table (LabeledShape or TrackedShape).

    parent_qs:               queryset of skeleton parents on the table
    child_qs_for_parents:    callable(chunk_ids) -> queryset of children for those parents
    table_label:             string for logging
    """
    total = parent_qs.count()
    if total == 0:
        common_logger.info(f"[{table_label}] no skeleton rows to backfill")
        return

    common_logger.info(f"[{table_label}] backfilling {total} skeleton rows")

    parent_ids = list(parent_qs.values_list("id", flat=True))
    processed = 0
    for offset in range(0, len(parent_ids), CHUNK_SIZE):
        chunk_ids = parent_ids[offset : offset + CHUNK_SIZE]

        # Fetch children for this chunk; exclude outside (their coordinates are meaningless).
        # Group by parent in Python — element points are stored as a single comma-separated
        # text field, so SQL-side aggregation is not straightforward.
        children = child_qs_for_parents(chunk_ids).exclude(outside=True).only(
            "parent_id", "points"
        )

        # Bucket children by parent.
        by_parent = {}
        for child in children.iterator():
            by_parent.setdefault(child.parent_id, []).append(child.points)

        # Compute bbox per parent and update.
        updates = []
        for parent_id in chunk_ids:
            element_points_list = by_parent.get(parent_id, [])
            xs = []
            ys = []
            for points in element_points_list:
                # points is a flat sequence of x,y pairs (FloatArrayField/LazyList).
                point_seq = list(points)
                for i in range(0, len(point_seq), 2):
                    xs.append(point_seq[i])
                    if i + 1 < len(point_seq):
                        ys.append(point_seq[i + 1])

            if xs and ys:
                bbox = [min(xs) - MARGIN, min(ys) - MARGIN, max(xs) + MARGIN, max(ys) + MARGIN]
            else:
                # All elements outside or no children — degenerate state.
                bbox = [0.0, 0.0, 0.0, 0.0]

            updates.append((parent_id, bbox))

        # Apply updates in a single batch using model.objects.filter(...).update(...) per row.
        # bulk_update would be ideal but FloatArrayField serialization through bulk_update
        # has historically been finicky; per-row update is safe and still bounded.
        Parent = parent_qs.model
        for parent_id, bbox in updates:
            Parent.objects.filter(id=parent_id).update(bbox=bbox)

        processed += len(chunk_ids)
        if (offset // CHUNK_SIZE) % 20 == 0:
            common_logger.info(f"[{table_label}] {processed}/{total} done")

    common_logger.info(f"[{table_label}] backfill complete: {processed}/{total}")


def backfill_skeleton_bbox(apps, schema_editor):
    LabeledShape = apps.get_model("engine", "LabeledShape")
    TrackedShape = apps.get_model("engine", "TrackedShape")

    # Inline logger so failures in the migration_logger helper don't block this migration.
    import logging
    common_logger = logging.getLogger("migration_0098")
    common_logger.setLevel(logging.INFO)

    _backfill_table(
        parent_qs=LabeledShape.objects.filter(type="skeleton"),
        child_qs_for_parents=lambda ids: LabeledShape.objects.filter(parent_id__in=ids),
        table_label="LabeledShape",
        common_logger=common_logger,
    )
    _backfill_table(
        parent_qs=TrackedShape.objects.filter(type="skeleton"),
        child_qs_for_parents=lambda ids: TrackedShape.objects.filter(parent_id__in=ids),
        table_label="TrackedShape",
        common_logger=common_logger,
    )


class Migration(migrations.Migration):

    dependencies = [
        ("engine", "0097_drop_legacy_analytics_report"),
    ]

    operations = [
        migrations.AddField(
            model_name="labeledshape",
            name="bbox",
            field=cvat.apps.engine.models.FloatArrayField(default=list),
        ),
        migrations.AddField(
            model_name="trackedshape",
            name="bbox",
            field=cvat.apps.engine.models.FloatArrayField(default=list),
        ),
        migrations.RunPython(
            backfill_skeleton_bbox,
            reverse_code=migrations.RunPython.noop,
        ),
    ]
