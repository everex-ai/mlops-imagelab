# Multi-Selection: Drag & Delete 기능 문서

## 개요

CVAT 캔버스에 **다중 선택(Multi-Selection)** 기능을 추가하여, 여러 어노테이션 객체를 한 번에 선택/이동/삭제할 수 있도록 구현했습니다. 기존의 단일 활성 객체(Single Active Element) 모델은 그대로 유지하면서, 별도의 `selectedStatesID` 배열을 통해 멀티 셀렉션을 관리합니다.

### 지원 대상
- 모든 셰이프 타입: Skeleton, Rectangle, Polygon, Polyline, Ellipse, Points, Mask

---

## 사용자 인터페이스

### 1. Shift+Click 선택
- 객체 위에서 **Shift+클릭**하면 해당 객체가 선택 목록에 추가/제거됩니다 (토글)
- 현재 활성화된 객체는 첫 Shift+Click 시 자동으로 선택 목록에 포함됩니다
- 선택된 객체는 **파란색 점선 테두리**(#40a9ff)로 표시됩니다

### 2. Shift+드래그 영역 선택
- 빈 캔버스 영역에서 **Shift+드래그**하면 파란색 반투명 선택 박스가 나타납니다
- 마우스를 놓으면 박스 안에 포함된 모든 객체가 선택됩니다
- 선택 박스 스타일: 파란색(#40a9ff) 배경 15% 투명도, 2px 점선 테두리

### 3. 선택 해제
- Shift 없이 빈 캔버스를 클릭하면 모든 선택이 해제됩니다
- 프레임 변경 시 선택이 초기화됩니다

### 4. 다중 드래그
- 선택된 객체 중 하나를 드래그하면 **모든 선택된 객체가 동일한 거리만큼 이동**합니다
- Pinned 객체는 선택에 포함되지만 이동하지 않습니다
- 드래그 완료 시 하나의 Undo 엔트리로 기록됩니다

### 5. 다중 삭제
- 여러 객체가 선택된 상태에서 **Delete 키**를 누르면 확인 다이얼로그가 표시됩니다
- "N개의 객체를 삭제하시겠습니까?" 메시지와 함께 트랙/잠금 경고 표시
- 확인 시 모든 선택된 객체가 일괄 삭제되며, **Ctrl+Z 한 번으로 전체 복원** 가능

---

## 아키텍처

### 상태 관리 구조

```
activatedStateID (기존, 변경 없음)
  → 사이드바 상세 표시, 속성 편집, 컨텍스트 메뉴, 키보드 단축키

selectedStatesID (신규)
  → 다중 드래그, 다중 삭제, 시각적 선택 표시
  → activatedStateID는 항상 selectedStatesID에 암묵적으로 포함
```

### 데이터 흐름

```
사용자 액션 → 캔버스 이벤트 → Redux 액션 → 리듀서 → 컴포넌트 업데이트 → 캔버스 동기화
```

#### Shift+Click 선택 흐름
```
mousedown(Shift) → 시작 좌표 기록
  ↓
mouseup(Shift, 이동 < 5px)
  ↓
elementFromPoint로 클릭된 셰이프 감지
  ↓
toggleObjectSelection(clientID)
  ↓
TOGGLE_OBJECT_SELECTION 리듀서
  ↓
selectedStatesID 배열에 ID 추가/제거
  ↓
componentDidUpdate → canvasInstance.setSelection()
  ↓
CSS 클래스 cvat_canvas_shape_multiselected 적용/제거
```

#### Shift+드래그 영역 선택 흐름
```
mousedown(Shift, 빈 캔버스) → 선택 박스 SVG Rect 생성
  ↓
mousemove → 선택 박스 크기 업데이트
  ↓
mouseup → 박스 내 객체의 clientID 수집
  ↓
canvas.multiselected 이벤트 발송
  ↓
onCanvasMultiSelected → selectObjects(clientIDs)
  ↓
SELECT_OBJECTS 리듀서 → selectedStatesID 교체
```

#### 다중 드래그 흐름
```
dragstart (활성 셰이프)
  ↓
selectedClientIDs 내 다른 셰이프의 시작 위치 저장
  ↓
dragmove → 활성 셰이프의 delta 계산 → 선택된 셰이프에 동일 delta 적용
  ↓
dragend → canvas.multiedited 이벤트 발송 (edits 배열)
  ↓
onCanvasMultiEdited → updateMultipleAnnotationsAsync(statesToUpdate)
  ↓
batchUpdatePoints → 단일 히스토리 엔트리로 기록
```

#### 다중 삭제 흐름
```
Delete 키 → selectedStatesID + activatedStateID 합집합
  ↓
removeObjects(statesToRemove, force)
  ↓
RemoveConfirmComponent (확인 다이얼로그)
  ↓
removeObjectsAsync → batchRemove(objectStates, force, frame)
  ↓
단일 히스토리 엔트리로 기록 → REMOVE_OBJECTS_SUCCESS
  ↓
selectedStatesID 및 activatedStateID 초기화
```

---

## 수정 파일 상세

### 1. Redux 상태 및 액션

#### `cvat-ui/src/reducers/index.ts`
- `AnnotationState.annotations`에 `selectedStatesID: number[]` 타입 추가

#### `cvat-ui/src/actions/annotation-actions.ts`

**새 액션 타입:**
```typescript
SELECT_OBJECTS = 'SELECT_OBJECTS'
TOGGLE_OBJECT_SELECTION = 'TOGGLE_OBJECT_SELECTION'
REMOVE_OBJECTS = 'REMOVE_OBJECTS'
REMOVE_OBJECTS_SUCCESS = 'REMOVE_OBJECTS_SUCCESS'
REMOVE_OBJECTS_FAILED = 'REMOVE_OBJECTS_FAILED'
```

**새 액션 크리에이터:**
```typescript
selectObjects(stateIDs: number[]): AnyAction
toggleObjectSelection(stateID: number): AnyAction
```

**새 비동기 Thunk:**
```typescript
removeObjectsAsync(objectStates: ObjectState[], force: boolean): ThunkAction
updateMultipleAnnotationsAsync(statesToUpdate: any[]): ThunkAction
```

#### `cvat-ui/src/reducers/annotation-reducer.ts`

**새 리듀서 케이스:**
- `SELECT_OBJECTS`: `selectedStatesID`를 payload 배열로 교체
- `TOGGLE_OBJECT_SELECTION`: ID를 배열에 추가/제거 토글. 첫 토글 시 activatedStateID 자동 포함
- `REMOVE_OBJECTS_SUCCESS`: 삭제된 ID들을 states에서 필터링, 선택/활성 초기화

**기존 케이스 수정:**
- `ACTIVATE_OBJECT`: 선택이 존재할 때(`selectedStatesID.length > 0`) 선택 유지
- `CHANGE_FRAME_SUCCESS`: `selectedStatesID: []` 초기화
- `FETCH_ANNOTATIONS_SUCCESS`: `selectedStatesID: []` 초기화
- `REMOVE_OBJECT_SUCCESS`: 해당 ID를 `selectedStatesID`에서 필터링

---

### 2. 캔버스 라이브러리

#### `cvat-canvas/src/typescript/canvasModel.ts`

**새 상태 및 메서드:**
```typescript
// data 객체에 추가
selectedClientIDs: number[]

// UpdateReasons enum에 추가
OBJECTS_SELECTED = 'objects_selected'

// 새 메서드
public setSelection(clientIDs: number[]): void
public get selectedClientIDs(): number[]
```

#### `cvat-canvas/src/typescript/canvas.ts`

**공개 API 추가:**
```typescript
public setSelection(clientIDs: number[]): void
```

#### `cvat-canvas/src/typescript/canvasView.ts`

이 파일이 가장 큰 변경을 포함합니다:

**새 프라이빗 상태:**
```typescript
private selectedClientIDs: number[] = [];
private multiSelectBox: SVG.Rect | null = null;
private multiSelectStart: { x: number; y: number } | null = null;
```

**새 메서드:**
| 메서드 | 역할 |
|--------|------|
| `updateSelection(clientIDs)` | CSS 클래스 `cvat_canvas_shape_multiselected` 적용/제거 |
| `moveShapeVisually(shape, state, startPos, dx, dy)` | 셰이프 타입별 시각적 이동 처리 |

**수정된 핵심 로직:**

1. **`canvas.moved` 이벤트에 `shiftKey` 추가**: 마우스 이동 이벤트에 Shift 키 상태 전달
2. **Shift+드래그 영역 선택**: `mousedown`에서 Shift+빈 캔버스 감지 → 선택 박스 생성 → `mouseup`에서 박스 내 객체 수집
3. **다중 드래그**: `draggable()` 메서드 내 `dragstart`/`dragmove`/`dragend`에 선택된 셰이프 동시 이동 로직 추가
4. **드래그 방지**: 선택된 비활성 셰이프 클릭 시 캔버스 패닝 방지
5. **Skeleton 노드 shiftKey 전파**: `addSkeleton()` 내 노드 클릭 핸들러에 `shiftKey` 추가

**새 커스텀 이벤트:**
| 이벤트 | Detail | 용도 |
|--------|--------|------|
| `canvas.multiselected` | `{ clientIDs: number[] }` | 영역 드래그 선택 완료 |
| `canvas.multiedited` | `{ edits: Array<{state, points}> }` | 다중 드래그 완료 |

#### `cvat-canvas/src/scss/canvas.scss`

**수정된 스타일:**
```scss
.cvat_canvas_multiselect_box {
    fill: #40a9ff;
    fill-opacity: 0.15;
    stroke: #40a9ff;
    stroke-width: 2;
    stroke-dasharray: 6 3;
}
```

---

### 3. UI 통합

#### `cvat-ui/src/components/annotation-page/canvas/views/canvas2d/canvas-wrapper.tsx`

**새 프로퍼티:**
```typescript
private shiftClickStart: { x: number; y: number } | null = null;
```

**Props 추가:**
```typescript
selectedStatesID: number[]          // Redux에서
onToggleObjectSelection(stateID)    // dispatch
onSelectObjects(stateIDs)           // dispatch
onUpdateMultipleAnnotations(states) // dispatch
```

**수정된 이벤트 핸들러:**

| 핸들러 | 변경 내용 |
|--------|----------|
| `onCanvasMouseDown` | Shift 없이 빈 캔버스 클릭 시 선택 해제, Shift+mousedown 좌표 기록 |
| `onCanvasMouseUp` (신규) | Shift+Click 감지 → `elementFromPoint`로 셰이프 찾기 → `toggleObjectSelection` |
| `onCanvasShapeClicked` | Shift+Click 시 early return (onCanvasMouseUp에 위임, 중복 방지) |
| `onCanvasCursorMoved` | `shiftKey` 시 auto-activate 차단 |
| `onCanvasMultiSelected` (신규) | `canvas.multiselected` → `selectObjects(clientIDs)` |
| `onCanvasMultiEdited` (신규) | `canvas.multiedited` → `updateMultipleAnnotationsAsync` |
| `componentDidUpdate` | `selectedStatesID` 변경 시 `canvasInstance.setSelection()` 동기화 |

---

### 4. 다중 삭제 UI

#### `cvat-ui/src/containers/annotation-page/standard-workspace/objects-side-bar/objects-list.tsx`

**DELETE 키 핸들러 수정:**
```typescript
// selectedStatesID가 있으면 다중 삭제 경로
if (selectedStatesID.length > 0 && !readonly) {
    const allIDs = new Set([...selectedStatesID]);
    if (activatedStateID !== null) allIDs.add(activatedStateID);
    const statesToRemove = objectStates.filter(s => allIDs.has(s.clientID));
    removeObjects(statesToRemove, event?.shiftKey || false);
}
```

#### `cvat-ui/src/components/annotation-page/standard-workspace/remove-confirm.tsx`

- `objectStates` 배열 처리 지원
- 다중 삭제 시: "N개의 객체를 삭제하시겠습니까?" 메시지 표시
- 트랙/잠금 객체 포함 시 경고 표시

---

### 5. 일괄 Undo 지원 (cvat-core)

#### `cvat-core/src/annotations-collection.ts`

**`batchRemove(objectStates, force, frame)`:**
- 모든 대상 객체 유효성 검증
- 잠금 객체 확인 (force가 아닌 경우 에러)
- 모든 객체를 `removed = true`로 설정
- 단일 `history.do()` 호출로 Undo/Redo 클로저 생성
  - Undo: 모든 객체 `removed = false` 복원
  - Redo: 모든 객체 다시 `removed = true`

**`batchUpdatePoints(updates)`:**
- `updates`: `{ clientID, points, frame }[]` 배열
- 기존 포인트를 백업 (Undo용)
- `history.freeze(true)` → 개별 업데이트 수행 → `history.freeze(false)`
- 단일 `history.do()` 호출로 일괄 Undo 지원
  - Undo: 모든 포인트를 백업 값으로 복원
  - Redo: 모든 포인트를 새 값으로 다시 적용

---

## 엣지 케이스 처리

| 시나리오 | 동작 |
|----------|------|
| Pinned 객체 선택 후 드래그 | 선택에는 포함되나 이동하지 않음 |
| Locked 객체 선택 후 삭제 | force=true 시에만 삭제 가능, 확인 경고 표시 |
| 프레임 변경 | `selectedStatesID: []` 초기화 |
| 모드 변경 (DRAW, EDIT, MERGE 등) | IDLE이 아니면 선택 불가 |
| 드래그 중 abort (Esc) | 모든 선택된 셰이프를 원래 위치로 복원 |
| Skeleton 노드 Shift+Click | 부모 Skeleton의 clientID로 토글 |
| Z-Layer 변경 | 숨겨진 객체는 선택에서 자동 제거되지 않음 (향후 개선 가능) |

---

## 수정 파일 목록

| 파일 | 난이도 |
|------|--------|
| `cvat-ui/src/reducers/index.ts` | 하 |
| `cvat-ui/src/actions/annotation-actions.ts` | 중 |
| `cvat-ui/src/reducers/annotation-reducer.ts` | 중 |
| `cvat-canvas/src/typescript/canvasModel.ts` | 하 |
| `cvat-canvas/src/typescript/canvas.ts` | 하 |
| `cvat-canvas/src/typescript/canvasView.ts` | **상** |
| `cvat-canvas/src/scss/canvas.scss` | 하 |
| `cvat-ui/src/components/.../canvas-wrapper.tsx` | 중 |
| `cvat-ui/src/containers/.../objects-list.tsx` | 하 |
| `cvat-ui/src/components/.../remove-confirm.tsx` | 하 |
| `cvat-core/src/annotations-collection.ts` | 중 |

---

## 디버깅 시 발견된 주요 이슈 및 해결

### 1. 캔버스 패닝 문제
- **증상**: 선택된 셰이프를 클릭하면 이미지가 드래그됨
- **원인**: `mousedown`에서 `enableDrag()` 호출이 선택된 셰이프를 고려하지 않음
- **해결**: `selectedClientIDs`에 포함된 셰이프 클릭 시 `enableDrag()` 스킵

### 2. ACTIVATE_OBJECT가 선택을 초기화하는 문제
- **증상**: Shift+Click 시 선택이 바로 사라짐
- **원인**: `ACTIVATE_OBJECT` 리듀서가 `selectedStatesID: []`로 초기화
- **해결**: `keepSelection = currentSelectedIDs.length > 0` 조건으로 선택 유지

### 3. Skeleton에서 Shift+Click이 동작하지 않는 문제
- **증상**: Skeleton 노드에 Shift+Click 해도 선택되지 않음
- **원인**: CVAT는 `canvas.clicked`이 아닌 `canvas.moved`(mousemove)로 객체를 활성화. Shift 키 상태가 전달되지 않아 auto-activate가 차단되지 않음
- **해결**: `canvas.moved` 이벤트에 `shiftKey` 추가, `onCanvasCursorMoved`에서 shiftKey 시 early return

### 4. 이중 토글 문제 (가장 최근 수정)
- **증상**: Shift+Click이 선택을 추가했다가 바로 제거함
- **원인**: `onCanvasMouseUp`과 `onCanvasShapeClicked` 두 핸들러가 모두 `toggleObjectSelection`을 호출하여 이중 토글 발생
- **해결**: `onCanvasShapeClicked`에서 Shift+Click 처리를 제거, `onCanvasMouseUp`이 전담

---

## 검증 방법

### 수동 테스트
1. 객체를 클릭하여 활성화 → 다른 객체에 Shift+Click → 파란 점선 테두리 확인
2. 빈 영역에서 Shift+드래그 → 파란 선택 박스 표시 → 영역 내 객체 선택 확인
3. 선택된 객체 중 하나 드래그 → 모든 선택된 객체 동시 이동 확인
4. Delete 키 → 확인 다이얼로그 → 전체 삭제 확인
5. Ctrl+Z → 삭제된 객체 전체 복원 확인
6. Shift 없이 빈 영역 클릭 → 선택 해제 확인

### 빌드 확인
```bash
yarn build:cvat-canvas && yarn build:cvat-core && yarn build:cvat-ui
```
