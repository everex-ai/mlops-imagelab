---
date: 2026-10-28
topic: inno-126-reviewer-only-reject
ticket: INNO-126
---

# 검수자만 job을 반려(rejected)할 수 있게 하기 (INNO-126)

## Summary

job state를 `rejected`로 바꾸는 동작을 검수자(reviewer)와 관리자(admin)에게만 허용한다. 작업자 화면에서는 `rejected` 항목을 숨기지 않고 비활성+툴팁으로 보여주고, 서버는 `jobs.rego`의 `update:state` 규칙에서 요청 값이 `rejected`인지 확인해 403으로 거부한다. `rejected` → 다른 상태로의 전환은 막지 않는다.

## Problem Frame

현재는 job 담당자(작업자)도 job state를 `rejected`로 바꿀 수 있다. 화면도 서버도 막지 않는다.

- `cvat/apps/engine/rules/jobs.rego`는 `is_job_staff`(job/task/project 담당자·소유자)에게 `update:state`를 허용하고, 바꾸려는 **값**은 보지 않는다.
- 값을 볼 수도 없다. `JobPermission`(`cvat/apps/engine/permissions.py`)은 PATCH 본문의 필드 **이름**으로 scope만 고르고(`get_per_field_update_scopes`: `state` → `update:state`), OPA input에는 `scope`/`auth`/`resource`(DB의 현재 job)만 실린다. 요청된 새 state는 OPA까지 가지 않는다.
- UI의 세 진입점이 모두 네 상태를 그대로 노출한다: 어노테이션 화면 Menu > Change job state(`annotation-menu.tsx`), Jobs 목록 ⋮ > State(`jobs-page/actions-menu.tsx`, 다중 선택 시 일괄), 그리고 같은 `JobStateSelector`를 쓰는 Task 상세의 job 카드(`job-item/job-item.tsx`).

반려는 검수 라운드를 닫는 검수자의 판단이다. 작업자가 반려를 찍으면 라운드 기록(job round-boundary 스냅샷)과 INNO-123의 `검수 반려` 알림이 실제 검수 없이 발생한다.

## Actors

- A1. 작업자: job 담당자. `rejected`로 바꿀 수 없다. `rejected` 상태의 job을 `in progress`/`completed`로 바꿔 재제출할 수 있다.
- A2. 검수자: 전역 권한 `reviewer`(sandbox) 또는 조직 역할 `reviewer`. 지금처럼 반려할 수 있다. 전역 권한은 그룹 중 admin > user > reviewer > worker 순서의 첫 번째 하나이므로, `user`와 `reviewer` 그룹을 함께 가진 계정은 `user`로 취급된다.
- A3. 관리자: 전역 권한 `admin`. 제약 없음.
- A4. 서버(OPA): 화면을 거치지 않은 요청(오래 열린 화면, API/SDK/CLI)도 거부한다.

## Key Decisions

- **막는 대상은 "다른 상태 → rejected"뿐.** 판단 기준은 요청된 새 값이 `rejected`인지다. 현재 값이 `rejected`인 job에서 다른 상태로 가는 전환은 기존 규칙 그대로다.
- **서버 판단은 `jobs.rego`의 `update:state` 규칙 안에서 한다.** 이를 위해 요청된 새 state를 OPA input에 실어야 한다. 현재는 어떤 permission 클래스도 요청 본문 값을 OPA로 넘기지 않으므로 이 fork에서 새로 여는 경로다. 형태(필드 이름·위치)는 planning이 정한다.
- **허용 계정 = 전역 `admin`, 전역 `reviewer`, 조직 역할 `reviewer`.** 그 외(전역 `user`·`worker`, 조직 owner/maintainer/supervisor/worker, task·project 소유자/담당자)는 job 담당자여도 불가. 티켓의 "reviewer, admin 외 불가"를 문자 그대로 적용했다 — **사용자 결정 2026-10-28로 대체: worker만 차단**(Q1 참고).
- **같은 값 no-op도 거부한다.** 작업자가 이미 `rejected`인 job에 `state=rejected`를 PATCH해도 403. 서버 규칙이 "요청 값이 rejected인가"만 보면 되어 단순하고, 화면은 해당 항목이 비활성이라 이 요청을 보내지 않는다. 일괄 변경은 이미 같은 상태인 job을 요청에서 빼므로(`onUpdateJobField`) 영향이 없다.
- **`state=rejected`가 다른 필드와 함께 오면 요청 전체를 거부한다.** 권한 검사는 업데이트 전에 scope별로 수행되므로 일부만 반영되는 일은 없다.
- **Task 상세 job 카드에도 같은 비활성 처리를 적용한다.** 티켓은 두 화면만 명시했지만 같은 `JobStateSelector` 컴포넌트를 공유하고, 목표가 "화면에서 막기"이므로 세 번째 진입점을 열어 둘 이유가 없다.

## Requirements

**서버 권한**

- R1. 허용 계정(A2, A3)이 아닌 사용자가 job state를 `rejected`로 바꾸는 요청은 403으로 거부되고 job state는 바뀌지 않는다.
- R2. 판단은 `jobs.rego`의 `update:state` 규칙에서 요청된 새 state 값으로 한다. 이를 위해 요청된 state가 OPA input에 포함된다.
- R3. 새 state가 `rejected`가 아닌 `update:state`는 현재 규칙 그대로 허용·거부된다(`rejected` → `in progress`/`completed`/`new` 포함).
- R4. 403 응답에는 `반려(rejected)는 작업자 계정으로 할 수 없습니다.` 메시지가 담겨, UI의 기존 오류 알림이 `Could not update job` / `Error: 반려(rejected)는 작업자 계정으로 할 수 없습니다.`로 표시된다. 현재 OPA의 거부 사유(`reasons`)는 `PolicyEnforcer`에서 버려져 DRF 기본 문구가 나가므로, 메시지를 응답까지 전달하는 경로가 필요하다.
- R5. 검수자·관리자의 기존 권한(stage/state/assignee 변경, 어노테이션 변경 금지)은 바뀌지 않는다.

**작업자 화면**

- R6. 어노테이션 화면 Menu > Change job state에서 `rejected` 항목은 보이되 비활성(회색)이며, 호버 시 툴팁 `반려(rejected)는 작업자 계정으로 할 수 없습니다`를 띄운다. 클릭해도 확인 창이 뜨지 않는다.
- R7. Jobs 목록 ⋮ > State 선택지와 Task 상세 job 카드의 State 선택지에서 `rejected`는 같은 방식(비활성+툴팁)으로 표시된다. 여러 job을 선택한 일괄 변경도 같다.
- R8. 이미 `rejected`인 job에서는 `rejected`가 현재 상태 표시(✓/선택값)로 보이지만 비활성이고, `new`/`in progress`/`completed`는 기존대로 선택할 수 있다.
- R9. 화면의 허용 판정은 서버와 같은 기준(A2, A3)을 따른다. 조직 역할 `reviewer`도 검수자로 본다.

**검수자 화면**

- R10. 검수자·관리자 화면은 변경 없다.

**테스트**

- R11. OPA 테스트가 다음을 검증한다: 작업자·job 담당자·task/project 소유자·조직 maintainer 등이 `rejected`로 바꾸려 하면 거부, 같은 사용자의 다른 state 값은 기존 결과 유지, 전역/조직 reviewer와 admin은 `rejected` 허용. 기존 `jobs_reviewer_test.rego`/`jobs_sandbox_reviewer_test.rego` 스타일의 수기 테스트로 두거나 생성기(`cvat/apps/engine/rules/tests/generators/jobs_test.gen.rego.py`, `configs/jobs.csv`)에 state 값 축을 추가한다 — planning이 고른다.

## Acceptance Examples

- AE1. 작업자가 담당 job(`in progress`)의 Change job state를 연다 → `rejected`가 회색, 호버 시 툴팁, 클릭해도 아무 일 없음. `completed` 클릭 → 기존 확인 창 → 변경됨.
- AE2. 작업자가 Jobs 목록에서 job 3개를 선택하고 ⋮ > State를 연다 → `rejected` 비활성+툴팁.
- AE3. 작업자가 반려 전 열어 둔 화면에서, 또는 API로 `PATCH /api/jobs/{id} {"state": "rejected"}` → 403, 알림 `Could not update job` / `Error: 반려(rejected)는 작업자 계정으로 할 수 없습니다.`, job state 그대로.
- AE4. 검수자가 반려한 job을 작업자가 연다 → `rejected`에 ✓, 비활성. `in progress` 선택 → 변경됨.
- AE5. 검수자(전역 또는 조직 reviewer)가 `completed` job을 `rejected`로 → 지금과 동일하게 성공.
- AE6. 작업자가 `PATCH {"state": "rejected", "assignee": ...}` → 403, assignee도 바뀌지 않음.

## Success Criteria

- 작업자 계정으로는 어떤 경로로도 job이 `rejected`가 되지 않는다.
- 검수자 워크플로는 화면·결과 모두 이전과 같다.
- 작업자는 오류 알림에서 왜 거부됐는지 한국어로 알 수 있다.

## Scope Boundaries

- `rejected` → 다른 상태 전환 제한은 하지 않는다.
- 작업자의 `completed` → `in progress` 되돌리기는 막지 않는다. `job_snapshots.py`의 `classify_job_transition`은 이것도 `REJECTED` 라운드 경계로 기록하지만(`_REOPENED_STATES`), 이 티켓 범위 밖이다.
- stage 변경, assignee 변경 권한은 건드리지 않는다.
- 이슈(Issue) resolve/reopen 권한은 건드리지 않는다.

## Dependencies / Interactions

- **INNO-123(알림):** `검수 반려` 알림은 state → `rejected`에서 발생한다. 이 변경 후에는 검수자·관리자만 이 알림을 유발한다. 거부된 403 요청은 상태를 바꾸지 않으므로 알림·스냅샷 모두 생기지 않아야 한다.
- **job round-boundary 스냅샷:** `completed` → `rejected`는 `REJECTED` 경계다. 거부된 요청은 전이가 커밋되지 않으므로 스냅샷 행도 생기지 않는다.
- **production_stats / Beacon `job_rounds`:** 반려 라운드가 검수자 행동만 반영하게 되어 지표 신뢰도가 오른다. 데이터 형태는 바뀌지 않는다.
- 로컬 DB에는 조직이 0개이고 전역 그룹(admin/user/reviewer/worker)만 쓰인다. 운영도 sandbox 위주일 것으로 보나 확인하지 않았다(가정).

## 미결정 사항 (사용자 확인 필요)

- **Q1. 전역 `user` 권한 계정과 조직 owner/maintainer의 반려 가능 여부** — 사용자 결정 2026-10-28: worker만 차단. 실효 privilege가 worker인 계정(sandbox: 전역 `worker`, 조직: role `worker`/무역할)만 반려 불가, 나머지(admin, `user`, `reviewer`, 조직 owner/maintainer/supervisor/reviewer)는 가능.
  - 권장: 티켓 문구대로 **불가**. 반려 권한이 필요한 사람은 `reviewer` 그룹(또는 조직 reviewer 역할)에 넣는다.
  - 대안: 전역 `user`(task/project를 만드는 관리자 계정)와 조직 owner/maintainer도 허용. 현재 이 계정들은 `update:state` 권한이 있어, 불가로 하면 이들의 반려 능력이 사라진다. 실제로 반려를 `user` 계정으로 하는 사람이 있다면 대안이 맞다.
- **Q2. 같은 값 no-op(`rejected` → `rejected`) PATCH** — 가정(사용자 확인 대기).
  - 권장: 작업자는 거부(403). 화면은 보내지 않으므로 사용자에게 보이지 않는다.
  - 대안: 현재 값과 같으면 허용. OPA에 현재 state도 넘겨야 해 규칙이 조금 복잡해진다.
- **Q3. Task 상세 job 카드 적용** — 가정(사용자 확인 대기).
  - 권장: 적용(R7). 같은 컴포넌트라 추가 비용이 거의 없다.
  - 대안: 티켓 명시 두 화면만. 서버가 막으므로 카드에서 고른 작업자는 403 알림을 보게 된다.

## Sources / Research

- `cvat/apps/engine/rules/jobs.rego` — `update:state` 허용 규칙(비검수자 4개: sandbox worker+`is_job_staff`, 조직 maintainer, 조직 worker+`is_job_staff`, 조직 무역할 worker 담당자 / 검수자 2개: 조직·sandbox reviewer), `utils.is_admin` 선행 허용.
- `cvat/apps/iam/rules/utils.rego`(`is_reviewer` = 전역 privilege), `cvat/apps/organizations/rules/organizations.rego`(`is_reviewer` = 조직 role; reviewer는 `get_priority` 밖).
- `cvat/apps/iam/middleware.py` — privilege는 소속 그룹 중 `IAM_ROLES` 순서(admin > user > reviewer > worker) 최상위 하나.
- `cvat/apps/engine/permissions.py` `JobPermission._get_scopes`/`get_resource`, `cvat/apps/iam/permissions.py` `get_per_field_update_scopes`, `PolicyEnforcer._check_permission`(reasons 미사용).
- `cvat-ui/src/components/annotation-page/top-bar/annotation-menu.tsx`(Change job state, 기존 `isReviewerOnly` 그룹 판정), `components/job-item/job-selectors.tsx`(`JobStateSelector`), `components/jobs-page/actions-menu.tsx`·`actions-menu-items.tsx`(일괄 `edit_state`), `actions/bulk-actions.ts`(첫 실패에서 중단·재시도), `reducers/notifications-reducer.ts`(`Could not update job`).
- `cvat/apps/engine/job_snapshots.py` `classify_job_transition`.
