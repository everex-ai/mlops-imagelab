---
title: "feat: Persist skeleton bbox as a first-class field"
type: feat
status: active
created: 2026-05-19
origin: docs/brainstorms/2026-05-19-skeleton-bbox-requirements.md
scope: standard
target_repo: cvat-everex
---

# feat: Persist skeleton bbox as a first-class field

## Summary

Skeleton shape에 axis-aligned `bbox = [xtl, ytl, xbr, ybr]` 필드를 1급 데이터로 추가한다. 회전은 기존 `Shape.rotation` 재활용. annotator가 그린 객체 경계를 영속화하고, COCO Keypoints의 `annotations[i].bbox`와 round-trip을 보장한다. 기존 643,945 skeleton parent row + 29,925 TrackedShape skeleton row를 chunked migration으로 backfill한다.

(see origin: [docs/brainstorms/2026-05-19-skeleton-bbox-requirements.md](../brainstorms/2026-05-19-skeleton-bbox-requirements.md))

---

## Problem Frame

현재 skeleton shape는 wrapping rect를 frontend에서만 매번 `min/max + 20px` 으로 즉석 계산하고 (cvat-canvas/src/typescript/canvasView.ts:3895-3919), 어디에도 저장하지 않는다. 결과:

1. annotator가 처음 그린 회색 박스(=객체 경계)가 휘발됨.
2. COCO Keypoints import에서 `RemoveBboxAnnotations` 가 bbox를 강제로 폐기 (cvat/apps/dataset_manager/formats/coco.py:72-79).
3. export 시 bbox는 elements에서 자동 derive되어 사용자 의도와 분리됨.

이를 해결하기 위해 skeleton에만 의미 있는 `bbox` 컬럼을 `Shape` abstract 모델에 추가하고, 직렬화 경로 전반에서 `points`와 동등한 1급 시민으로 흐르게 한다.

---

## Requirements Traceability

| R-ID | 요구 (from origin) | 추적 단위 |
|---|---|---|
| R1 | skeleton 새로 그리면 bbox가 DB에 저장 | U2, U6, U7 |
| R2 | bbox 단독 드래그/리사이즈, keypoints 영향 없음 | U7 |
| R3 | keypoint 이동이 bbox를 변경하지 않음 (soft snap 예외) | U7 |
| R4 | COCO Keypoints round-trip 보존 | U9 |
| R5 | 기존 673,870 skeleton row를 합리적 bbox 값으로 migrate | U3 |
| R6 | Migration 30분 이내 완료 | U3 |
| R7 | SDK 응답 스키마에 `bbox` 노출. **요청 측은 breaking change**: skeleton POST에 bbox 필수 (구 SDK는 skeleton 생성 시 400). 응답을 단순 read만 하는 기존 클라이언트는 무손상. | U2, U9, U10 |

---

## Key Technical Decisions

- **신규 필드 vs `points` 재활용**: 신규 `bbox` 필드 채택. rectangle/polygon 등과의 의미 충돌 회피. `points`는 skeleton에서 빈 배열 유지(serializer validator 호환).
- **저장 위치**: `Shape` abstract model에 `bbox = FloatArrayField(default=list)`. `LabeledShape`, `TrackedShape` 자동 상속. text 컬럼 직렬화 (`points`와 동일 메커니즘).
- **NOT NULL 정책**: `default=list`로 컬럼 자체는 NULL 없음. 의미적 NOT NULL은 **serializer-level validation**으로 강제. 단 invariant를 모든 producer와 일관시키기 위해 skeleton의 **유효 상태를 두 가지로 정의**:
  - **Normal**: `len(bbox)==4 and xtl<xbr and ytl<ybr` — annotator가 그렸거나 정상 backfill된 경우.
  - **Degenerate**: `bbox == [0,0,0,0]` — 모든 element가 outside인 매우 드문 케이스 (migration backfill에서만 발생). serializer는 이 상태도 허용 (이후 첫 정상 편집 시 정상화됨).
  - `bbox==[]` 는 **금지** — non-skeleton에서만 빈 배열. skeleton은 반드시 위 둘 중 하나.
  - **API 요청 측 정책 (breaking change)**: skeleton POST/PATCH에 bbox 필수. 누락 시 400. 구 SDK 클라이언트가 skeleton 생성 시 깨짐 — release notes에 명시. 응답 측은 항상 위 두 형식 중 하나로 채워진 4-element 반환 (read-only 클라이언트 무손상).
- **회전**: 기존 `Shape.rotation` (double precision) 재활용. bbox는 axis-aligned로만 저장 → 사다리꼴 불가.
- **Migration 전략**: AddField → chunked RunPython backfill → migration 단일 파일 내 완결. Chunk 크기 5,000 parent row. parent_id 인덱스 활용한 `elements` self-join. 추정 10-20분.
- **운영 정책**: Migration 동안 read-only window. cvat_server는 동작 유지하되 annotation write API 차단 권장. RQ worker(import/export/annotation)는 일시 정지. release notes에 maintenance window 명시.
- **Backfill 정책**: visible+occluded element만 사용 (outside 제외), `[min_x-20, min_y-20, max_x+20, max_y+20]`. 기존 wrapping margin 20px 유지로 시각적 연속성 확보.
- **Soft-snap perf**: dragmove 마다 24 keypoint 순회 O(n) 비용은 무시 가능 (현재 setupSkeletonEdges도 dragmove마다 호출됨).
- **Datumaro bbox 운반**: `attributes['bbox']` 에 JSON 직렬화하여 운반 — datumaro 패키지 수정 없이 CVAT 양 끝단에서 인식.
- **COCO `[x, y, w, h]` ↔ CVAT `[xtl, ytl, xbr, ybr]`** 변환: `xbr = x+w`, `ybr = y+h`.

---

## High-Level Technical Design

> *This illustrates the intended approach and is directional guidance for review, not implementation specification.*

```text
Backend (Django/DRF)
  Shape (abstract)
    + bbox: FloatArrayField(default=list)   <-- 신규
    points, rotation, occluded, outside, z_order
  ↓
  LabeledShape / TrackedShape  (자동 상속)
  ↓
  ShapeSerializer.validate(): if type==SKELETON => len(bbox)==4, else bbox==[]
  LabeledShapeSerializerFromDB.convert_shape(): keys += ['bbox']
  LabeledTrackSerializerFromDB.convert_track(): shape_keys += ['bbox']

Migration 0098_add_skeleton_bbox.py
  Operations:
    1) AddField(Shape.bbox, default=list)            # online, fast
    2) RunPython(backfill_skeleton_bbox, reverse=noop)  # chunked
       - LabeledShape parent (type='skeleton') 5k씩 ID 범위로 fetch
       - 각 parent마다 elements (visible+occluded) 조회 → min/max±20 계산
       - TrackedShape 동일 처리

Dataset Manager
  formats/cvat.py
    Import (line 316): skeleton인 경우 box attrs → shape['bbox'] = [xtl,ytl,xbr,ybr]
    Export (line 969): open_skeleton(dump_data) 호출 시 dump_data에 bbox 포함
                       → cvat/apps/dataset_manager/formats/cvat.py dumper.open_skeleton 갱신
  formats/coco.py
    Import (line 89, 103): RemoveBboxAnnotations 제거 → bbox annotation을 skeleton.bbox에 매핑
    Export (datumaro의 coco_person_keypoints): bindings.py converter가 skeleton.bbox를
           attributes['bbox']로 운반 → coco 어댑터가 person bbox로 작성
  bindings.py
    CvatToDmAnnotationConverter._convert_shape: skeleton이면 attributes['bbox']=JSON 추가
    import_dm_annotations: dm Skeleton.attributes['bbox'] (또는 인접한 bbox annotation) → bbox 인자
    LabeledShape 생성 (line 2144): bbox=bbox 인자 추가

cvat-core (TypeScript)
  server-response-types.ts / server-request-types.ts
    SerializedShape, SerializedTrack: + bbox?: number[]
  annotations-objects.ts (SkeletonShape, SkeletonTrack)
    toJSON(): skeleton일 때 bbox 포함
    saveBbox(bbox, frame): keypoints처럼 별도 setter (TrackedShape용 implicit keyframe 패턴)
  object-state.ts
    + bbox getter/setter (skeleton일 때만 4-element, 그 외 null)
  annotations-saver.ts
    JSON_SERIALIZER_KEYS에 'bbox' 추가
  object-utils.ts:372,388 / annotations-collection.ts:317,376,536,681
    skeleton 분기에서 bbox 운반 (points는 null 강제 유지)

cvat-canvas (TypeScript)
  canvasView.ts:3906-3919 setupSkeleton
    wrappingRect = state.bbox (저장값) → fallback: computeWrappingBox(elements,20)
  canvasView.ts:1277-1340 draggable (line 드래그)
    skeleton: 기존대로 line 드래그 = 전체 평행이동
    onDragEnd: bbox + element points 모두 ObjectState로 emit
  canvasView.ts:1582-1618 resizable (corner/edge 핸들)
    신규 모드: skeleton resize 시 element points 비례 스케일 코드 제거
    bbox 좌표만 갱신 → ObjectState에 bbox만 emit (keypoints 변경 안 함)
  신규: keypoint drag end 시 soft-snap 계산 (bbox가 outermost visible+occluded keypoint 포함하도록 자동 확장)
  신규: bbox 리사이즈 중 outermost keypoint를 못 담는 좌표 입력 시 clamp
```

---

## Output Structure

신규 파일은 적은 편이며 기존 파일 수정 위주. 신규 추가:

```text
cvat/apps/engine/migrations/
  0098_add_skeleton_bbox.py        # AddField + RunPython chunked backfill

cvat/apps/dataset_manager/tests/
  test_skeleton_bbox.py            # COCO/CVAT XML round-trip + migration backfill 검증

tests/python/rest_api/
  test_skeleton_bbox.py            # API-level round-trip + validation
```

기존 파일은 in-place 수정. 신규 frontend test는 기존 unit 테스트 위치에 추가 (cvat-canvas에는 활성 단위 테스트 디렉터리 없음 — 통합 시점 검증 의존).

---

## Scope Boundaries

### In Scope
- `Shape.bbox` 컬럼 추가, migration 및 backfill
- Serializer / direct-from-DB serializer / SDK schema 노출
- CVAT XML / COCO Keypoints round-trip (bindings.py 포함)
- cvat-core 직렬화/역직렬화/saver dirty tracking
- cvat-canvas: wrapping rect를 bbox 저장값으로 전환, drag/resize 의미 재정의, soft-snap, clamp
- API/format round-trip 테스트, backfill 검증 테스트

### Outside this product's identity (from origin)
- skeleton bbox에 confidence/score 등 추가 메타
- 다른 shape (rectangle, polygon)에 wrapping 추가
- 새로운 keypoint visibility 모델
- 3D skeleton 지원

### Deferred for later (from origin)
- Quality reports / consensus 매칭 metric에 bbox IoU 통합
- Datumaro 외부 consumer를 위한 datumaro 패키지 자체 변경

### Deferred to Follow-Up Work
- UI: details sidebar에서 bbox 좌표 수치 표시/입력 (현재 plan은 canvas 조작만)
- Bbox auto-resize 마진을 라벨별로 설정 가능하게 (현재 plan은 0px 고정)
- Skeleton 전체 이동 전용 단축키/버튼 (현재 plan은 line 드래그로 충분)

---

## Implementation Units

### U1. Migration 영향도 측정 SQL 실행 및 검증

**Goal:** Migration 실행 전 production DB에 대해 실제 영향 범위와 인덱스 상태를 측정해서 chunk 크기, 운영 윈도우, fallback 전략을 확정.

**Requirements:** R5, R6
**Dependencies:** —
**Files:** (코드 변경 없음 — 운영 산출물)

**Approach:**
- 사용자가 production DB(또는 staging clone)에서 측정 SQL 실행:
  - `SELECT COUNT(*) FROM engine_trackedshape WHERE parent_id IS NOT NULL` (TrackedShape children)
  - `EXPLAIN ANALYZE SELECT MIN(...) FROM engine_labeledshape WHERE parent_id IN (SELECT id FROM engine_labeledshape WHERE type='skeleton' LIMIT 5000)` (chunk 성능 확인)
  - `SELECT id FROM engine_labeledshape WHERE type='skeleton' ORDER BY id LIMIT 1 OFFSET 643944` (max id 확인)
- 결과를 plan에 주석으로 기록.
- staging clone에 0098 migration dry-run 후 실제 소요 시간 측정.

**Test scenarios:** *Test expectation: none -- 운영 측정 단계, 검증은 U3의 migration 테스트가 담당.*

**Verification:**
- TrackedShape children row 수 확인됨
- 5,000 row chunk 1회 backfill이 < 30초임이 staging에서 입증
- 전체 migration 소요시간이 < 30분으로 추정됨

---

### U2. Backend 모델 + Serializer: `Shape.bbox` 필드 추가

**Goal:** Django 모델, DRF serializer, direct-from-DB serializer에 `bbox` 필드를 노출하고 skeleton 전용 validation 규칙을 적용. SDK schema 자동 갱신.

**Requirements:** R1, R7
**Dependencies:** U1 (영향 측정 완료)
**Files:**
- cvat/apps/engine/models.py (`Shape` abstract: bbox 필드 추가, 1187-1197)
- cvat/apps/engine/serializers.py (`ShapeSerializer` 3232-3270, `LabeledShapeSerializer` 3275-3294, `TrackedShapeSerializer` 3352, `LabeledShapeSerializerFromDB.convert_shape` 3316-3330, `LabeledTrackSerializerFromDB.convert_track` 3332-3350)
- cvat/schema.yml (자동생성, `python manage.py spectacular` 결과 커밋)
- tests/python/rest_api/test_skeleton_bbox.py (신규)

**Approach:**
- `Shape` abstract: `bbox = FloatArrayField(default=list, help_text="[xtl, ytl, xbr, ybr] for skeleton; empty otherwise")`.
- `ShapeSerializer`: `bbox = OptimizedFloatListField(allow_empty=True, required=False)` 추가.
- `validate()` 분기에 skeleton 케이스 강화 — **유효 상태는 정확히 두 가지**:
  - **Normal**: `len(bbox) == 4 and xtl < xbr and ytl < ybr` (strict, equal 제외).
  - **Degenerate**: `bbox == [0, 0, 0, 0]` (정확히 이 값만 허용 — migration backfill의 all-outside skeleton 케이스).
  - 그 외 모든 입력 (`bbox==[]`, `len!=4`, `xtl==xbr`, `xtl>xbr`, `[0,0,0,0]`이 아닌 zero-area 등) → 400.
  - 그 외 shape type: `len(bbox) == 0` 강제.
- `LabeledShapeSerializerFromDB.convert_shape`: `_convert_annotation` 키 리스트에 `'bbox'` 추가.
- `LabeledTrackSerializerFromDB.convert_track`: `shape_keys` 리스트에 `'bbox'` 추가.
- skeleton 자식 element는 bbox=[] 유지 (parent만 가짐).
- Schema 재생성: `docker run --rm cvat/server:dev python manage.py spectacular > cvat/schema.yml`.

**Patterns to follow:**
- `points` 필드 처리 전반 (validate 분기, FromDB serializer 키 리스트).

**Execution note:** Migration이 없는 상태로 serializer만 먼저 만들면 기존 row의 `bbox` 컬럼 부재로 직렬화가 깨진다. U2와 U3는 같은 PR에서 동시 머지.

**Test scenarios:**

POST (create) 경로:
- Covers R1. POST skeleton with `bbox=[10,20,100,200]` → 200 OK, 응답에 `bbox` 동일 값.
- Covers R7. POST skeleton **bbox 필드 누락** → 400 (skeleton requires bbox).
- Covers R7. POST skeleton with `bbox=[]` → 400 (skeleton requires 4-element bbox).
- POST skeleton with `bbox=[100,200,10,20]` (xbr<xtl) → 400.
- POST skeleton with `bbox=[10,10,10,20]` (xtl==xbr, zero width, **non-degenerate**) → 400.
- POST skeleton with `bbox=[10,20,10,20]` (zero area, non-degenerate) → 400.
- POST skeleton with `bbox=[0,0,0,0]` → 200 OK (정확히 degenerate state).
- POST rectangle with `bbox=[1,2,3,4]` → 400 (non-skeleton must have empty bbox).
- POST rectangle **bbox 누락** → 200 OK (additive for non-skeleton).

PATCH (update) 경로 — **신규 명시**:
- Covers R7. 기존 skeleton (bbox 있음) PATCH **bbox 누락** → 400 (PATCH도 동일 validator 적용).
- Covers R7. 기존 skeleton PATCH `bbox=[20,30,200,300]` → 200 OK, 저장된 값 갱신.
- 기존 skeleton (Normal bbox) → PATCH `bbox=[0,0,0,0]` (degenerate로 회귀) → 200 OK (의도된 회귀 케이스, all-outside 상태 표현 가능).
- 기존 rectangle PATCH bbox 누락 → 200 OK (non-skeleton 무영향).
- TrackedShape PATCH (track의 특정 frame shape 갱신) → 동일 규칙 적용. bbox 누락 시 400.

GET (read) 경로:
- GET skeleton: `bbox` 키가 응답에 포함됨.
- GET task annotations (LabeledShapeSerializerFromDB 경로): skeleton parent에 bbox 포함, child element는 bbox=[].
- LabeledTrack with skeleton frame shapes: 각 frame TrackedShape에 bbox 포함.

**Verification:** API 테스트 통과, cvat/schema.yml diff에 bbox 필드 추가됨.

---

### U3. Migration 0098: AddField + chunked backfill

**Goal:** `bbox` 컬럼을 추가하고 기존 skeleton row 673,870개를 elements 좌표 기반으로 backfill. 단일 migration 파일에서 완결.

**Requirements:** R5, R6
**Dependencies:** U2 (모델 정의가 먼저 있어야 makemigrations 가능)
**Files:**
- cvat/apps/engine/migrations/0098_add_skeleton_bbox.py (신규)
- cvat/apps/engine/migrations/tests/test_0098_skeleton_bbox_backfill.py (신규, optional)
- cvat/apps/dataset_manager/tests/test_skeleton_bbox.py (migration 결과 sanity check)

**Approach:**
- `dependencies = [("engine", "0097_drop_legacy_analytics_report")]`.
- Operations 순서:
  1. `migrations.AddField('labeledshape', 'bbox', FloatArrayField(default=list))` — fast, default 값으로 모든 row 즉시 채워짐.
  2. `migrations.AddField('trackedshape', 'bbox', FloatArrayField(default=list))` — 동일.
  3. `migrations.RunPython(backfill_skeleton_bbox, reverse_code=migrations.RunPython.noop)`.
- `backfill_skeleton_bbox(apps, schema_editor)`:
  - `LabeledShape = apps.get_model('engine', 'LabeledShape')`.
  - `CHUNK = 5000`.
  - skeleton parent id 범위를 5k씩 순회:
    ```text
    for offset in range(0, total, CHUNK):
        chunk = LabeledShape.objects.filter(type='skeleton').order_by('id')[offset:offset+CHUNK]
        chunk_ids = list(chunk.values_list('id', flat=True))
        children = LabeledShape.objects.filter(parent_id__in=chunk_ids).exclude(outside=True)
        # parent_id별로 min/max 계산 (Python 측)
        # parent의 bbox = [min_x-20, min_y-20, max_x+20, max_y+20]
        # bulk_update
    ```
  - TrackedShape도 동일 패턴 (parent는 TrackedShape, children도 TrackedShape).
  - 모든 elements가 outside인 skeleton: bbox = `[0, 0, 0, 0]` (degenerate, 사용자 첫 편집 시 정상화).
  - element의 `points = [x, y]` 또는 더 긴 좌표 배열 — `points[0::2]`가 x, `points[1::2]`가 y.
- Migration 로그 출력: 100 chunk마다 진행률 stdout.

**Patterns to follow:**
- 0097은 단순 RunSQL 패턴이라 직접 참고는 적음. Django 공식 `RunPython` data migration 패턴 따름. 데이터 모델은 `apps.get_model()`로만 접근 (직접 import 금지).

**Test scenarios:**
- Migration unit test (test_0098_skeleton_bbox_backfill.py): 5 skeleton parent (각 24 child point) fixture 생성 → migration 실행 → 각 parent의 bbox가 자식 min/max ± 20px임을 검증.
- outside=True element 1개 포함 fixture: 해당 element는 bbox 계산에서 제외됨을 검증.
- 모든 element가 outside인 edge case: bbox = `[0, 0, 0, 0]` 임을 검증.
- TrackedShape에 대해 동일 검증.
- Reverse migration (`migrate engine 0097`): bbox 컬럼이 사라지고 다른 데이터에 손상 없음.

**Verification:**
- `python manage.py migrate engine 0098` → 정상 종료
- Staging dry-run 시간 < 30분
- Reverse: `python manage.py migrate engine 0097` 정상 동작
- 샘플 100 skeleton row의 bbox가 elements min/max+20 와 정확히 일치

---

### U4. Dataset manager: CVAT XML import/export (annotation + interpolation 양쪽)

**Goal:** CVAT XML round-trip에서 skeleton bbox 보존. `<skeleton xtl=... ytl=... xbr=... ybr=...>` 속성. annotation export(`dump_annotations`)와 interpolation export(`dump_as_cvat_interpolation`) 두 경로 모두 포괄.

**Requirements:** R4
**Dependencies:** U2, U6 (CommonData 명시 named tuple bbox 필드)
**Files:**
- cvat/apps/dataset_manager/formats/cvat.py:
  - Import: `_load_xml` 부근 + `CvatExtractor._parse_shape_ann` line 587-599 (`Skeleton(...)` 생성). 단순 `shape["bbox"]` 키만 두면 datumaro로 전달 안 됨 → **`attributes["bbox"]`에 JSON 직렬화 형태로 운반**해야 `import_dm_annotations` 측에서 인식.
  - Annotation export: `dump_labeled_shapes` skeleton 분기 line 969-993.
  - **Interpolation export** (신규 반영): `dump_as_cvat_interpolation` line 1014 + 내부 `dump_shape` line 1018 + skeleton 케이스 line 1131, 1193. annotation path와 동일하게 bbox attr 출력 필요.
- cvat/apps/dataset_manager/bindings.py: `import_dm_annotations` skeleton 분기에서 `ann.attributes.pop('bbox', None)` 으로 추출 후 LabeledShape `bbox=` 인자에 전달 (U6의 named tuple 변경 의존).
- dumper 모듈: `open_skeleton/close_skeleton` 가 dump_data의 bbox를 xtl/ytl/xbr/ybr attr로 출력하도록. 작업 시 `grep -rn "def open_skeleton"` 으로 위치 식별. `open_box` 패턴 그대로 mirror.
- cvat/apps/dataset_manager/tests/test_skeleton_bbox.py: annotation + interpolation 모두 테스트.

**Approach:**

**Transport channel은 U5와 동일 표준화 사용**: attribute 키 `__cvat_bbox`, 값 `{"format":"xyxy","values":[...]}` JSON. rotation은 기존 attribute `'rotation'` 채널 그대로 (rectangle/ellipse가 이미 사용 중).

- **Import** (`_parse_shape_ann` skeleton 분기):
  ```text
  elif ann_type == "skeleton":
      elements = [cls._parse_shape_ann(e, categories) for e in ann.get("elements", [])]
      if all(k in ann for k in ("xtl","ytl","xbr","ybr")):
          attributes["__cvat_bbox"] = json.dumps({
              "format": "xyxy",
              "values": [float(ann["xtl"]), float(ann["ytl"]),
                         float(ann["xbr"]), float(ann["ybr"])],
          })
      # rotation은 이미 ann["rotation"] → attributes["rotation"] 처리됨 (line 529-530)
      return Skeleton(elements, label=..., attributes=attributes, ...)
  ```
  XML 파싱(`cvat.py:316` 영역)은 `shape["bbox"]`로 임시 추출 후, Skeleton 생성 시점에 `attributes["__cvat_bbox"]` JSON으로 옮긴다.
- **Export (annotation path)** (line 969): dump_data에 `bbox` + `rotation` 키 추가. dumper.open_skeleton이 `xtl/ytl/xbr/ybr` + `rotation` (0이 아닐 때만) attr 출력. rectangle의 `if shape.rotation: dump_data.update(...)` (line 878-881) 패턴 mirror.
- **Export (interpolation path)** (line 1014-1193): tracked skeleton 케이스도 동일 attr 출력 (bbox + rotation). interpolation은 keyframe별 bbox/rotation 사용, 보간 frame은 cvat-core가 이미 보간한 값이 ProjectData/CommonData에 들어와 있으면 그대로 dump.
- **import_dm_annotations** (bindings.py): skeleton 분기에서:
  - `attr_payload = ann.attributes.pop('__cvat_bbox', None)` → JSON 파싱 → `LabeledShape(bbox=values)`. 없으면 `bbox=[0,0,0,0]`.
  - `rotation = ann.attributes.pop('rotation', 0.0)` (line 2099 패턴 이미 존재 — skeleton에도 적용됨을 확인).

**Patterns to follow:**
- `box` import/export 흐름 (cvat.py:304-315, dumper의 `open_box`).
- Datumaro attribute 운반 패턴: bindings.py:2099 `ann.attributes.pop('rotation', 0.0)` 와 동일.

**Test scenarios:**
- Covers R4. **Annotation path**: skeleton(parent) + 24 elements + bbox=[10,20,100,200] 포함 task → CVAT XML export → re-import → 동일 bbox.
- Covers R4. **Interpolation path**: SkeletonTrack 2 keyframe (frame=0 bbox=[0,0,100,100], frame=10 bbox=[100,100,200,200]) → CVAT XML interpolation export → re-import → 각 keyframe bbox 정확히 복원.
- **Rotation round-trip (annotation)**: skeleton with rotation=45° + bbox → export → re-import → rotation 보존.
- **Rotation round-trip (interpolation)**: SkeletonTrack keyframe별 rotation 보존 (frame=0 rot=0, frame=10 rot=90).
- 구 export(bbox attr 없음)를 import → `bbox=[0,0,0,0]` (degenerate) 적재.
- bbox와 elements가 어긋난 경우 그대로 보존 (format round-trip은 user data 우선).
- **Transport attribute leak 검증**: skeleton export → import 후 ObjectState.attributes에 `__cvat_bbox` 키가 leak되지 않음 (pop 동작).

**Verification:** test_skeleton_bbox.py annotation + interpolation round-trip 시나리오 통과 (bbox + rotation 모두).

---

### U5. Dataset manager: COCO Keypoints + Datumaro bbox 운반

**Goal:** COCO Keypoints의 `annotations[i].bbox` 가 skeleton.bbox로 보존되도록 변환. `RemoveBboxAnnotations` 폐기. datumaro 채널은 attributes JSON으로 운반.

**Requirements:** R4
**Dependencies:** U2, U4 (CVAT 내부 round-trip이 먼저 안정), **U6 (`CommonData.LabeledShape/TrackedShape` named tuple에 `bbox` 필드 추가)**
**Files:**
- cvat/apps/dataset_manager/formats/coco.py (line 72-79 `RemoveBboxAnnotations`, line 89, 103)
- cvat/apps/dataset_manager/bindings.py:
  - `CommonData.LabeledShape` named tuple line 220-233: `bbox: Sequence[float] = ()` 추가.
  - `CommonData.TrackedShape` named tuple line 235-250: 동일.
  - `ProjectData` 내부의 동등 named tuple (있으면) 동일 처리.
  - `CommonData._export_labeled_shape` 및 `_export_tracked_shape`: DB에서 가져온 row의 `bbox` 필드를 named tuple로 전달.
  - `CvatToDmAnnotationConverter._convert_shape` line ~1890-1912: skeleton 분기에서 `attributes['bbox'] = json.dumps(shape.bbox)`. 추가로 외부 consumer(COCO 어댑터)를 위해 같은 `group_id`로 별도 `dm.Bbox` annotation 동반 emit (datumaro coco_person_keypoints adapter가 이걸 person bbox로 출력).
  - `import_dm_annotations` skeleton 분기 line 2121-2156, LabeledShape 생성 line 2144: `bbox=parsed_bbox` 인자 추가.
- cvat/apps/dataset_manager/tests/test_skeleton_bbox.py
- **cvat/apps/quality_control/quality_reports.py line 1914 부근**: `ignored_attrs`에 `'__cvat_bbox'` 추가 (transport-only attribute가 MISMATCHING_ATTRIBUTES conflict로 잡히지 않도록).
- **cvat/apps/consensus/merging_manager.py line 104-120**: 동일 ignore 처리.

**Approach:**

**Transport channel 표준화 — 모든 attribute carrier는 reserved-prefix + typed JSON**:
- attribute 키: `__cvat_bbox` (사용자 attribute와 명확히 구분, quality_control/consensus의 attribute 비교에서 제외 처리 가능).
- 값: `{"format": "xyxy", "values": [xtl, ytl, xbr, ybr]}` JSON 직렬화. 미래에 다른 format을 운반해야 하면 `format` 키로 확장.
- **단일 source of truth**: 모든 CVAT 내부 코드(U4 CVAT XML, U5 COCO, datumaro)는 이 형식 하나만 사용. `[x, y, w, h]` ↔ `[xtl, ytl, xbr, ybr]` 변환은 **format boundary에서 1회만**, 내부 IR에서는 항상 xyxy.

**Import 변경** (coco.py):
  - `RemoveBboxAnnotations` 제거.
  - 신규 transformer `LinkBboxToSkeleton`:
    1. 같은 `group_id`로 묶인 bbox annotation을 인접 skeleton annotation에 매칭.
    2. **여기서 COCO `[x, y, w, h]` → CVAT `[x, y, x+w, y+h]` 변환** 수행.
    3. 변환된 값을 `skeleton.attributes['__cvat_bbox'] = json.dumps({"format":"xyxy","values":[...]})`로 attach.
    4. group_id 없으면 image 단위로 1:1 매칭 (skeleton 1개 + bbox 1개) 폴백.
  - bindings.py `import_dm_annotations` skeleton 분기:
    - `attr_payload = ann.attributes.pop('__cvat_bbox', None)` (pop으로 attribute에서 제거).
    - 있으면 JSON 파싱, `format == 'xyxy'` 검증, `values` 4-element 추출, `LabeledShape(bbox=values)`.
    - 없으면 `LabeledShape(bbox=[0,0,0,0])` (degenerate, U2 validator 통과 가능. **`[]` 사용 금지 — U2가 거부**).

**Export 변경** (bindings.py):
  - `_convert_shape` skeleton 분기:
    1. `attributes['__cvat_bbox'] = json.dumps({"format":"xyxy","values":list(shape.bbox)})`.
    2. **`dm_attr['rotation'] = shape.rotation`** — bindings.py line 1839 `if shape.type in (RECTANGLE, ELLIPSE):` 조건에 `SKELETON` 추가. skeleton의 의미 있는 rotation이 datumaro attribute로 운반되도록.
    3. **추가로 별도 `dm.Bbox` annotation 동반 emit** — datumaro의 coco_person_keypoints adapter가 이걸 person bbox로 출력. 동일 group_id로 연결. `bbox = [shape.bbox[0], shape.bbox[1], shape.bbox[2]-shape.bbox[0], shape.bbox[3]-shape.bbox[1]]` (xyxy → xywh 변환).
    4. `shape.bbox == [0,0,0,0]` (degenerate) 인 경우 dm.Bbox emit 생략 (COCO output에 bogus bbox 안 들어가게).
  - **Quality/consensus 격리**: `__cvat_bbox` attribute는 transport-only. `cvat/apps/quality_control/quality_reports.py:1914` `self.ignored_attrs` set에 `'__cvat_bbox'` 기본 포함. consensus도 동일. **이는 U5의 부가 작업 — bindings.py 변경과 같은 PR에서 함께**.

**Datumaro export** (datumaro.py): 별도 변경 없음 — attribute는 datumaro가 자동 운반. round-trip 테스트로 confirm.

**Patterns to follow:**
- 다른 어댑터(e.g., rectangle ↔ dm.Bbox) 가 `[x, y, w, h]` 사용하는 패턴.

**Test scenarios:**
- Covers R4. COCO Keypoints 1.0 import: `annotations[0].bbox = [10, 20, 90, 180]` + keypoints → CVAT skeleton.bbox = `[10, 20, 100, 200]` (xywh→xyxy 변환).
- COCO Keypoints export: skeleton.bbox = `[10, 20, 100, 200]` → 출력 JSON `annotations[i].bbox = [10, 20, 90, 180]` (xyxy→xywh 변환).
- skeleton.bbox = `[0,0,0,0]` (degenerate) export: dm.Bbox emit 생략, COCO JSON에 person bbox 항목 없음.
- Datumaro round-trip: skeleton.bbox 보존. `__cvat_bbox` attribute는 import 시 pop되어 사용자 attribute에 leak되지 않음을 검증.
- **Transport attribute leak 검증**: skeleton with bbox export → datumaro Skeleton의 attributes에 `__cvat_bbox` 존재 → re-import 후 ObjectState.attributes에 `__cvat_bbox` 없음 (pop 동작).
- **bbox 없는 구 COCO Keypoints 데이터 import**: skeleton.bbox = `[0,0,0,0]` (degenerate, **`[]` 아님** — U2 validator 호환). 사용자가 첫 편집 시 정상 bbox로 갱신됨.
- **Quality conflict 회귀 방지**: 동일한 skeleton 2개를 quality compare (GT vs annotation) → `__cvat_bbox` 차이가 MISMATCHING_ATTRIBUTES conflict로 잡히지 않음 (ignored_attrs 등록 검증).
- **Consensus merge 회귀 방지**: 같은 skeleton 3 annotator 결과 merge → `__cvat_bbox` 차이로 인한 attribute 충돌 없음.

**Verification:** COCO Keypoints round-trip 테스트 통과, `RemoveBboxAnnotations` 클래스 삭제됨, quality/consensus 기존 테스트 회귀 없음.

---

### U6. cvat-core: 직렬화 경로에 bbox 운반

**Goal:** cvat-core의 모든 skeleton 직렬화 분기에서 `bbox`를 1급 필드로 운반. 기존 `points: null` 강제는 유지하되 `bbox`는 추가.

**Requirements:** R1, R2, R3, R7
**Dependencies:** U2
**Files:**
- cvat-core/src/server-response-types.ts (`SerializedShape` line 419-434, `SerializedTrack` line 436-456: `bbox?: number[]` 추가, 자식 frame shape에도 추가)
- cvat-core/src/annotations-objects.ts:
  - `SkeletonShape` constructor line 2000-2047: `this.rotation = 0` 강제 제거 → `data.rotation || 0` 보존. `readOnlyFields`에서 `'rotation'` 제거. element 생성 시 `rotation: 0` 강제는 유지(자식 keypoint는 회전 무의미).
  - `SkeletonShape.toJSON()` line 2081-2121: `rotation: this.rotation` (기존 `0` 하드코드 교체), `bbox: this.bbox` 추가.
  - `SkeletonShape.get()` line 2123-2160: `rotation: this.rotation`, `bbox: this.bbox` 추가.
  - `SkeletonShape.saveRotation` line 2177-2193: **element points를 회전시키는 로직 제거**. `this.rotation`만 갱신 (history 액션 유지). element는 회전 없음 → canvas SVG `transform: rotate` 로만 시각적 회전 적용.
  - `SkeletonTrack` constructor line 2971-3023: 동일 패턴 (rotation 보존).
  - `SkeletonTrack.saveRotation` line 3041-3071: element points 회전 로직 제거.
  - `SkeletonTrack.getPosition` line 3322-3353: bbox 선형 보간 추가. `leftPosition.bbox`, `rightPosition.bbox` 4 element를 각각 (targetFrame - leftFrame) / (rightFrame - leftFrame) 비율로 interpolate. singlePosition만 있을 때는 그대로 반환. **rotation도 같이 보간** (rectangle Track 패턴 참고).
  - `Shape.saveBbox(bbox, frame)` 신규 메소드: `savePoints` 패턴 mirror (line 1213-1247). wasKeyframe 분기, history 액션 `CHANGED_BBOX`(신규), implicit keyframe logging, computeNewSource.
- cvat-core/src/annotations-collection.ts: skeleton 분기 (line 317, 376, 536, 681)에 `bbox: object.bbox` 운반.
- cvat-core/src/object-utils.ts: line 372, 388 propagateShapes skeleton 분기에 bbox.
- cvat-core/src/object-state.ts: `bbox` getter/setter (skeleton이면 4-element, 그 외 null). setter는 SkeletonShape/Track의 `saveBbox` 호출.
- cvat-core/src/annotations-saver.ts: dirty 감지 키 리스트에 `'bbox'` 추가.
- cvat-core/src/labels.ts: 변경 없음 (확인용 — skeleton 라벨 정의 영향 없음).

**참고**: `server-request-types.ts` 는 현재 API token / user modifiable 타입만 정의 (12줄). shape 인터페이스 없음. U6 파일 목록에서 제외.

**Approach:**
- `SerializedShape`, `SerializedTrack`: `bbox?: number[]` 추가 (response-types에만).
- `SkeletonShape.toJSON()/get()`: `bbox: this.bbox || []`, `rotation: this.rotation` 포함.
- `SkeletonShape.constructor`: `this.bbox = data.bbox || [0,0,0,0]`, `this.rotation = data.rotation || 0`.
- `SkeletonTrack`: frame별 shape에 bbox 운반. `saveBbox(bbox, frame)` 메소드 추가. `getPosition`에서 keyframe 사이 bbox 선형 보간.
- `ObjectState.bbox` getter/setter: skeleton이면 4-element 또는 null, 그 외 항상 null.
- collection/utils 분기: 기존 `points: null` 라인 옆에 `bbox: object.bbox` 추가.
- annotations-saver.ts: dirty 감지 키 리스트에 `'bbox'` 등록.
- **rotation 시맨틱 변경**: skeleton의 `Shape.rotation`을 진짜 회전각으로 사용 (이전: 항상 0 강제). element points는 회전되지 않음. canvas에서 SVG `transform: rotate({rotation} {cx} {cy})` 로 시각화. axis-aligned bbox 좌표 + rotation 스칼라로 회전된 직사각형 표현.

**Patterns to follow:**
- `savePoints` (annotations-objects.ts:1213-1247): wasKeyframe 분기, history 액션, implicit keyframe 로깅, computeNewSource. `saveBbox`는 이걸 그대로 mirror.
- Track의 frame-별 보간 패턴: `RectangleTrack.getPosition` 등이 points 4-element 선형 보간하는 방식.

**Test scenarios:**
- *Test expectation: 통합 시점에 cvat-ui 동작으로 검증 — cvat-core 자체 test 인프라가 약함. 단위 테스트는 type-check (`yarn workspace cvat-core run type-check`) 통과로 대체.*
- ObjectState.bbox로 4-element 값 설정 후 toJSON → bbox 직렬화 확인 (가능하면 jest fixture).
- **Track interpolation**: SkeletonTrack에 keyframe A(frame=0, bbox=[0,0,100,100])와 B(frame=10, bbox=[100,100,200,200]) 등록 → frame=5 ObjectState.bbox = [50,50,150,150] (선형 보간).
- **Implicit keyframe via saveBbox**: 비-keyframe frame에서 saveBbox 호출 → 해당 frame이 새 keyframe으로 격상.
- **Rotation**: SkeletonShape에 rotation=45° 설정 → toJSON().rotation=45, get().rotation=45. element.points는 회전 전 좌표 그대로 유지 (canvas가 SVG transform으로 시각화).

**Verification:**
- `yarn workspace cvat-core run type-check` 통과
- E2E 또는 cypress: skeleton bbox 변경 → 서버 PATCH 요청에 bbox 포함 확인

---

### U7. cvat-canvas: wrapping rect를 저장값 기반으로 + drag/resize 의미 재정의

**Goal:** wrapping rect의 좌표를 `state.bbox`에서 읽고, drag/resize 결과를 `bbox`(필요 시 `points` 함께)로 emit. corner/edge 핸들 동작을 keypoint 분리 모드로 전환. soft-snap 및 clamp 추가.

**Requirements:** R1, R2, R3
**Dependencies:** U6
**Files:**
- cvat-canvas/src/typescript/canvasView.ts (line 3895-3919 setupSkeleton wrapping rect, 1277-1340 draggable, 1582-1618 resizable, onEditDone 호출부)
- cvat-canvas/src/typescript/drawHandler.ts (line 1071 pasteSkeleton, 1279, 1563 — draw 결과에 bbox 포함)
- cvat-canvas/src/typescript/shared.ts (computeWrappingBox 활용)
- cvat-canvas/src/typescript/consts.ts (SKELETON_RECT_MARGIN 유지)

**Approach:**
- **setupSkeleton (line 3895-3919)**: `state.bbox`가 4-element면 그 값으로 wrappingRect 생성. fallback: `computeWrappingBox(elements, SKELETON_RECT_MARGIN)`.
- **draggable (line 1277-1340)**:
  - skeleton의 line 드래그(전체 이동): 기존 동작 유지. 단 dragend에서 onEditDone 호출 시 새 bbox `[x, y, x+w, y+h]`도 함께 emit.
- **resizable (line 1582-1618)**:
  - skeleton resize 시 keypoints 비례 스케일 코드 제거 (line 1598-1608 for-loop).
  - resize 결과는 bbox 좌표 변경만. resizing 도중 outermost visible+occluded keypoint를 바깥에 두지 못하는 좌표가 들어오면 `Math.max/min`으로 clamp (그 keypoint 좌표까지만 줄어듦).
  - resizeend: onEditDone에 새 bbox 전달, keypoints 미변경.
- **keypoint drag end (svgElements draggable)**:
  - dragend 시 bbox 검사: 만약 keypoint가 bbox 밖이면 bbox 좌표를 그 keypoint까지 확장(0px margin). 확장된 bbox + 변경된 keypoint 좌표를 함께 emit.
- **drawHandler (line 1071, 1279, 1563)**: skeleton draw 완료 시 그린 rect 좌표를 `bbox`로, 자동 배치된 keypoints는 `elements`로 emit.

**Patterns to follow:**
- `onEditDone(state, points, rotation)` 시그니처 확장 또는 별도 `onEditDoneSkeleton(state, points, rotation, bbox)` 분기.
- draggable의 multi-drag 패턴 (line 1342-1349).

**Test scenarios:**
- *Manual + Cypress*: skeleton 새로 그리기 → DB에 bbox 저장 확인 (네트워크 패널의 PATCH/POST 요청).
- *Manual*: bbox corner 핸들 드래그 → keypoints 제자리, bbox만 변경.
- *Manual*: bbox edge 중앙 핸들 드래그 → 동일.
- *Manual*: bbox line 드래그 → keypoints + bbox 모두 평행이동.
- *Manual*: keypoint 하나를 bbox 밖으로 끌기 → 그 keypoint 좌표에 0px margin으로 bbox 확장.
- *Manual*: bbox를 keypoints 영역보다 작게 줄이려 시도 → outermost visible+occluded keypoint에서 멈춤.
- *Manual*: outside=true keypoint를 bbox 밖에 두기 → bbox 확장 안 됨 (검증 제외).
- *Manual*: rotation 핸들로 회전 → `Shape.rotation` 값만 변경, bbox 좌표 axis-aligned 유지.

**Verification:** Cypress e2e 시나리오 추가 (`tests/cypress/e2e/actions_objects/skeleton_bbox.js`), 모두 통과.

---

### U8. cvat-ui: Redux state + saver 흡수 확인

**Goal:** cvat-ui의 redux/component 코드는 cvat-core의 ObjectState를 그대로 소비하므로 별도 변경은 거의 없음. 단 skeleton 관련 컴포넌트에서 bbox 노출 누락이 없는지 확인.

**Requirements:** R1, R7
**Dependencies:** U6, U7
**Files:**
- cvat-ui/src/components/annotation-page/standard-workspace/controls-side-bar/draw-skeleton-control.tsx (draw 트리거, 변경 없을 가능성)
- cvat-ui/src/reducers/annotation-reducer.ts (action handler 검토)
- cvat-ui/src/components/annotation-page/standard-workspace/objects-side-bar/object-item-details.tsx (skeleton details panel — bbox 표시는 deferred, 일단 변경 없음)

**Approach:**
- `yarn workspace cvat-ui run type-check`로 SerializedShape 타입 변경이 누락된 곳 없는지 확인.
- redux state는 ObjectState 그대로 전달하므로 transparent.

**Test scenarios:**
- *Test expectation: none -- pass-through 변경. type-check 및 U7의 e2e가 통합 검증.*

**Verification:** `yarn workspace cvat-ui run type-check` 통과.

---

### U9. SDK 재생성

**Goal:** OpenAPI schema에 `bbox` 필드가 반영된 cvat-sdk 재생성. **Read 경로는 invisible, Write 경로는 breaking** — read-only 사용자는 무손상, skeleton create/update 호출하는 자동화는 메이저 버전 bump 필요.

**Requirements:** R7
**Dependencies:** U2
**Files:**
- cvat-sdk/gen/postprocess (생성 출력)
- cvat-sdk/cvat_sdk/api_client/models/* (자동생성)
- cvat-sdk 버전 bump — **메이저** (skeleton write contract breaking)

**Approach:**
- `./cvat-sdk/gen/generate.sh` 실행. 결과 diff 검토:
  - `LabeledShape`, `TrackedShape`, `LabeledShapeRequest`, `TrackedShapeRequest` 모델에 `bbox` 필드 추가됨을 확인.
- **호환성 매트릭스**:
  - **Read 경로**: 기존 SDK가 응답을 받아 deserialize만 한다면 추가 `bbox` 필드 무시 → 무손상.
  - **Write 경로 (skeleton POST/PATCH)**: 구 SDK가 bbox 누락한 채 호출 → 400 거부. **breaking change**. 자동화 파이프라인 영향.
  - **Write 경로 (rectangle/polygon 등 non-skeleton)**: bbox 무시되므로 무손상 (U2 validator가 빈 배열 또는 누락 모두 허용).

**Test scenarios:**
- SDK로 skeleton 생성/조회 (cvat-sdk/tests/python 또는 tests/python/sdk/test_*): bbox 필드 송수신 확인.
- **Read-only 호환성**: 구 SDK (이전 버전) 모델로 응답 deserialize → 추가 bbox 필드 무시되며 정상 동작.
- **Write breaking 입증**: 구 SDK 모델로 skeleton POST 시도 → 400 (skeleton requires bbox). 의도된 breaking change임을 release notes에 명시.
- **Write 무손상 입증 (non-skeleton)**: 구 SDK로 rectangle POST → 200 OK (bbox 필드 미전송이지만 non-skeleton은 허용).

**Verification:**
- generate.sh 종료 코드 0
- 자동생성 모델 diff에 bbox 필드 명시
- SDK 테스트 통과

---

### U10. Release notes + 운영 문서

**Goal:** 사용자/운영자에게 변경사항과 maintenance window를 명확히 고지.

**Requirements:** R5, R6
**Dependencies:** U3 (migration 완성), U5 (COCO 동작 변경 확정)
**Files:**
- CHANGELOG.md 또는 docs/release-notes/ (저장소 convention에 따라)

**Approach:**
- Breaking change 섹션:
  - COCO Keypoints import: 이전엔 person bbox가 폐기되었으나 이제는 skeleton.bbox로 저장됨. 자동화 파이프라인이 bbox 누락에 의존했다면 영향 있음.
  - SDK skeleton POST: bbox 필드 필수 (skeleton type일 때 4-element).
- Migration window: 약 30분 read-only 권장. 작업: cvat_worker_annotation/import/export RQ 일시 정지, write API 차단.
- Frontend 동작 변경 안내:
  - 빨간 박스 corner 핸들 = 이제 bbox만 리사이즈 (이전: skeleton 전체 비례 스케일).
  - keypoint 드래그가 bbox를 자동 확장(0px). 박스 밖으로 끌면 박스가 그 점까지 늘어남.

**Test scenarios:** *Test expectation: none -- 문서.*

**Verification:** CHANGELOG에 항목 추가, PR description에 동일 정보 포함.

---

## Test Strategy

### 통합 round-trip 테스트 (백엔드)
- `tests/python/rest_api/test_skeleton_bbox.py`: API 레벨 CRUD + validation + COCO/CVAT XML round-trip.
- `cvat/apps/dataset_manager/tests/test_skeleton_bbox.py`: format-level round-trip + migration backfill 검증 unit.

### Migration 회귀 테스트
- 0098 migration unit test로 backfill 정확성 검증 (5 fixture skeleton, outside element 포함 케이스).
- Reverse migration이 데이터 손상 없이 수행됨.

### Frontend
- Cypress e2e (`tests/cypress/e2e/actions_objects/skeleton_bbox.js`): 그리기, line 드래그, corner/edge 리사이즈, keypoint snap, rotation, occluded/outside 처리.
- Type check: cvat-core, cvat-ui 모두 통과.

### SDK
- cvat-sdk 자동생성 후 기존 sdk 테스트 회귀 확인.

### Existing test 갱신
- tests/python/rest_api/test_task_data.py:420-459 `test_can_get_annotations_from_new_task_with_skeletons`: 응답에 bbox 키 등장하므로 assertion 보정.

---

## System-Wide Impact

| 영역 | 영향 | 완화 |
|---|---|---|
| DB schema | LabeledShape, TrackedShape에 컬럼 1개씩 추가 (text). 3.9 GB 테이블에 약간의 저장 공간 증가 (~5%). | online add column (NULL→default), 즉시 영향 없음. |
| Migration 운영 | 약 10-20분 backfill 동안 write 차단 권장. | staging dry-run, 30분 maintenance window 공지. |
| External API contract | `bbox` 필드 신규 노출. skeleton POST 시 필수. | release notes, breaking change 명시. additive read는 무손상. |
| COCO 자동화 파이프라인 | bbox가 더 이상 무시되지 않음. 기존 import 결과와 다름 (개선). | release notes. |
| Frontend UX | wrapping rect resize 의미 변경 (corner = bbox 단독, line = 전체 이동). | release notes, 사용자 가이드. |
| RQ workers (import/export) | 새 코드 경로 사용. RQ 재시작 후 적용. | 배포 시 worker rolling restart. |

---

## Risk Analysis & Mitigation

| Risk | Severity | Likelihood | 완화 |
|---|---|---|---|
| Migration이 30분 초과 | High | Low | U1 staging dry-run으로 사전 측정. chunk 크기 조정 가능. 필요 시 RunPython을 별도 management command로 분리 (manual run, idempotent). |
| Backfill 중 race (사용자가 skeleton 생성) | Med | Low | maintenance window write 차단. RQ worker 정지. |
| `RemoveBboxAnnotations` 제거 후 datumaro에서 invalid label 에러 | Med | Med | LinkBboxToSkeleton transformer가 bbox 자체는 dataset에서 제거하고 skeleton attribute로만 attach. label 충돌 회피. |
| dumper.open_skeleton 위치 누락 | Low | Med | grep `open_skeleton` 으로 dumper 모듈 식별, `open_box` 패턴 mirror. |
| cvat-canvas resize 코드 변경이 다른 shape resize에 회귀 | High | Low | skeleton 분기만 수정, 다른 shape는 기존 경로 그대로. Cypress 회귀 시나리오로 rectangle/polygon resize 동시 검증. |
| Soft-snap이 keypoint dragmove 마다 trigger되어 jitter | Low | Low | dragend에서만 snap 계산, dragmove는 단순 keypoint 좌표 갱신. |

---

## Dependencies / Prerequisites

- PostgreSQL: 기존 환경 그대로. FloatArrayField는 text 직렬화이므로 PG 특수 기능 의존 없음.
- Django/DRF: 기존 버전.
- datumaro: 기존 버전 그대로 (attributes 운반만 사용, 패키지 수정 불필요).
- Docker dev stack: 변경 없음.
- 사용자 측 사전 작업: U1의 SQL 결과 확보, staging clone 확보.

---

## Operational / Rollout Notes

1. **Staging dry-run** (U3 머지 전): production DB clone에 0098 적용, 시간 측정, 무작위 100 skeleton 표본 bbox 검증.
2. **Production deploy 순서**:
   1. Maintenance window 시작 (예: 30분).
   2. cvat_server, cvat_ui 새 이미지 배포 (코드만, migration 미실행 상태에선 bbox 컬럼 없음 — 따라서 코드 배포와 migration은 동시 실행, U2/U3 같은 PR).
   3. `docker compose run --rm cvat_server python manage.py migrate engine 0098`.
   4. Schema 재생성 산출물 (cvat/schema.yml) 함께 배포.
   5. RQ worker 재시작.
   6. Smoke test: skeleton GET/POST, COCO export round-trip.
   7. Maintenance window 해제.
3. **Rollback**: `migrate engine 0097` → bbox 컬럼 drop. 코드는 0097 이전 커밋으로 revert.

---

## Open Questions Resolved in This Plan

- **Backfill chunk size**: 5,000 row/batch (U3).
- **TrackedShape children 측정**: U1 SQL 단계로 사전 실행.
- **Migration 운영 정책**: read-only maintenance window 30분.
- **Soft-snap perf**: dragend에서만 1회 계산, 무시 가능.

## Deferred to Implementation

- `dumper.open_skeleton` 의 실제 모듈 경로 (U4 작업 시 grep으로 식별).
- COCO transformer `LinkBboxToSkeleton` 구체 그룹핑 키 (annotations index인지 group_id인지) — datumaro CocoImporter 출력 구조 확인 후 결정.
- Soft-snap이 keypoint 다중 선택 multi-drag 흐름에서 bbox 한 번만 확장되도록 dragend hook 위치.

---

## References

- Origin: docs/brainstorms/2026-05-19-skeleton-bbox-requirements.md
- Shape abstract model: cvat/apps/engine/models.py:1187-1197
- ShapeSerializer + validation: cvat/apps/engine/serializers.py:3232-3294
- LabeledShapeSerializerFromDB / LabeledTrackSerializerFromDB: cvat/apps/engine/serializers.py:3316-3350
- Latest migration: cvat/apps/engine/migrations/0097_drop_legacy_analytics_report.py
- CVAT XML import box pattern: cvat/apps/dataset_manager/formats/cvat.py:304-315
- CVAT XML export skeleton: cvat/apps/dataset_manager/formats/cvat.py:969-993
- COCO bbox 폐기 로직: cvat/apps/dataset_manager/formats/coco.py:72-79
- bindings.py skeleton import: cvat/apps/dataset_manager/bindings.py:2086-2156
- cvat-canvas wrapping rect: cvat-canvas/src/typescript/canvasView.ts:3895-3919
- cvat-canvas drag/resize: cvat-canvas/src/typescript/canvasView.ts:1277-1340, 1582-1618
- Implicit keyframe (savePoints): cvat-core/src/annotations-objects.ts:1213-1247

---

## Codex Cross-Review (2026-05-19)

### Findings 요약
- CRITICAL: 4개 (#1 product-decision, #2/#3/#4 factual-fix)
- MAJOR: 3개 (#5/#6/#7 factual-fix)
- MINOR: 1개 (#8 factual-fix)
- false-positive: 0개

### 처리 결과
- **#1 (R7 contradiction)** → brainstorm 회귀로 product 결정. **Required 채택**: skeleton POST에 bbox 필수, 누락 시 400. R7은 "응답 read-only 클라이언트 무손상"으로 좁힘. SDK 메이저 bump + release notes 명시. Requirements Traceability R7과 U2 test scenarios 반영 완료.
- **#2 (invariant inconsistency)** → Key Technical Decisions에 Normal/Degenerate 2개 유효 상태 명시, serializer validation에 `bbox==[0,0,0,0]` 허용 추가, `bbox==[]` 금지. U3 backfill 결과와 일관.
- **#3 (rotation override)** → U6에 `SkeletonShape.constructor` rotation=0 강제 제거, `toJSON()/get()`에 rotation 보존, `saveRotation`이 element points 회전 제거 명시. canvas에서 SVG transform으로 시각화.
- **#4 (track interpolation)** → U6에 `SkeletonTrack.getPosition` bbox 선형 보간 추가. 테스트 시나리오 보강.
- **#5 (XML import bridge)** → U4에 `attributes['bbox']` JSON 운반으로 변경. `_parse_shape_ann` 에서 attribute로 옮긴 후 Skeleton 생성.
- **#6 (named tuple carrier)** → U5 dependencies에 U6 추가. `CommonData.LabeledShape/TrackedShape` 에 `bbox` 필드 추가, `_export_labeled_shape/_export_tracked_shape` 갱신 명시.
- **#7 (interpolation export path)** → U4에 `dump_as_cvat_interpolation` line 1014-1193 경로 명시 + tracked skeleton round-trip 테스트 추가.
- **#8 (server-request-types)** → U6 파일 목록에서 server-request-types.ts 제거, response-types.ts에만 anchor.

### 다음 사이클 학습 후보 (`AGENTS.md` review standards 후보)
- **DB invariant vs migration backfill 일관성**: NOT NULL 정책을 정할 때 backfill이 만들 수 있는 모든 상태를 명시적으로 허용 상태에 포함시켜야 함. "validator가 받지 못하는 row를 migration이 만든다" 패턴은 반복 발생.
- **cvat-core skeleton 클래스의 hardcoded `rotation=0` 패턴**: SkeletonShape/Track에서 rotation을 강제 0으로 보내고 element points로 회전을 구현하는 패턴이 여러 곳에 산재. 미래에 회전 기반 작업 시 같은 함정. CLAUDE.md에 "SkeletonShape rotation 변경 시 5개 위치 동시 수정 필요" 룰 추가 권장.
- **Datumaro IR 운반 채널 패턴**: CVAT-only 필드를 datumaro로 운반할 때는 `attributes` JSON이 표준 채널 (rotation 운반 패턴이 이미 존재). 이 룰을 dataset_manager 디렉토리 README에 명시 권장.
- **Dataset manager의 dual export paths**: `dump_annotations` + `dump_as_cvat_interpolation` 두 경로가 별도 코드. shape 관련 변경 시 양쪽 다 수정 필요. 향후 plan에서 dataset_manager 변경은 두 경로를 분명히 명시하는 게 좋음.

---

## Codex Cross-Review Round 2 (2026-05-19)

### Findings 요약
- CRITICAL: 5개 → 전체 plan v3 패치 (game 룰 예외 — 모두 factual-fix, product 결정 0)
- MAJOR: 1개 → plan 패치
- false-positive: 0

### 처리 결과
- **#1 (U9 self-contradiction)** → U9 텍스트 워딩 정정. read-only 호환 vs write breaking 명확 분리. 호환성 매트릭스 추가.
- **#2 (bbox invariant 불완전)** → U2 validation을 정확히 `[0,0,0,0] OR (len==4 and xtl<xbr and ytl<ybr)` 로 strict화. U5 COCO 폴백을 `[]`에서 `[0,0,0,0]`으로 변경. zero-width/zero-area 케이스 명시 거부.
- **#3 (attribute carrier 좌표 의미 모호)** → transport 표준화: 키 `__cvat_bbox`, 값 `{"format":"xyxy","values":[...]}` 단일 형식. format boundary에서만 xywh↔xyxy 변환. U4/U5 모두 이 표준 사용.
- **#4 (quality/consensus attribute 노출)** → U5에 `quality_reports.py:1914 ignored_attrs`와 `merging_manager.py:104-120`에 `__cvat_bbox` 등록 작업 추가. transport-only attribute 격리. 회귀 방지 테스트 시나리오 추가.
- **#5 (rotation export 누락)** → U4 CVAT XML skeleton attr에 `rotation` 출력 추가 (annotation + interpolation path 둘 다). U5 bindings.py line 1839 `if shape.type in (RECTANGLE, ELLIPSE):` 조건에 `SKELETON` 추가. rotation round-trip 테스트 명시.
- **#6 (PATCH 테스트 누락)** → U2 test scenarios에 POST/PATCH 분리, PATCH 5개 시나리오 추가 (skeleton/non-skeleton, bbox 누락, Normal→degenerate 회귀, TrackedShape PATCH).

### 게이트 룰 학습
- 기존 룰: "CRITICAL 1개 이상 → brainstorm 회귀".
- 이번 라운드 관찰: CRITICAL 5개가 모두 factual-fix Type. brainstorm으로 결정할 product 질문 없음.
- **개선 제안**: 게이트 룰을 `CRITICAL 중 product-decision Type이 1개 이상 → brainstorm 회귀, 모두 factual-fix → plan 패치` 로 세분화. `codex-review-router` skill의 Phase 4 룰 갱신 검토.

### 다음 사이클 학습 후보 (이번 라운드 신규)
- **Transport-only attribute 패턴**: dataset_manager가 datumaro로 CVAT-only 필드를 운반할 때, quality/consensus의 attribute 비교 경로가 그 transport metadata를 사용자 attribute로 오인하는 회귀 위험. 표준 prefix(`__cvat_*`) + `ignored_attrs` 자동 등록 패턴을 라이브러리 레벨로 추출하면 향후 유사 작업에서 같은 함정 방지.
- **bbox 두 형식 ([xtl,ytl,xbr,ybr] vs [x,y,w,h])의 internal/external boundary**: CVAT 내부는 xyxy, 외부 포맷(COCO, ML)은 종종 xywh. 변환은 format adapter에서만 1회, IR에서는 단일 형식. 향후 다른 shape에 외부 format 변환 추가 시 이 원칙 명시.
- **Validator의 두 유효 상태 (Normal + Degenerate)**: migration backfill로 의도적 degenerate state를 만들 때, validator에 해당 상태만 정확히 허용 (`xtl<=xbr` 같은 느슨한 조건이 아닌 `== [0,0,0,0]` 등 명시적 한 점). 두 상태 모두 round-trip 테스트.
