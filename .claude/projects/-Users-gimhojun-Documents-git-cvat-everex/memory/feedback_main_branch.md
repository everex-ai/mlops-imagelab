---
name: Main branch is main, not develop
description: User wants PRs to target main branch, not develop. CLAUDE.md was updated accordingly.
type: feedback
---

PR을 만들 때 base 브랜치는 `main`을 사용해야 한다. `develop`이 아님.

**Why:** 사용자가 "메인에 머지해"라고 했을 때 `develop`으로 보내서 수정해야 했음.

**How to apply:** PR 생성 시 `--base main`을 사용. CLAUDE.md에도 반영 완료.
