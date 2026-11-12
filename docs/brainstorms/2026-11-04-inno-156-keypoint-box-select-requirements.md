---
date: 2026-11-04
topic: inno-156-keypoint-box-select
ticket: INNO-156
related: [INNO-157, INNO-158]
---

# INNO-156 Shift+드래그 박스로 키포인트만 선택

## Summary

스켈레톤에 대해 Shift+드래그 박스는 이제 사람 전체가 아니라 박스 안에 들어온 키포인트만 선택한다. 개별 키포인트는 mac `⌘+클릭`, Windows/Linux `Ctrl+클릭`으로 선택에 넣고 뺀다. 사람 단위 다중 선택은 기존 Shift+클릭이 맡는다. 선택한 키포인트를 끌면 여러 사람의 키포인트가 함께 움직이고, Undo 한 번으로 그 이동 전체가 되돌아간다.

## Problem Frame

Shift+드래그 박스 다중 선택은 카메라 흔들림 보정(여러 사람을 한꺼번에 옮기기)을 위해 포크에서 추가한 기능이다. 지금은 박스가 걸친 사람을 통째로 고르기 때문에(`cvat-canvas/src/typescript/canvasView.ts`의 `finishMultiSelect`), 일부 관절만 어긋난 경우(예: 여러 사람의 발목만 밀림)에는 쓸 수 없다. 작업자는 키포인트를 하나씩 끌어 고친다. 핵심 동작은 Jira에서 결정되었고, 이 문서는 그 결정을 코드 현실에 맞춰 빈칸을 채운다. 결정에 없던 빈칸은 기본값을 정하고 가정(AS)으로 표시했다. 사용자는 대부분 mac이다.

## Key Decisions

- **박스 = 키포인트 전용, 사람 단위 = Shift+클릭.** 스켈레톤에 대해 Shift+드래그 박스는 키포인트만 선택한다. 사람 전체를 여러 명 고르려면 기존 Shift+클릭(한 명씩 토글, `canvas-wrapper.tsx`의 `onCanvasMouseUp`)을 쓴다. 사용자 결정(Jira). 스켈레톤이 아닌 도형의 처리는 Q1에서 정한다.
- **개별 토글 키는 플랫폼별.** mac은 `⌘+클릭`, Windows/Linux는 `Ctrl+클릭`이다. mac의 Ctrl+클릭은 우클릭(컨텍스트 메뉴)이라 쓰지 않는다. 기존 플랫폼 분기 패턴(`cvat-ui/src/components/bulk-wrapper.tsx`의 `isMac ? metaKey : ctrlKey`)을 따른다. 사용자 결정(Jira).
- **복사·삭제는 사람 단위로 확장.** 키포인트만 선택된 상태에서 복사·삭제하면 그 키포인트가 속한 사람 전체가 대상이 된다. 삭제는 기존 "여러 명 선택 후 Delete"와 같이 Undo 한 번으로 되돌린다. 사용자 결정(Jira).
- **bbox는 기존 soft-snap 규칙을 따른다.** soft-snap은 키포인트가 bbox 밖으로 나가면 bbox를 넓혀 감싸고, 줄이지는 않는 규칙이다(`cvat-core/src/annotations-objects.ts`의 스켈레톤 `save`). 한 사람의 키포인트가 모두 선택되어 움직이면 그 사람의 bbox도 같은 거리만큼 함께 이동한다. 사용자 결정(Jira). bbox 저장 규칙은 `docs/plans/2026-05-19-001-feat-skeleton-bbox-persistence-plan.md`, 경계 제한은 INNO-158 R3을 따른다.
- **한 번의 이동 = 한 번의 Undo.** 여러 사람의 키포인트를 한 번에 옮긴 이동은 Undo 한 번으로 전부 되돌아간다. 사용자 결정(Jira). 기존 사람 단위 다중 이동도 같은 이동 경로를 쓰게 되므로 같은 규칙을 적용한다(사용자 기대 "한 동작 = 한 Undo"의 연장). 가정 — AS5.
- **"사람 전체 선택" = "그 사람의 보이는 키포인트 전부 선택".** 보이는 키포인트는 hidden·outside가 아닌 키포인트다. 이동·복사·삭제 규칙을 두 선택 방식에 똑같이 적용하기 위해 이렇게 본다. 그래서 Shift+클릭으로 고른 사람과 박스로 고른 키포인트가 섞여 있어도 한 번에 끌 수 있다. 가정 — AS1.

## Actors

- A1. 작업자·검수자(어노테이션 화면 Standard workspace에서 스켈레톤을 고치는 사람). 권한 변화는 없다.

## Requirements

**선택**

- R1. Shift+드래그 박스를 놓으면 박스 안에 중심점이 들어온 스켈레톤 키포인트만 선택된다. 박스에 걸친 사람 전체는 선택되지 않는다(중심점 판정은 가정 — AS3). 스켈레톤이 아닌 도형은 Q1을 따른다.
- R2. 숨김(hidden)·outside 상태라 화면에 그려지지 않은 키포인트는 박스로 선택되지 않는다.
- R3. 박스 선택은 기존 선택에 더해진다(현재 동작과 같다). 키포인트를 하나도 담지 못한 박스는 선택을 바꾸지 않는다.
- R4. mac `⌘+클릭`, Windows/Linux `Ctrl+클릭`으로 키포인트 하나를 선택에 넣거나 뺀다. 그 사람이 활성 상태가 아니어도 동작한다. 키포인트가 아닌 곳(빈 캔버스 포함)에서는 이 조합이 선택을 바꾸지 않는다.
- R5. 사람 전체 선택 중 그 사람의 키포인트 하나를 `⌘/Ctrl+클릭`하면 그 키포인트만 빠지고 나머지 키포인트는 선택에 남는다.
- R6. Shift+클릭(키포인트 위 포함)은 지금처럼 사람 한 명 전체를 토글한다. 수식키 없는 클릭은 지금처럼 선택을 바꾸지 않는다.
- R7. 선택된 키포인트는 키포인트마다 활성·hover 상태와 구별되는 강조를 받는다. 일부 키포인트만 선택된 사람에는 사람 단위 선택 표시(`cvat_canvas_shape_multiselected`)가 붙지 않는다.

**선택 해제·수명**

- R8. 빈 캔버스를 Shift·`⌘/Ctrl` 없이 클릭하면 사람 선택과 키포인트 선택이 모두 비워진다.
- R9. 키포인트 선택은 사람 선택과 같은 상황에서 함께 정리된다. 사람이 삭제되면 그 사람의 키포인트도 선택에서 빠진다. 가정 — AS6.
- R10. 박스를 그리는 중 Esc를 누르거나 창 포커스를 잃으면 박스가 취소되고 선택은 바뀌지 않는다.

**이동**

- R11. 선택된 키포인트 중 하나를 끌면 선택된 모든 키포인트가 같은 거리만큼 함께 움직인다. 여러 사람에 걸쳐 있어도, 그 사람들이 활성 상태가 아니어도 같다.
- R12. 선택된 사람 전체가 섞여 있으면 그 사람들도 함께 움직인다. 선택된 사람의 bbox를 끌어도 같은 묶음 전체가 움직인다(INNO-157 R11).
- R13. 선택되지 않은 키포인트를 끌면 그 키포인트만 움직이고 선택은 바뀌지 않는다(INNO-157 AE2).
- R14. 이동 후 bbox 밖으로 나간 키포인트가 있는 사람은 soft-snap으로 bbox가 늘어난다. bbox 갱신은 드래그를 놓을 때 반영된다. 가정 — AS7.
- R15. 한 사람의 보이는 키포인트가 모두 선택되어 함께 움직이면 그 사람의 bbox는 같은 거리만큼 평행 이동한다. 그중 잠긴 키포인트가 있어 제자리에 남으면 R14를 따른다.
- R16. 잠긴(lock) 키포인트·사람, 고정(pinned) 객체는 선택되어 있어도 움직이지 않는다(현재 다중 이동과 같은 규칙). 박스로 선택은 된다. 가정 — AS4.
- R17. 드래그 중 이미지 경계에 닿으면 선택 묶음 전체가 그 축으로 멈추고 묶음 안 상대 위치는 유지된다(INNO-158 R10·R11, 가정 — AS2). 멈출 때 따로 알림은 없다(INNO-158 R12).

**복사·삭제·Undo**

- R18. 키포인트만 선택된 상태에서 복사하면 그 키포인트가 속한 사람 전체가 복사된다. 붙여넣기는 기존 사람 복사와 같다.
- R19. 키포인트만 선택된 상태에서 Delete하면 그 키포인트가 속한 사람만 삭제된다. 커서 아래 활성(hover) 사람은 선택에 없으면 삭제되지 않는다. 가정 — AS8.
- R20. R19의 삭제는 Undo 한 번으로 모두 복구된다.
- R21. 한 번의 다중 이동(R11·R12)은 Undo 한 번으로 전부 되돌아가고, Redo 한 번으로 전부 다시 적용된다.
- R22. 단축키 바인딩은 바꾸지 않는다. 복사·Undo·Redo는 기존 바인딩 그대로다(Undo는 현재 `ctrl+z`, `cvat-ui/src/components/annotation-page/top-bar/left-group.tsx`).

**Shift+드래그 시작 위치 (INNO-157이 정본)**

- R23. Shift+드래그의 시작 위치 판정은 INNO-157 문서를 따른다. 요약하면 키포인트 위에서 시작하면 그 키포인트를 옮기고(INNO-157 R6), 키포인트가 아닌 bbox 안에서 시작하면 새 박스 선택을 시작한다(INNO-157 R1·R4).

## Acceptance Examples

- AE1. 3명이 서 있는 프레임. 세 사람 발목을 지나는 가로 띠로 Shift+드래그 → 6개 발목 키포인트만 강조, 사람 단위 선택 표시 없음. 발목 하나를 아래로 20px 끌기 → 6개 발목이 모두 20px 이동, 나머지 키포인트는 그대로.
- AE2. AE1 직후 Undo 한 번 → 6개 발목이 모두 원위치. Redo 한 번 → 다시 20px 이동.
- AE3. 사람 A의 손목이 bbox 아래 경계 근처. 선택한 손목을 bbox 밖으로 끌기 → 놓는 순간 A의 bbox 아래 변이 손목을 감싸도록 늘어남.
- AE4. 사람 B의 보이는 키포인트 전부가 들어오게 박스 선택(B에는 outside 키포인트 1개 있음) → 오른쪽으로 끌기 → B의 bbox가 크기 그대로 오른쪽으로 이동.
- AE5. (mac) 박스로 사람 C의 키포인트 5개 선택 → `⌘+클릭`으로 그중 1개 해제 → 4개만 강조. `⌘+클릭`으로 사람 D의 코 키포인트 추가 → 5개 강조. `⌘+클릭`이 키포인트를 몇 px 빗나가 빈 캔버스에 떨어짐 → 선택 그대로.
- AE6. 사람 C·D의 키포인트 일부만 선택, 커서는 사람 F 위 → Delete → C, D 두 사람만 삭제. Undo 한 번 → 둘 다 복구.
- AE7. 키포인트 일부만 선택 → 복사 → 붙여넣기 → 해당 사람 전체가 붙여넣기됨.
- AE8. 키포인트 선택 중, 선택되지 않은 사람 E의 무릎 위에서 Shift+드래그 → 무릎만 이동, 기존 선택 그대로.
- AE9. 여러 사람 키포인트 선택 후 왼쪽으로 끌다가 한 키포인트가 이미지 왼쪽 경계에 닿음 → 묶음 전체가 거기서 더 이상 왼쪽으로 가지 않음.
- AE10. 박스를 그리는 중 Esc → 박스 사라짐, 선택 변화 없음.

## Success Criteria

- 작업자가 여러 사람의 같은 관절 어긋남을 드래그 한 번으로 고치고, Undo 한 번으로 취소할 수 있다.
- 사람 전체 이동(카메라 흔들림 보정)은 Shift+클릭 선택 후 드래그로 여전히 가능하다.
- 단일 키포인트 드래그, 단일 사람 드래그·리사이즈, 회전에 회귀가 없다.

## Scope Boundaries

- 키포인트 선택 상태에서 라벨 변경·속성 편집·잠금·숨김 등 다른 일괄 조작은 하지 않는다. 이들은 지금처럼 활성 객체에만 적용된다.
- 키포인트만 따로 복사·삭제하는 기능은 없다(R18·R19로 사람 단위 확장).
- 사이드바 객체 목록은 키포인트 선택을 표시하지 않는다. 가정 — AS9.
- 커서 모양, 박스 모양(기존 `cvat_canvas_multiselect_box` 재사용), 박스를 그리는 중 미리보기 강조는 바꾸거나 추가하지 않는다. 가정 — AS10.
- 키보드만으로 키포인트를 선택하는 방법은 만들지 않는다. F1 단축키 목록 추가도 하지 않는다(마우스 조합).
- Review workspace 등 다른 workspace의 선택 동작은 바꾸지 않는다.
- 서버·저장 형식 변경 없음. 키포인트 선택은 화면 상태일 뿐 저장되지 않는다.

## Dependencies / Assumptions

- 현재 선택 상태(`annotations.selectedStatesID`, `cvat-ui/src/reducers/annotation-reducer.ts`)는 최상위 객체 ID만 담는다. 키포인트 선택을 담을 별도 상태가 필요하다(형태는 planning).
- 현재 키포인트는 스켈레톤이 활성화된 경우에만 끌 수 있다(`canvasView.ts` resizable 경로의 요소별 `draggable`). 실제로는 hover로 활성화되며, Ctrl을 누르고 있으면 hover 활성화가 막힌다(`mousemove`의 `if (e.ctrlKey || e.altKey) return`). 키포인트 `click` 처리는 비활성 스켈레톤에도 있으나 `canvas.clicked`는 `shiftKey`만 전달한다. 다른 사람의 선택 키포인트를 함께 옮기는 경로는 새로 필요하다. 기존 multi-drag는 요소 드래그에서 발동하지 않는다.
- 현재 다중 이동은 `canvas.multiedited` → `updateMultipleAnnotationsAsync` → 객체별 `save()`라 Undo가 객체 수만큼 쌓인다. cvat-core의 history(`annotations-history.ts`)에는 묶음 기능이 없고, 스켈레톤 `save`가 자체적으로 `freeze(true/false)`를 호출하므로 바깥에서 freeze로 감싸는 방식은 통하지 않는다. `annotations-collection.ts`의 `batchUpdatePoints`는 일반 도형 points만 다루고 검증·bbox soft-snap을 건너뛰어 재사용할 수 없다. 묶음 history가 새로 필요하다(planning).
- 다중 삭제는 이미 `batchRemove`로 Undo 한 번이다. 다만 기존 삭제 핸들러(`objects-list.tsx`의 `DELETE_OBJECT_STANDARD_WORKSPACE`)는 활성 객체도 삭제 대상에 더하고, 완전히 잠긴 사람이 있으면 force(Shift) 없이 전체가 실패한다. 후자는 기존 동작 그대로 둔다.
- soft-snap은 outside만 건너뛰고 hidden 키포인트는 bbox 계산에 넣는다. R15의 "보이는 키포인트" 판정과 맞는지 planning에서 확인한다.
- 활성이 아닌 사람의 bbox 사각형은 화면에 보이지 않는다(`canvas.scss`). 그 안의 Shift+드래그는 지금도 박스를 시작한다.
- `points` 도형에서는 Ctrl/Alt+클릭이 점 편집에 쓰인다(`canvasView.ts` 점 클릭 처리). 스켈레톤 키포인트에는 해당하지 않는다.

**가정 (결정에 없던 빈칸의 기본값)**

- AS1. 사람 전체 선택과 키포인트 선택을 섞을 수 있고, 섞여 있어도 한 묶음으로 움직인다. 비용: 두 선택을 하나의 이동 경로로 합쳐야 한다.
- AS2. 경계 클램프는 묶음 단위로 멈춘다(모양 보존). INNO-158 Q1 기본값과 같다.
- AS3. 박스 판정은 키포인트 중심점이 박스 안에 있는지로 한다(원 일부만 걸치면 제외).
- AS4. 잠긴 키포인트·사람도 박스로 선택은 되지만 움직이지 않는다.
- AS5. 한 동작 = 한 Undo를 기존 사람 단위 다중 이동에도 적용한다.
- AS6. 키포인트 선택 정리 규칙은 사람 선택과 같다(프레임 이동 시에도 객체가 남아 있으면 유지하는 현재 규칙 포함).
- AS7. bbox 확장은 드래그 중 실시간이 아니라 놓을 때 반영된다(현재 단일 키포인트 드래그와 같다).
- AS8. 키포인트 선택 상태의 삭제는 선택된 키포인트의 주인만 대상이며, hover로 활성된 사람은 더하지 않는다. 기존 사람 다중 삭제의 "활성 객체 추가" 동작과 다르다.
- AS9. 사이드바는 일부 키포인트만 선택된 사람을 표시하지 않는다.
- AS10. 커서·박스 모양·박스 미리보기는 현재 그대로다.

## Coordination

- INNO-157(Shift+드래그 시작 위치 판정)과 INNO-158(경계 클램프)은 같은 브랜치로 나간다. 시작 위치 규칙의 정본은 INNO-157, 경계 규칙의 정본은 INNO-158이다. 이 문서의 R17·R23은 그 문서들을 인용만 한다.
- Q1은 INNO-157 Q2와 같은 질문이다. 한 번 답하면 두 문서에 함께 반영한다.

## 미결정 사항 (사용자 확인 필요)

- Q1. **스켈레톤이 아닌 도형(사각형·폴리곤 등)과 박스 선택.** 권장: 지금처럼 박스에 걸치면 객체 전체가 선택된다(사각형 등만 쓰는 잡의 회귀 방지, INNO-157 Q2와 동일 권장). 대안: 박스는 스켈레톤 키포인트만 고르고 다른 도형은 무시("키포인트만 선택"의 문자적 적용). 스켈레톤 외 도형을 쓰는 작업이 없다면 영향이 없다. 시안 전에 정하면 화면이 하나로 정해진다.
- Q2. **키포인트만 선택했을 때 삭제·복사 대상(사람 전체)을 미리 보여줄지.** 권장: 표시하지 않음(R7, 결정된 "사람 단위 선택 표시 없음"과 일치, Undo로 복구 가능). 대안: 주인 스켈레톤에 옅은 외곽 표시, 또는 삭제 후 "N명 삭제됨" 알림.

## Sources / Research

- 박스 선택·다중 이동: `cvat-canvas/src/typescript/canvasView.ts`(`onCanvasMouseDown`, `finishMultiSelect`, `draggable`의 multi-drag, `updateSelection`), `cvat-canvas/src/scss/canvas.scss`(`.cvat_canvas_shape_multiselected`)
- UI 선택·Shift+클릭: `cvat-ui/src/components/annotation-page/canvas/views/canvas2d/canvas-wrapper.tsx`(`onCanvasMouseDown`/`onCanvasMouseUp`, `onCanvasMultiEdited`, `onCanvasMultiSelected`), `cvat-ui/src/reducers/annotation-reducer.ts`
- 복사·삭제: `cvat-ui/src/containers/annotation-page/standard-workspace/objects-side-bar/objects-list.tsx`(`COPY_SHAPE`, `DELETE_OBJECT_STANDARD_WORKSPACE`), `cvat-ui/src/actions/annotation-actions.ts`(`removeObjectsAsync`, `copyShapes`, `updateMultipleAnnotationsAsync`)
- Undo·soft-snap: `cvat-core/src/annotations-history.ts`, `cvat-core/src/annotations-collection.ts`(`batchUpdatePoints`, `batchRemove`), `cvat-core/src/annotations-objects.ts`(스켈레톤 `save`)
- 플랫폼 키 분기: `cvat-ui/src/components/bulk-wrapper.tsx`
- 관련 문서: `docs/brainstorms/2026-11-04-inno-157-box-select-inside-bbox-requirements.md`, `docs/brainstorms/2026-11-04-inno-158-clamp-to-image-requirements.md`
