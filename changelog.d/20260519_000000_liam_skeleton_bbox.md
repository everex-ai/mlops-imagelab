### Added

- Skeleton shape에 1급 `bbox = [xtl, ytl, xbr, ybr]` 필드 추가. annotator가
  처음 그린 회색 박스가 객체 경계로 영속 저장됨. wrapping rect는 더 이상
  매 렌더마다 keypoint min/max + margin으로 계산되지 않고 저장된 값을 그대로
  사용. (`docs/plans/2026-05-19-001-feat-skeleton-bbox-persistence-plan.md`)
- COCO Keypoints import가 `annotations[i].bbox` (xywh)를 skeleton bbox로
  보존. 이전에는 `RemoveBboxAnnotations` transformer가 강제로 폐기했음.
- COCO Keypoints export 시 skeleton bbox에서 person bbox annotation을 동반
  emit해 표준 COCO Keypoints round-trip 무손실.

### Changed

- **\[Breaking — write 경로\]** skeleton 생성/수정 REST 요청 (POST/PATCH
  `/api/jobs/<id>/annotations`)에 `bbox` 필드가 필수. 누락 시 400.
  기존 SDK 클라이언트가 skeleton을 생성하는 자동화 스크립트는 SDK 메이저
  버전 bump가 필요. 응답만 읽는 read-only 클라이언트는 호환 (필드 추가만).
- skeleton 유효 bbox 상태는 둘 중 하나로 정의:
  - **Normal** — `[xtl, ytl, xbr, ybr]` with `xtl<xbr and ytl<ybr` (annotator
    가 그린 객체 경계)
  - **Degenerate** — 정확히 `[0, 0, 0, 0]` (모든 element가 `outside=true`인
    드문 케이스; migration backfill에서만 발생, 첫 정상 편집 시 자동 회복)
  - 그 외 입력 (zero-area non-degenerate, 역전된 좌표, 빈 배열)은 모두 400.
- skeleton 회전 의미 변경: 기존엔 `Shape.rotation`을 항상 0으로 강제하고
  child keypoint 좌표를 직접 회전시켰음. 이제 `Shape.rotation`이 의미 있는
  스칼라로 보존되고, child keypoint는 변형되지 않으며, 캔버스가 SVG
  transform으로 시각적 회전을 처리. 데이터셋 export (CVAT XML, COCO,
  Datumaro)도 skeleton rotation을 보존.
- skeleton 빨간 박스 corner/edge 핸들 드래그가 **bbox만** 변경하도록 의미
  재정의. 이전엔 모든 keypoint를 박스 변화에 비례해 스케일했음. line 드래그
  (테두리 잡기)는 기존 동작 유지 — bbox + keypoints가 함께 평행이동.
- skeleton keypoint를 박스 밖으로 이동시키면 bbox가 그 keypoint 좌표까지
  자동 확장 (soft-snap, 0px margin). bbox 리사이즈로 keypoint를 못 담게
  되면 outermost visible/occluded keypoint까지로 자동 clamp. `outside=true`
  keypoint는 두 검증 모두에서 제외.
- skeleton track의 frame 간 bbox는 선형 보간되어 표시. 보간 frame에서
  사용자가 bbox를 수정하면 그 frame이 자동으로 새 keyframe으로 격상됨
  (implicit keyframe — keypoint 수정과 동일한 패턴).
- Migration `0098_add_skeleton_bbox`: 모든 LabeledShape/TrackedShape에 bbox
  컬럼 추가 후 기존 skeleton row를 element keypoint min/max ± 20px로
  chunked backfill (5,000 row/batch). production DB 약 673,870 skeleton
  parent row 기준 약 10-20분 소요 예상. **배포 시 약 30분 read-only
  maintenance window 권장** (annotation write API 차단, RQ worker 일시 정지).

### Fixed

- Datumaro IR을 통한 skeleton transport에서 reserved-prefix attribute
  `__cvat_bbox` 사용. `quality_control` 의 `ignored_attrs` 와
  `consensus` merge 경로에서 이 attribute를 자동 제외해 transport metadata
  가 `MISMATCHING_ATTRIBUTES` conflict를 만들지 않음.

### Removed

- `cvat/apps/dataset_manager/formats/coco.py` 의 `RemoveBboxAnnotations`
  transformer 폐기. 대체 `LinkBboxToSkeleton`이 person bbox를 그룹 키
  (또는 image당 단일 skeleton 폴백)로 매칭해 skeleton attribute에 흡수.
