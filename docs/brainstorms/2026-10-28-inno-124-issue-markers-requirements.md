---
date: 2026-10-28
topic: inno-124-issue-markers
---

# INNO-124 — ImageLab 안에서 이슈 위치 표시 (IssueMarkers + Issues 배지)

## Summary

annotation 페이지 상단 프레임 슬라이더에 **이슈가 있는 프레임마다 마커**를 그리고, 사이드바 Issues 탭 이름 옆에 **job 전체 `미해결/전체` 배지**를 단다. 마커를 클릭하면 그 프레임으로 이동하고 Issues 탭이 열린다. 기준은 항상 job 전체 이슈이며, 이슈 추가·해결·재오픈·삭제가 새로고침 없이 즉시 반영된다.

## Problem Frame

job 안에서 검수 이슈가 몇 개인지, 어느 이미지에 있는지 한눈에 알 수 없다.

- 슬라이더에는 이슈 표시가 없다.
- Issues 탭의 `Items: N`은 **현재 프레임** 이슈 수(`frameIssues.length`)만 보여준다.
- 이슈 프레임을 찾으려면 Issues 탭의 `<` `>` 버튼으로 하나씩 이동해야 한다.

작업자는 재작업할 위치를, 검수자는 남은 미해결 건을 파악하는 데 이 순회 비용을 매번 치른다.

## Key Decisions

시안과 Slack 결정은 사용자와 합의 완료된 사항이다. 아래는 그 위에 이 문서가 더한 해석·기본값이다.

- **데이터는 이미 클라이언트에 있다 — 신규 API 없음.** job 진입 시 `job.issues()`가 `fetchAll`로 job의 **모든** 이슈를 받아 `state.review.issues`에 넣는다(`frameIssues`는 그중 현재 프레임 필터). 마커·배지는 이 목록에서 파생하면 된다.
- **즉시 반영은 "내 클라이언트의 동작" 기준.** 추가(`FINISH_ISSUE_SUCCESS`)·삭제(`REMOVE_ISSUE_SUCCESS`)는 `issues` 배열을 갱신하고, 해결·재오픈(`RESOLVE/REOPEN_ISSUE_SUCCESS`)은 issue 객체를 in-place 변경한 뒤 배열을 새로 만든다. 따라서 `issues`에서 파생하면 네 동작 모두 즉시 반영된다. 다른 사용자가 동시에 만든 이슈의 실시간 동기화는 범위 밖이다(job 재진입 시 반영).
- **마커 대상은 Issue만.** `<` `>` 순회는 Review 모드에서 Ground truth 표시 시 quality conflict 프레임도 포함하지만, 마커·배지는 Issue(피드백)만 다룬다. 티켓의 "이슈(피드백) 수"와 일치시킨다.
- **`T R`은 기존 `issuesResolvedHidden` 플래그를 그대로 따른다.** 이 플래그는 이미 캔버스 이슈 표시와 `<` `>` 순회에 쓰이므로, 마커도 같은 플래그로 회색 마커를 숨겨 세 곳의 동작을 일치시킨다.
- **`T I`(모든 이슈 숨기기)는 마커 전체를 숨긴다 (사용자 결정 2026-10-28).** 이슈 표시 토글은 마커에도 일관되게 적용한다. 모든 이슈를 숨겼는데 마커가 남으면 사용자 의도와 어긋난다. 같은 플래그(`issuesHidden`)를 눈 아이콘과 `T I` 단축키가 공유한다.
- **배지는 어떤 토글에도 숨겨지지 않는다.** `T I`·`T R`과 무관하게 배지는 항상 job 전체 `미해결/전체`를 보여준다.
- **기존 슬라이더 오버레이 패턴을 따른다.** 슬라이더 위에는 이미 캐시 진행도 SVG(`cvat-player-slider-progress`)와 비디오 챕터 마크(antd `marks`)가 겹쳐 있다. 마커는 별도 레이어로 얹되 챕터 마크·진행도 표시와 시각적으로 충돌하지 않아야 한다.

## Requirements

**슬라이더 마커 (IssueMarkers)**

- R1. job에서 이슈가 1건 이상 있는 프레임마다 슬라이더 위에 마커 1개를 그린다. 한 프레임에 이슈가 여러 건이어도 마커는 1개다.
- R2. 인접한 프레임의 마커도 합치지 않는다.
- R3. 마커는 2×12px 동일 크기이며 정수 픽셀 위치에 맞춰 그린다.
- R4. 그 프레임에 미해결 이슈가 하나라도 있으면 빨강, 모두 해결이면 회색이다.
- R5. 현재 프레임 핸들은 항상 마커 위에 그려진다.

**호버·클릭**

- R6. 슬라이더 위에서 커서에 가장 가까운 마커로 스냅하고, 스냅된 마커는 4×16px 진한 색으로 커진다.
- R7. 스냅 범위는 마커 좌우 6px이며, 이웃 마커와 가까우면 두 마커 사이 중간 지점까지로 줄어든다.
- R8. 툴팁·미리보기는 없다.
- R9. 스냅된 마커를 클릭하면 그 프레임으로 이동하고 사이드바 Issues 탭이 활성화된다.
- R10. 스냅 범위 밖에서는 슬라이더 클릭·드래그가 기존과 동일하게 동작한다.

**Issues 탭 배지**

- R11. Issues 탭 이름 옆에 job 전체 `미해결/전체` 배지를 표시한다(예: `Issues 5/6`).
- R12. 미해결이 있으면 빨간 배지, 모두 해결이면 회색 배지(`0/6`), 이슈가 0건이면 배지를 숨긴다.
- R13. 세 자리(`100/114`)까지 탭이 잘리지 않도록 사이드바 탭 좌우 여백을 16px → 12px로 줄인다. Objects·Labels 탭에도 함께 적용된다.
- R14. 기존 `Items: N`(현재 프레임 이슈 수)은 그대로 유지한다.

**표시 규칙**

- R15. 마커와 배지는 job 전체 이슈를 기준으로 한다.
- R16. 이슈 추가·해결·재오픈·삭제 시 새로고침 없이 마커 색/유무와 배지 숫자가 즉시 갱신된다. INNO-127(단축키 삭제) 경로도 포함한다.
- R17. `T R`(해결된 이슈 숨기기)이 켜지면 회색 마커를 숨긴다. 배지 숫자는 계속 전체 기준으로 표시한다.
- R18. Standard/Review 모드, 작업자/검수자 모두 동일하게 동작한다.
- R19. 이 기능의 on/off 설정은 두지 않는다.
- R20. `T I`(모든 이슈 숨기기, 눈 아이콘)가 켜지면 모든 마커를 숨긴다. 배지는 계속 표시한다. (사용자 결정 2026-10-28)

## Acceptance Examples

- AE1 (R1, R4). 프레임 10에 미해결 1건 + 해결 1건 → 빨간 마커 1개. 미해결 건을 해결하면 즉시 회색으로 바뀐다.
- AE2 (R4, R16). 회색 마커 프레임의 이슈를 재오픈 → 즉시 빨강. 배지 `0/2` → `1/2`, 배지 색도 회색 → 빨강.
- AE3 (R16). 프레임의 유일한 이슈를 삭제(버튼 또는 INNO-127 단축키) → 마커가 사라지고 배지 전체 수가 1 줄어든다. 마지막 이슈였다면 배지가 사라진다.
- AE4 (R17). `T R` 켬 → 회색 마커만 사라지고 빨간 마커와 배지 `5/6`은 그대로. 이때 해결된 이슈만 있는 프레임은 스냅·클릭 대상에서도 빠진다.
- AE5 (R7). 마커 A·B가 8px 떨어져 있으면 각 스냅 범위는 서로를 향한 쪽으로 4px까지만이다. 다른 쪽은 6px 그대로다.
- AE6 (R9, R14). 마커 클릭으로 프레임 42로 이동 → Objects 탭을 보고 있었어도 Issues 탭이 열리고 `Items: N`은 프레임 42의 이슈 수를 보여준다.
- AE7 (R20). `T I` 켬 → 빨강·회색 마커가 모두 사라지고 스냅·클릭도 없다. 배지 `5/6`은 그대로. `T I`를 끄면 `T R` 상태에 맞게 마커가 돌아온다.

## Scope Boundaries

- 다른 사용자가 만든·해결한 이슈의 실시간 반영(polling/websocket)은 하지 않는다.
- quality conflict(GT 비교 결과)는 마커·배지에 포함하지 않는다.
- 마커 툴팁, 썸네일 미리보기, 근접 마커 클러스터링은 하지 않는다.
- 서버/API 변경은 없다. job 목록·task 페이지 등 annotation 페이지 밖의 이슈 수 표시는 범위 밖이다.

## Dependencies / Assumptions

- `job.issues()`가 job의 모든 이슈를 페이지네이션 없이 받아온다는 현재 동작(`serverProxy.issues.get` → `fetchAll`)에 의존한다. 이슈가 수백 건인 job에서도 진입 시 1회 로드로 충분하다고 가정한다.
- 사이드바 `Tabs`는 현재 비제어(`defaultActiveKey='objects'`)라, R9의 "Issues 탭 열기"는 탭 활성 상태를 외부에서 바꿀 수 있어야 한다. 방식은 planning에서 정한다.
- `T R` 플래그(`issuesResolvedHidden`)는 Redux 상태로만 존재하고 job을 닫으면 초기화된다. 마커도 이 수명을 따른다.

## 미결정 사항 (사용자 확인 필요)

남은 3건(1·3·4)은 모두 비차단(non-blocking)이다. planning은 각 항목의 **권장안을 가정(사용자 확인 대기)**으로 채택해 진행한다. 2번은 사용자가 결정했다.

1. **마커 클릭 시 사이드바가 접혀 있으면?**
   - 결정 [사용자 결정 2026-10-28]: 사이드바를 펼치고 Issues 탭을 연다. "클릭 → 이슈 목록이 열림"이라는 합의된 결과를 지킨다.
   - 대안: 프레임 이동만 하고 접힌 상태 유지(사용자가 의도적으로 접은 상태 존중).
2. ~~모든 이슈 숨기기 시 마커~~ → 해결됨: R20 (사용자 결정 2026-10-28, `T I` 켜면 마커 전체 숨김).
3. **Standard/Review 외 workspace(Attribute annotation, Single shape 등)에서의 동작은?** 슬라이더는 모든 workspace가 공유하지만 Issues 탭은 Standard/Review 사이드바에만 있다.
   - 권장 [가정(사용자 확인 대기)]: 마커는 모든 workspace에서 보이고 클릭 시 프레임 이동만 한다. Single shape처럼 슬라이더 조작이 비활성인 곳에서는 마커 클릭도 비활성.
   - 대안: Standard/Review에서만 마커를 표시.
4. **삭제된(deleted) 프레임에 이슈가 있으면?**
   - 권장 [가정(사용자 확인 대기)]: 마커를 그대로 표시한다. 이슈는 살아 있고 배지 숫자에도 포함되므로 위치도 보여야 한다.
   - 대안: 숨김 프레임 표시 설정을 따라 숨긴다.

## Outstanding Questions

**Deferred to Planning**

- 긴 job에서 여러 이슈 프레임이 같은 정수 픽셀에 떨어질 때의 스냅·클릭 대상 결정 규칙(예: 커서와 프레임 단위로 가장 가까운 것). R2 "합치지 않음"과 R3 "정수 픽셀"이 동시에 걸리는 경우다.
- Ground truth job처럼 `startFrame..stopFrame` 안에 job 소속이 아닌 프레임이 섞인 경우의 위치 계산. 기존 진행도 SVG와 같은 좌표계를 쓰면 된다는 가정이며 planning에서 확인한다.
- 빨강·회색·진한 색의 구체 토큰(기존 antd/CVAT 색 재사용).
- 마커 레이어와 기존 챕터 마크·진행도 SVG·슬라이더 플러그인 슬롯 간 z-order와 포인터 이벤트 처리.

## Sources

- `cvat-ui/src/reducers/review-reducer.ts` — `issues`/`frameIssues` 파생, 추가·해결·재오픈·삭제 시 갱신 경로.
- `cvat-ui/src/actions/annotation-actions.ts` (`job.issues()` 로드), `cvat-core/src/session-implementation.ts`, `cvat-core/src/server-proxy.ts` (`getIssues` → `fetchAll`).
- `cvat-ui/src/components/annotation-page/top-bar/player-navigation.tsx` — antd `Slider`, 챕터 `marks`, `cvat-player-slider-progress` SVG, `player.slider` 플러그인 슬롯.
- `cvat-ui/src/components/annotation-page/standard-workspace/objects-side-bar/issues-list.tsx` — `Items: N`, `<` `>` 순회, `T R`(`TOGGLE_RESOLVED_ISSUES_HIDDEN`).
- `cvat-ui/src/components/annotation-page/standard-workspace/objects-side-bar/objects-side-bar.tsx` — 비제어 `Tabs`(Objects/Labels/Issues).
- `cvat-ui/src/components/annotation-page/review/issues-aggregator.tsx` — 캔버스 이슈 표시의 `issuesResolvedHidden` 처리.
- 관련 티켓: INNO-127(이슈 단축키 삭제).
