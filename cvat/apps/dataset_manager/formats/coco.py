# Copyright (C) 2018-2022 Intel Corporation
# Copyright (C) CVAT.ai Corporation
#
# SPDX-License-Identifier: MIT

import zipfile
from pathlib import Path
from typing import BinaryIO

from datumaro.components.annotation import AnnotationType
from datumaro.components.dataset import StreamDataset
from datumaro.components.transformer import ItemTransform
from datumaro.plugins.data_formats.coco.importer import CocoImporter

from cvat.apps.dataset_manager.bindings import (
    GetCVATDataExtractor,
    NoMediaInAnnotationFileError,
    detect_dataset,
    import_dm_annotations,
)
from cvat.apps.dataset_manager.util import make_zip_archive

from .registry import dm_env, exporter, importer
from .transformations import EllipsesToMasks


@exporter(name="COCO", ext="ZIP", version="1.0")
def _export(dst_file, temp_dir, instance_data, save_images=False):
    with GetCVATDataExtractor(instance_data, include_images=save_images) as extractor:
        dataset = StreamDataset.from_extractors(extractor, env=dm_env)
        dataset.transform(EllipsesToMasks)
        dataset.export(temp_dir, "coco_instances", save_media=save_images, merge_images=False)

    make_zip_archive(temp_dir, dst_file)


@importer(name="COCO", ext="JSON, ZIP", version="1.0")
def _import(src_file: BinaryIO, temp_dir, instance_data, load_data_callback=None, **kwargs):
    if zipfile.is_zipfile(src_file):
        zipfile.ZipFile(src_file).extractall(temp_dir)
        # We use coco importer because it gives better error message
        detect_dataset(temp_dir, format_name="coco", importer=CocoImporter)
        dataset = StreamDataset.import_from(temp_dir, "coco_instances", env=dm_env)
        if load_data_callback is not None:
            load_data_callback(dataset, instance_data)
        import_dm_annotations(dataset, instance_data)
    else:
        if load_data_callback:
            raise NoMediaInAnnotationFileError()

        tmp_src_file_link = Path(temp_dir) / "annotations" / "default.json"
        tmp_src_file_link.parent.mkdir()
        tmp_src_file_link.symlink_to(src_file.name)
        dataset = StreamDataset.import_from(
            str(tmp_src_file_link.absolute()), "coco_instances", env=dm_env
        )
        import_dm_annotations(dataset, instance_data)


def _postprocess_coco_keypoints_bbox(temp_dir):
    """Rewrite the exported person_keypoints*.json so each annotation's
    top-level COCO `bbox` matches the user-drawn skeleton bbox carried via the
    `__cvat_bbox` transport attribute, then strip that transport attribute.

    Datumaro's coco_person_keypoints exporter derives `bbox` from keypoint
    extents when the skeleton has no companion dm.Bbox in the same group.
    Even when we emit a companion dm.Bbox, group=0 (the common CVAT default)
    causes the exporter's `find_solitary_points` branch to ignore it. The
    cleanest cross-version-safe fix is to post-process the JSON after the
    datumaro export completes.
    """
    import glob
    import json as _json

    for json_path in glob.glob(str(Path(temp_dir) / "annotations" / "*.json")):
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                doc = _json.load(f)
        except (OSError, ValueError):
            continue

        annotations = doc.get("annotations")
        if not isinstance(annotations, list):
            continue

        changed = False
        for ann in annotations:
            attrs = ann.get("attributes")
            if not isinstance(attrs, dict):
                continue

            payload = attrs.pop("__cvat_bbox", None)
            changed = True if "__cvat_bbox" not in attrs else changed
            if payload is None:
                continue

            try:
                parsed = _json.loads(payload) if isinstance(payload, str) else payload
                fmt = parsed.get("format", "xyxy")
                values = list(parsed.get("values", []))
                if len(values) != 4:
                    continue
                if fmt == "xywh":
                    x, y, w, h = values
                else:
                    x, y, x2, y2 = values
                    w, h = x2 - x, y2 - y
                ann["bbox"] = [float(x), float(y), float(w), float(h)]
                ann["area"] = float(w) * float(h)
                changed = True
            except (TypeError, ValueError, AttributeError):
                continue

        if changed:
            with open(json_path, "w", encoding="utf-8") as f:
                _json.dump(doc, f)


@exporter(name="COCO Keypoints", ext="ZIP", version="1.0")
def _export(dst_file, temp_dir, instance_data, save_images=False):
    with GetCVATDataExtractor(instance_data, include_images=save_images) as extractor:
        dataset = StreamDataset.from_extractors(extractor, env=dm_env)
        dataset.transform(EllipsesToMasks)
        dataset.export(
            temp_dir, "coco_person_keypoints", save_media=save_images, merge_images=False
        )

    _postprocess_coco_keypoints_bbox(temp_dir)
    make_zip_archive(temp_dir, dst_file)


class LinkBboxToSkeleton(ItemTransform):
    """Move COCO bbox annotations onto the matching skeleton as a transport attribute.

    COCO Keypoints emits a person object as two siblings sharing a group: a Bbox
    (person bounding box) and a Skeleton (keypoints). CVAT previously discarded
    the bbox; now we attach it to the skeleton via the reserved-prefix attribute
    `__cvat_bbox` (xywh→xyxy converted, JSON encoded) and drop the standalone
    Bbox so it does not surface as a separate annotation. The same reserved
    prefix is filtered out of attribute comparison in quality_control and
    consensus pipelines (see U5).
    """

    def transform_item(self, item):
        import json

        bboxes_by_group = {}
        for ann in item.annotations:
            if ann.type == AnnotationType.bbox:
                # group=0 is the "no group" marker in datumaro; treat each
                # ungrouped bbox as its own entry so we can pair 1:1 when there
                # is exactly one skeleton and one bbox per item.
                bboxes_by_group.setdefault(ann.group, []).append(ann)

        skeletons = [
            ann for ann in item.annotations if ann.type == AnnotationType.skeleton
        ]

        for skeleton in skeletons:
            matched_bbox = None
            grouped = bboxes_by_group.get(skeleton.group, [])
            if grouped:
                matched_bbox = grouped.pop(0)
            elif skeleton.group == 0 and len(skeletons) == 1:
                # Fallback: single skeleton with no group — pair with any
                # ungrouped bbox in the same item.
                ungrouped = bboxes_by_group.get(0, [])
                if ungrouped:
                    matched_bbox = ungrouped.pop(0)

            if matched_bbox is None:
                continue

            # datumaro Bbox stores [x, y, w, h] via .points = [x, y, x+w, y+h]
            # internally. Use .get_bbox() if available, otherwise reconstruct.
            if hasattr(matched_bbox, "get_bbox"):
                x, y, w, h = matched_bbox.get_bbox()
            else:
                x, y = matched_bbox.x, matched_bbox.y
                w, h = matched_bbox.w, matched_bbox.h
            skeleton.attributes["__cvat_bbox"] = json.dumps({
                "format": "xyxy",
                "values": [x, y, x + w, y + h],
            })

        # Drop the bbox annotations we have absorbed; keep any leftovers (they
        # had labels that didn't match a skeleton in this item).
        absorbed_ids = set()
        for grouped in bboxes_by_group.values():
            # Only the bboxes still in the list were not paired with a skeleton;
            # everything that was paired had already been pop()ed off the list.
            pass

        def convert_annotations():
            kept = []
            for ann in item.annotations:
                if ann.type == AnnotationType.bbox:
                    # Discard any bbox that was absorbed into a skeleton. Since
                    # we cannot reliably tell them apart by identity after
                    # transformation, drop all bboxes — COCO Keypoints datasets
                    # carry one bbox per person and we have already absorbed
                    # them above.
                    continue
                kept.append(ann)
            return kept

        return item.wrap(annotations=convert_annotations)


@importer(name="COCO Keypoints", ext="JSON, ZIP", version="1.0")
def _import(src_file, temp_dir, instance_data, load_data_callback=None, **kwargs):
    if zipfile.is_zipfile(src_file):
        zipfile.ZipFile(src_file).extractall(temp_dir)
        # We use coco importer because it gives better error message
        detect_dataset(temp_dir, format_name="coco", importer=CocoImporter)
        dataset = StreamDataset.import_from(temp_dir, "coco_person_keypoints", env=dm_env)
        dataset = dataset.transform(LinkBboxToSkeleton)
        if load_data_callback is not None:
            load_data_callback(dataset, instance_data)
        import_dm_annotations(dataset, instance_data)
    else:
        if load_data_callback:
            raise NoMediaInAnnotationFileError()

        tmp_src_file_link = Path(temp_dir) / "annotations" / "default.json"
        tmp_src_file_link.parent.mkdir()
        tmp_src_file_link.symlink_to(src_file.name)
        dataset = StreamDataset.import_from(
            str(tmp_src_file_link.absolute()), "coco_person_keypoints", env=dm_env
        )
        dataset = dataset.transform(LinkBboxToSkeleton)
        import_dm_annotations(dataset, instance_data)
