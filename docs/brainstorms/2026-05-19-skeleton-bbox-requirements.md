# Skeleton Bounding Box 영속화 — Requirements

- **Date**: 2026-05-19
- **Author**: liam@everex.co.kr
- **Status**: Ready for planning
- **Scope tier**: Standard
- **Successor doc**: TBD (`/ce-plan`)

## 1. Problem

CVAT skeleton shape는 자식 keypoint들의 좌표만 저장하고, 캔버스에 보이는 빨간 wrapping rect는 매번 `min/max + 20px margin`으로 즉석 계산된다 (`cvat-canvas/src/typescript/canvasView.ts:3895-3919`). 결과적으로:

1. annotator가 skeleton을 그리기 시작할 때 **명시적으로 그린 회색 가이드 박스**가 어디에도 저장되지 않는다. 이 박스는 "객체 경계"라는 의미를 가지지만 즉시 휘발된다.
2. **COCO Keypoints import는 `annotations[i].bbox` 를 강제로 폐기**한다 (`cvat/apps/dataset_manager/formats/coco.py:72-79`, 주석에 `TODO: find a way to import boxes`). 표준 COCO Keypoints는 person bbox와 keypoints를 둘 다 갖는데, CVAT는 bbox 정보를 잃는다.
3. export 시에도 skeleton의 object bbox가 elements에서 자동 계산되어 사용자가 그렸던 의도와 분리된다.

## 2. Goal

Skeleton에 1급 `bbox` 필드를 도입해서 (a) annotator가 그린 객체 경계를 영속화하고, (b) COCO Keypoints 등 외부 포맷의 bbox와 round-trip 보존을 가능하게 한다.

## 3. Users / Actors

- **Annotator**: skeleton을 그리는 사용자. 그린 박스가 그대로 저장되기를 기대.
- **Dataset 운영자**: COCO Keypoints 포맷으로 import/export 하는 사용자. bbox 손실이 없기를 기대.
- **Downstream ML 학습 파이프라인**: object bbox + keypoints 둘 다 갖춘 COCO 표준 출력을 소비.

## 4. Key Decisions

### 4.1 저장 방식 — 신규 필드 (Option B 확정)

- `points` 필드 재활용이 아니라 **신규 `bbox` 필드** 추가.
- `Shape` (abstract) 모델에 `bbox` 추가 → `LabeledShape`, `TrackedShape` 자동 상속.
- 형식: **axis-aligned `[xtl, ytl, xbr, ybr]`** (4-element float, text 컬럼 직렬화 — `points`와 동일 방식).
- 회전은 기존 `Shape.rotation` 필드(double precision) 재활용. bbox 자체는 axis-aligned로 저장하고 회전은 별도 스칼라.
- skeleton에만 의미 있음. 다른 shape 타입(rectangle/polygon/etc)에는 NULL.
- **사다리꼴 우려**: 발생하지 않음. SVG.js `.resize()`는 corner/edge 조작 시에도 사각형성을 유지하며 4 corner 독립 변형이 불가능. 결과는 항상 "axis-aligned rectangle + rotation angle" → DB에 그대로 표현 가능.
- 이유: `points` 재활용은 rectangle과의 의미 충돌 + 모든 직렬화 분기점 오염. 신규 필드가 의미 명확하고 외부 포맷(COCO bbox)과 매핑이 자연스러움.

### 4.2 NULL 정책 — NOT NULL + backfill migration

- 신규 row는 NOT NULL.
- 기존 row는 migration으로 `elements (min/max) + 20px` 으로 backfill.
- 이유: nullable + auto-derive 방식은 의미가 둘로 갈라짐("미설정"과 "계산 가능"). NOT NULL + backfill이 데이터 모델을 단순하게 만든다.
- Rollback: `bbox` 컬럼 drop만 하면 됨 (backfill 값은 derived data이므로 무손실).

### 4.3 의미 — annotator가 그린 객체 경계 (고정)

- skeleton bbox는 **annotator의 의도 = 객체(사람 등)의 경계**.
- keypoint를 이동/추가/삭제해도 bbox는 **자동으로 따라가지 않음**.
- rectangle과 동일한 1급 시각/데이터 entity.

### 4.4 편집 동작

기존 svg.select.js의 핸들 구조(코너 4 + 변 중앙 4 + rotation 1)를 그대로 활용한다. 의미만 재정의.

| 사용자 액션 | 동작 |
|---|---|
| skeleton 처음 그리기 | 현재처럼 회색 박스 드로우 → 박스 내부에 keypoint 자동 배치. 그 박스 좌표가 `bbox`로 저장. |
| bbox **line(테두리) 드래그** | **기존 동작 유지**: bbox + 모든 keypoint가 함께 평행이동 (skeleton 전체 이동). bbox는 자동 갱신되어 저장. |
| bbox **corner 핸들(lt/rt/rb/lb) 드래그** | **신규 의미**: bbox만 리사이즈, keypoints는 제자리. axis-aligned 유지. |
| bbox **edge 중앙 핸들(t/r/b/l) 드래그** | **신규 의미**: 해당 변만 이동, bbox만 변경, keypoints 제자리. axis-aligned 유지. |
| bbox **rotation 핸들** 드래그 | `Shape.rotation` 갱신. 시각적 회전, bbox 좌표는 axis-aligned 그대로. |
| **keypoint 개별 드래그** | **bbox는 변하지 않음** (현재의 자동 wrapping 로직 제거). |
| keypoint 이동으로 bbox 밖으로 나가면 | **Soft snap**: bbox가 그 keypoint 좌표에 **0px margin으로 딱 맞춤**까지 자동 확장. |
| bbox 리사이즈로 keypoint를 못 담게 되면 | **자동 clamp**: bbox가 outermost visible/occluded keypoint까지만 줄어들고 멈춤. 그 이상 줄이려 해도 차단. |
| `outside=true` keypoint | 위의 모든 검증/snap에서 **제외** (좌표값 무의미). `occluded=true`는 좌표 유효하므로 검증 포함. |
| **Track 보간 frame에서 사용자가 bbox 수정** | keypoint와 동일 패턴: 그 frame이 자동으로 새 keyframe으로 격상 (implicit keyframe). `cvat-core/src/annotations-objects.ts:1213-1247` `savePoints` 패턴 참고. |

핵심: **"line 드래그 = 전체 이동"은 보존**(기존 UX와 직관 유지), **corner/edge 핸들 = bbox 단독 변경**(새 의미). line 드래그 시 bbox는 keypoints와 함께 평행이동되어 결과적으로 두 데이터가 동시 갱신되므로 일관성 유지됨.

### 4.5 Import/Export 정책

- **CVAT XML**: `<skeleton>` element에 `xtl/ytl/xbr/ybr` 속성 직접 추가. round-trip 무손실.
- **COCO Keypoints (1.0)**:
  - Import: `annotations[i].bbox = [x, y, w, h]` 를 skeleton.bbox로 매핑 (현재의 `RemoveBboxAnnotations` 폐기 동작 제거). `[x, y, w, h]` → `[xtl, ytl, xbr=x+w, ybr=y+h]` 변환.
  - Export: 저장된 `skeleton.bbox` 우선 출력. NULL인 경우만 elements에서 계산 (정상 흐름에선 발생하지 않음).
- **Datumaro**: `datumaro.Skeleton` 타입에는 bbox 필드가 없음. CVAT-측 IR 또는 attributes에 운반 후 CVAT 측에서 복원. 외부 datumaro consumer로는 별도 채널 필요(또는 attributes 사용).
- 기타 포맷: skeleton 미지원이므로 변경 없음.

### 4.6 occluded / outside / visibility 분리 유지

- 기존 모델 그대로 (`cvat-core/src/annotations-objects.ts:518-519, 698-721`).
- `outside=true`: 좌표값 무의미 (frame 밖 / 존재하지 않음). bbox 검증 제외.
- `occluded=true`: 좌표값 유효 (보이지 않지만 위치는 안다). bbox 검증 포함.
- COCO `visibility`: v=0 ↔ outside, v=1 ↔ occluded, v=2 ↔ visible.
- 이 시맨틱은 변경 없음.

## 5. Success Criteria

1. Skeleton 새로 그리면 회색 박스 좌표가 DB의 `bbox` 컬럼에 저장된다.
2. bbox만 드래그/리사이즈 → keypoints 그대로, bbox만 변경되어 저장.
3. keypoint를 이동해도 bbox는 변경되지 않는다 (soft snap이 필요한 경우 외).
4. COCO Keypoints import 후 export: 입력 bbox가 정확히 보존된다 (round-trip).
5. 기존 643,945개 skeleton row가 migration 후 합리적 bbox 값을 갖는다 (elements min/max + 20px).
6. Migration이 production DB(약 4 GB)에서 **30분 이내**에 완료된다 (chunked).
7. SDK 응답 스키마에 `bbox` 필드가 노출되고, 기존 SDK 클라이언트(필드 무시)는 깨지지 않는다.

## 6. Out of Scope

- skeleton bbox에 confidence/score 등 추가 메타.
- 다른 shape (rectangle, polygon)에 wrapping/메타 추가.
- 새로운 keypoint visibility 모델.
- 3D skeleton (이미 Everex fork에서 제거됨).
- Quality reports / consensus의 매칭 metric에 skeleton bbox IoU 통합 (가능하지만 후속 별도 작업).
- COCO bbox 외 다른 포맷 (Datumaro 등) UI를 통한 bbox 편집 plus alpha.

## 7. Dependencies & Assumptions

- **DB 영향 측정 (실측값)**:
  - `engine_labeledshape` 중 skeleton parent: **643,945 row**
  - skeleton 당 평균 elements: **24개** (max 24, 균일 — 라벨 정의 기반).
  - LabeledShape 자식 elements 총합: **15,454,680 row** (정확히 643,945 × 24 일치 ✓).
  - `engine_trackedshape` 중 skeleton parent: **29,925 row** (≈ 6,054 track × 평균 4.9 keyframe).
  - skeleton track 고유 수: **6,054 track**.
  - `engine_labeledshape` 테이블 크기: **3.9 GB**.
  - `engine_labeledshape.points` 컬럼은 **text 타입** (FloatArrayField text 직렬화). 새 `bbox`도 동일 방식.
  - `parent_id` 인덱스 존재 (`engine_labeledshape_parent_id_41b56dde`) → backfill self-join 성능 양호.
  - TrackedShape 자식 elements 측정은 plan 단계 보강 (`SELECT COUNT(*) FROM engine_trackedshape WHERE parent_id IS NOT NULL`).
- **Migration 시간 가정**: 총 backfill 대상 약 **673,870 parent row** + 자식 ~16M scan. chunked batch 1-2k row/sec 기준 **10-20분**. staging 환경에서 dry-run 후 확정.
- **Datumaro**: bbox 운반은 attributes 또는 CVAT-측 IR 별도 channel 사용. datumaro 패키지 수정은 불필요.
- **하위 호환**: 기존 SDK/CLI 클라이언트가 응답에 새 필드가 있어도 깨지지 않는다고 가정 (additive change).
- **Production no-organization 모드**: 권한은 sandbox OPA 규칙 기반, skeleton-specific 권한 없음 (영향 없음 가정).
- **Frontend snap 동작**: Soft snap의 마진 정책 (정확히 keypoint 위치까지 vs 작은 padding 추가)은 plan 단계에서 결정.

## 8. Impact Surface (요약)

상세 라인 단위는 plan 단계에서 구체화. 여기서는 영향 영역만:

| 영역 | 핵심 파일 |
|---|---|
| **Backend 모델/스키마** | `cvat/apps/engine/models.py` (`Shape`), 신규 migration `0098_*` |
| **Backend Serializer** | `cvat/apps/engine/serializers.py` (`ShapeSerializer`, `LabeledShapeSerializer`, `TrackedShapeSerializer`, `LabeledTrackSerializer`) |
| **Backend Dataset Manager** | `bindings.py` (skeleton ↔ datumaro 변환), `formats/coco.py` (`RemoveBboxAnnotations` 폐기 + 새 mapping), `formats/cvat.py` (XML attr 추가), `formats/datumaro.py` (attributes 운반) |
| **cvat-core** | `object-utils.ts:372,388`, `annotations-collection.ts:317,376,536,681`, `annotations-objects.ts` (`SkeletonShape/Track` toJSON), `object-state.ts` (`bbox` getter), `server-response-types.ts` & `server-request-types.ts`, `annotations-saver.ts` (dirty key) |
| **cvat-canvas** | `canvasView.ts:3895-3919` (wrapping rect ↔ ObjectState 연결, drag/resize handler 1278/1519), `drawHandler.ts:1071,1279,1563` (draw 결과에 bbox 포함), soft-snap 로직 신규 |
| **cvat-ui** | redux/state 자동 흡수 (필드 추가만), details sidebar 표시 (선택) |
| **SDK/CLI** | OpenAPI schema 재생성 (`./cvat-sdk/gen/generate.sh`) |
| **Tests** | `tests/python/rest_api/test_task_data.py:420-459` (skeleton fixture), 포맷 round-trip 테스트 신규 (COCO/CVAT XML) |

## 9. Risks

1. **Migration 시간**: chunked batch가 제대로 동작하지 않으면 production 락 위험. → staging dry-run 필수.
2. **Backfill 의미 모호성**: 기존 row의 bbox는 "사용자가 그린 박스"가 아니라 "마이그레이션 시점 자동 계산"임. 그러나 첫 편집 시 정상화되므로 영구 문제 아님. 운영자에게 release notes로 고지.
3. **COCO bbox 의미 변화**: 현재 import는 bbox를 폐기. 새 동작은 bbox를 저장. 기존 import 워크플로우에 의존하던 사용자가 있다면 동작 변경 (개선이지만 변화). → release notes 명시.
4. **Datumaro round-trip 손실**: attributes 우회로 운반하면 외부 datumaro consumer는 bbox 못 봄. 명확한 한계.
5. **Soft-snap UX**: keypoint 드래그 시 bbox가 살짝 늘어나는 동작이 직관적인지 검증 필요. → UX QA.
6. **frontend의 wrapping rect 의미 변화**: 기존엔 "skeleton 전체 이동/리사이즈 핸들". 새 동작은 "bbox만 이동/리사이즈". skeleton 전체 이동이 필요한 사용자에게 대체 인터랙션 (예: 모든 keypoint multi-select) 필요 여부는 plan에서 검토.

## 10. Resolved Decisions (이전 Open Questions 정리)

- **Soft-snap margin**: 0px (keypoint 좌표에 딱 맞춤).
- **Bbox→keypoint clamp UI**: 자동 clamp (가장 외곽 keypoint까지만 줄어듦, 차단 + 별도 toast 없음).
- **Track bbox 보간**: keypoint와 동일 (선형 보간 + 수정 시 implicit keyframe 자동 생성).
- **Skeleton 전체 이동**: line 드래그 동작 유지. corner/edge 핸들만 의미 변경.
- **bbox 회전**: 기존 `Shape.rotation` 재활용. 사다리꼴 발생 불가 (SVG.js .resize() 특성).
- **Migration 전략**: 1단계 (AddField + chunked RunPython backfill + SetNotNull, 단일 파일). 단일 트랜잭션 권장.

## 11. Remaining Open Questions (plan에서 결정)

- Backfill chunk 크기 (5k? 10k?) 및 commit 주기.
- TrackedShape 자식 element row 수 측정 (`SELECT COUNT(*) FROM engine_trackedshape WHERE parent_id IS NOT NULL`).
- Migration 실행 중 서버 운영 정책 (downtime? read-only?).
- Soft-snap 동작이 빠르게 연속된 keypoint 드래그에서 perf 영향 (매 dragmove마다 bbox 재계산).

## 12. References

- Canvas wrapping rect 코드: `cvat-canvas/src/typescript/canvasView.ts:3895-3919`
- Wrapping rect drag = 전체 이동 로직: `cvat-canvas/src/typescript/canvasView.ts:1277-1340`
- Wrapping rect resize = 전체 스케일 + rotation: `cvat-canvas/src/typescript/canvasView.ts:1582-1618`
- svg.select.js 8 핸들 정의 (`lt rt rb lb t r b l` + `rot`): `cvat-canvas/src/typescript/canvasView.ts:1068-1072`
- Implicit keyframe 패턴 (track 보간 frame 수정 시 자동 격상): `cvat-core/src/annotations-objects.ts:1213-1247` (`savePoints` 내 `wasKeyframe` 분기)
- COCO bbox 폐기 로직: `cvat/apps/dataset_manager/formats/coco.py:72-79`
- skeleton 직렬화 `points: null` 강제 지점: `cvat-core/src/object-utils.ts:372,388`, `cvat-core/src/annotations-collection.ts:317,376,536,681`
- 현재 HEAD migration: `cvat/apps/engine/migrations/0097_drop_legacy_analytics_report.py`
- DB schema `\d engine_labeledshape`: `points TEXT NOT NULL`, `parent_id` 인덱스 존재.
