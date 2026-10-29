---
date: 2026-10-28
topic: inno-125-workspace-toggle-shortcut
ticket: INNO-125
---

# INNO-125 Standard ↔ Review 모드 전환 단축키 (`Z`)

## Summary

검수자 계정에서만 `Z` 한 번으로 어노테이션 화면의 workspace를 Standard ↔ Review로 전환한다. 전환 시 프레임·확대 위치·선택 상태는 유지되고, 피드백은 알림 대신 workspace 드롭다운 테두리를 0.5초 파랗게 강조하는 것으로 준다. 단축키는 F1 목록에 노출되고 F2 > Shortcuts에서 바꿀 수 있다.

## Problem Frame

검수자는 Standard(수정)와 Review(이슈 작성)를 자주 오간다. 지금은 우측 상단 workspace 드롭다운(`cvat-ui/src/components/annotation-page/top-bar/right-group.tsx`의 `Select`)을 마우스로 열어 고르는 수밖에 없다. 단축키 키(`Z`)와 동작은 검수자와 합의가 끝났다(Slack에서 W→Z로 변경). 이 문서는 합의된 시안을 코드 현실에 맞춰 빈칸을 채운다.

## Key Decisions

- **키는 `Z` 단독 (합의 완료).** 코드상 `Z` 단독 바인딩은 없다 — 쓰이는 것은 `ctrl+z`(Undo), `ctrl+shift+z`(Redo)뿐이다(`top-bar/left-group.tsx`). SAM 플러그인(`cvat-ui/plugins/sam`)·`cvat-canvas`에도 `z` 키 처리가 없다. 기존 충돌 판정(`utils/conflict-detector.ts`의 `conflict`)도 `z`와 `ctrl+z`를 충돌로 보지 않는다.
- **"검수자" = 시스템 그룹 `reviewer` 소속 (admin 겸직 포함).** 잡을 열 때 기본 workspace를 Review로 정하는 기존 판정(`actions/annotation-actions.ts`의 `isReviewer = groups.includes('reviewer')`)과 같은 기준을 쓴다. "기본으로 Review로 열리는 사람 = 토글이 필요한 사람"이라 일관된다. 저장 생략용 `isReviewerOnly`(reviewer이면서 admin 아님)와는 목적이 달라 따르지 않는다. 여기에 더해 현재 잡의 조직에서 멤버십 역할이 `reviewer`인 사용자도 검수자로 본다. 사용자 결정 2026-10-28: 조직 reviewer 역할 포함 — Q1.
- **어노테이션 화면 전체 스코프에 등록.** 기존 `ShortcutScope.ANNOTATION_PAGE`에 넣는다. 이 스코프는 충돌 검사 시 모든 workspace 스코프와 대조되므로(`conflict-detector.ts`의 `updatedFlatKeyMap`), 검수자가 다른 단축키를 `Z`로 바꾸거나 토글을 다른 키로 바꿀 때 기존 충돌 확인 모달(`settings-modal/multiple-shortcuts-display.tsx`)이 그대로 작동한다.
- **전환 규칙은 시안의 동작 규칙을 따른다.** Review → Standard, 그 외 모든 모드(Standard, Attribute annotation, Single shape, Tag annotation) → Review. "원래 모드 기억"은 하지 않는다 — Attribute에서 `Z` 두 번이면 Standard로 간다. 가정(사용자 확인 대기) — 미결정 Q3.
- **선택 상태 유지는 `Z` 전환에만 적용.** 현재 드롭다운 전환은 reducer(`reducers/annotation-reducer.ts`의 `CHANGE_WORKSPACE`)에서 활성 객체·선택 목록을 비운다. 시안이 "드롭다운 기존 동작 모두 유지"와 "Z는 선택 유지"를 함께 요구하므로, 두 경로의 동작이 갈린다. 가정(사용자 확인 대기) — 미결정 Q2.

## Actors

- A1. 검수자(`reviewer` 그룹 사용자): `Z`로 전환한다.
- A2. 그 외 사용자(annotator, admin 단독 등): 아무 변화도 보지 않는다.

## Requirements

**전환 동작**

- R1. 검수자가 어노테이션 화면에서 `Z`를 누르면 현재 workspace가 Review면 Standard로, 그 외면 Review로 즉시 바뀐다.
- R2. 어느 workspace(Standard, Review, Attribute, Single shape, Tag)에서든 `Z`가 동작한다.
- R3. 전환 후 현재 프레임과 캔버스 확대·이동 위치가 유지된다.
- R4. 전환 후 활성 객체·선택 객체가 유지된다(대상 workspace에서 표시 가능한 범위 내).
- R5. 입력창(input/textarea/select)에 포커스가 있으면 `Z`는 글자 입력으로만 처리되고 전환하지 않는다.
- R6. 그리기·편집 등 커서 모드가 아닌 상태에서는 `Z`가 무시된다(기존 드롭다운 전환과 같은 제약). 강조도 일어나지 않는다.
- R7. 모달이 열려 있으면 `Z`는 동작하지 않는다(기존 단축키 공통 동작).

**피드백·표시**

- R8. 전환은 알림 메시지를 띄우지 않는다. 드롭다운 값이 바뀌고, 드롭다운 테두리가 0.5초 파랗게 강조된다.
- R9. 테두리 강조는 단축키로 바뀐 경우에만 나타난다. 마우스로 드롭다운을 고른 경우는 지금과 같다.
- R10. 검수자에게는 드롭다운 목록의 Standard·Review 항목 옆에 현재 설정된 토글 키가 표시된다(기본 `Z`). 키를 F2에서 바꾸면 표시도 따라 바뀌고, 키를 비우면 표시도 사라진다.

**단축키 목록·설정**

- R11. 검수자의 F1 목록에 `Switch Standard/Review` 항목이 `z`로 표시된다.
- R12. 검수자는 F2 > Settings > Shortcuts에서 이 키를 바꿀 수 있고, 변경은 다른 단축키 변경과 동일하게 브라우저에 저장·복원된다.
- R13. 다른 단축키와 겹치는 키로 바꾸면 기존 충돌 확인 모달이 뜬다.

**비검수자**

- R14. 검수자가 아닌 계정에서는 단축키가 등록되지 않는다 — `Z`는 무반응, F1·F2 목록과 드롭다운에 토글 키가 보이지 않는다.
- R15. 드롭다운으로 workspace를 바꾸는 기존 동작은 모든 계정에서 그대로다.

## Acceptance Examples

- AE1. 검수자, Standard, 프레임 37, 객체 #5 활성 → `Z` → Review, 프레임 37, 객체 #5 활성, 드롭다운 테두리 0.5초 파랑. 다시 `Z` → Standard, 같은 상태.
- AE2. 검수자, Attribute annotation → `Z` → Review → `Z` → Standard.
- AE3. 검수자, Review 이슈 코멘트 입력창에 커서 → `z` 입력 → 글자 `z`만 입력되고 모드 그대로.
- AE4. 검수자, 폴리곤 그리는 중 → `Z` → 아무 변화 없음.
- AE5. annotator 계정 → `Z` → 무반응. F1에 항목 없음. 드롭다운 항목 옆 `Z` 없음.
- AE6. 검수자가 F2에서 "Next frame"(`f`)을 `z`로 바꾸려 함 → 충돌 모달에 `Switch Standard/Review` 표시.
- AE7. 검수자가 Ctrl을 늦게 눌러 `z`만 입력 → Review로 바뀜 → `Z` 한 번 더로 복귀(합의된 허용 리스크).

## Success Criteria

- 검수자가 마우스 없이 Standard ↔ Review를 오갈 수 있다.
- 비검수자 화면·동작에 관찰 가능한 변화가 없다.
- 기존 단축키 동작에 회귀가 없다(Undo/Redo 포함).

## Scope Boundaries

- 다른 workspace(Attribute 등)로 가는 단축키, 임의 모드 순환은 하지 않는다.
- 드롭다운 전환 동작(선택 해제 포함)은 바꾸지 않는다.
- 서버·권한(OPA) 변경 없음. 순수 UI 작업이다.
- 사용자별 단축키 설정의 서버 동기화는 하지 않는다(기존처럼 localStorage).

## Dependencies / Assumptions

- 사용자 그룹은 로그인 시 `state.auth.user.groups`로 들어온다(기존 `isReviewer`/`isReviewerOnly`가 사용하는 값).
- 단축키 목록은 import 시점에 전역 등록되는 구조다(`registerComponentShortcuts`, `actions/shortcuts-actions.ts`). F2 목록은 store의 keyMap 전체를, F1 목록은 현재 바인딩된 단축키(`utils/mousetrap-react.tsx`의 `getApplicationKeyMap`)를 보여준다. 따라서 "비검수자 미등록"은 기존처럼 모듈 로드 시 무조건 등록하는 방식으로는 충족되지 않는다.
- F2 커스텀 키 저장·복원(`actions/settings-actions.ts`의 `restoreSettingsAsync`/`updateCachedSettings`)은 복원 시점에 keyMap에 있던 항목만 다룬다. 검수자 판정 후 늦게 등록하면 커스텀 키가 복원·저장되지 않을 수 있다.
- 드롭다운 전환 시 workspace 컴포넌트가 바뀌며 캔버스가 재부착되고 `fitCanvas()`가 호출된다(`canvas-wrapper.tsx` `initialSetup`).
- 미검증: Mousetrap은 수식키를 정확히 맞추므로 mac `⌘Z`는 `z` 바인딩을 트리거하지 않는다고 가정한다.
- 드롭다운으로 바꾼 직후엔 컨테이너가 포커스를 해제한다(`containers/annotation-page/top-bar/top-bar.tsx`의 `changeWorkspace`가 `activeElement.blur()`). 따라서 마우스 전환 뒤 곧바로 `Z`를 눌러도 R5 입력창 규칙에 걸리지 않는다고 본다. 다만 드롭다운이 열린 채(포커스 중)일 때 `Z`는 막힌다.
- 캔버스 `fitCanvas`(`cvat-canvas/src/typescript/canvasModel.ts`)는 캔버스 크기만 갱신하고 배율·위치는 건드리지 않는다. 따라서 R3는 현재 드롭다운 경로에서도 이미 성립할 가능성이 높다(실행 확인 필요).

## Coordination

- INNO-127도 F1 목록에 단축키(Delete issue, `⌘⌫`/`Ctrl+Del`)를 추가한다. 키 충돌은 없지만 같은 단축키 등록·F1 경로를 건드리므로 병합 순서를 맞추고, 둘 다 머지된 상태에서 충돌 감지·F1 표시를 함께 확인한다.

## 미결정 사항 (사용자 확인 필요)

- Q1. **검수자 판정 기준.** 사용자 결정 2026-10-29: admin 단독 계정도 포함(대안 c 추가). 사용자 결정 2026-10-28: 조직 reviewer 역할 포함 — 시스템 그룹 `reviewer`(admin 겸직 포함) 또는 현재 잡의 조직 역할 `reviewer`. (당시 권장: 시스템 그룹 `reviewer` 포함 여부(admin 겸직 포함). 근거: 기본 Review 진입 판정과 동일. 대안: (a) `isReviewerOnly`처럼 admin 겸직 제외, (b) 조직 멤버십 역할 `reviewer`까지 포함, (c) admin 단독 계정에도 허용.)
- Q2. **선택 유지가 `Z`에만 적용되어 드롭다운과 동작이 갈리는 점.** 권장: 시안대로 `Z`만 선택 유지, 드롭다운은 기존(선택 해제) 유지. 대안: 드롭다운도 선택 유지로 통일(시안의 "드롭다운 기존 동작 유지"와 충돌).
- Q3. **Attribute 등에서 `Z`로 Review에 간 뒤 다시 `Z`의 목적지.** 권장: 항상 Standard(시안 동작 규칙). 대안: 직전 모드로 복귀("한 번 더 누르면 원래 모드로" 문구의 문자적 해석).
- Q4. **F2 목록에서 비검수자에게 항목 숨김.** 권장: 숨김(R14, "등록 안 함"의 자연스러운 해석). 대안: 비활성(회색) 표시 — 기존 `nonActive` 패턴 재사용으로 구현이 단순하지만 시안의 "안 보임" 취지에 어긋남.

## Sources / Research

- 단축키 구조: `cvat-ui/src/utils/mousetrap-react.tsx`, `utils/conflict-detector.ts`, `utils/enums.tsx`(`ShortcutScope`), `actions/shortcuts-actions.ts`, `reducers/shortcuts-reducer.ts`
- F1/F2: `components/shortcuts-dialog/shortcuts-dialog.tsx`, `components/header/settings-modal/shortcut-settings.tsx`, `multiple-shortcuts-display.tsx`, `actions/settings-actions.ts`
- workspace: `components/annotation-page/top-bar/right-group.tsx`, `reducers/annotation-reducer.ts`(`GET_JOB_SUCCESS`, `CHANGE_WORKSPACE`), `reducers/index.ts`(`Workspace`)
- 검수자 판정: `actions/annotation-actions.ts`(`isReviewer`, `isReviewerOnly`), `top-bar/annotation-menu.tsx`
