# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CVAT (Computer Vision Annotation Tool) is an interactive video and image annotation tool for computer vision. This is the **Everex fork**, shipped to users as **ImageLab** (see _Everex Fork Customizations_ below), with 3D annotation support and serverless AI functions removed. It's a full-stack application with:
- **Backend**: Django REST API with PostgreSQL, Redis (inmem + ondisk), ClickHouse for analytics
- **Frontend**: React/Redux single-page application with TypeScript
- **Workers**: Background RQ workers for import, export, annotation, webhooks, quality reports, consensus, chunks, snapshots (fork-added), and utils (notifications + cleaning)
- **Infrastructure**: Docker Compose deployment with Traefik reverse proxy, OPA for authorization

### Removed Features (Everex Fork)
- 3D annotation support (`cvat-canvas3d` package removed, plus the canvas3d UI: models page, model-runner modal, tools-control)
- Serverless AI/ML functions (`lambda_manager` app removed from `INSTALLED_APPS`)
- Git dataset repository integration (`dataset_repo` app removed)
- Point cloud annotation formats

Do not reintroduce imports of these apps/packages; `cvat/settings/base.py` no longer lists them.

## Git Workflow

- **GitHub repo**: `everex-ai/mlops-imagelab` (renamed from `everex-ai/cvat-everex`). The `origin` remote may still use the old URL — `git push`/`pull` follow GitHub's redirect, but `gh pr create` fails against the old name; pass `-R everex-ai/mlops-imagelab` or update the remote URL.
- **Working branch**: `main` (Everex PRs target this branch). The GitHub default branch (`origin/HEAD`) is `develop`, inherited from upstream — always pass `--base main` explicitly when creating PRs.
- **Upstream**: `https://github.com/cvat-ai/cvat.git` (official CVAT repo)
- **Git hooks**: Lefthook runs `lint-staged` on pre-commit for `*.{js,jsx,ts,tsx}` files

## Build and Development Commands

### Docker-based Development (Recommended)
```bash
# Start full development stack
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d

# Rebuild and start (after code changes)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# Run on a local workstation at http://localhost:8081 — add the local override
# (untracked docker-compose.local.yml: re-points prod bind mounts to ~/cvat-everex-data,
# rewrites Traefik Host rules and CSRF origins for localhost, remaps the export
# worker debug port 9092 → 127.0.0.1:9192 to avoid collisions)
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.local.yml up -d

# Reflect uncommitted backend changes WITHOUT rebuilding the image — append the
# srcmount override (untracked docker-compose.srcmount.yml: bind-mounts ./cvat over
# /home/django/cvat in the API server AND every RQ worker, since hooks run on the
# server but capture jobs run on the workers). The UI is a separate image; a UI
# change still needs `--build` or the dev server.
docker compose -f docker-compose.yml -f docker-compose.dev.yml \
  -f docker-compose.local.yml -f docker-compose.srcmount.yml up -d
# Then apply any new migrations against the persistent db:
docker exec cvat_server_everex python manage.py migrate
```

The base compose bakes `cvat/` into the server image and bind-mounts only `cvat/settings/base.py`, so **backend edits are invisible to a running stack** unless you rebuild or use the srcmount override above.

`deploy.sh` is the **production-host** deploy script (runs `git pull`, sets `CVAT_VERSION=dev`, rebuilds the stack) — do not run it on a local machine.

**Important — the base `docker-compose.yml` is pinned for production deployment, not localhost.** Traefik routes by `Host` header (`imagelab.mora.center` / `192.168.1.101`) on port `8081` (→ container `8080`); plain `http://localhost:8081` will NOT reach the UI without the matching `Host` header. Traefik admin maps `8091` (→ `8090`) but its dashboard entrypoint is commented out. To reach the UI from a browser, use `docker-compose.local.yml` (above), send the right `Host` header, add a hosts-file entry, or run the UI dev server (`yarn start:cvat-ui` on `localhost:3000`). Production volumes bind-mount to `/mnt/ssd/cvat_latest/`.

### Container Naming Convention
All Everex containers (and Compose service keys) use the `_everex` suffix: `cvat_server_everex`, `cvat_ui_everex`, `cvat_db_everex`, `cvat_redis_inmem_everex`, `cvat_redis_ondisk_everex`, etc. Use these exact names with `docker exec`/`docker logs` and as the service name for `docker compose run`. The Compose project name is `cvat-everex`, so the actual Docker network is `cvat-everex_cvat_everex` (verify with `docker network ls`) — use that for `docker network` / `--network` commands. The server image is `cvat/server:${CVAT_VERSION:-v2.52.0}` (there is no `:dev` tag — the dev override rebuilds this same tag).

### Frontend Development
```bash
# Install dependencies (uses yarn workspaces, requires Yarn 4.9.2 via corepack)
corepack enable yarn
yarn --immutable

# Build all frontend packages (order matters due to dependencies)
yarn build:cvat-data
yarn build:cvat-core
yarn build:cvat-canvas
yarn build:cvat-ui

# Start UI dev server (runs on localhost:3000, connects to API at localhost:7000)
yarn start:cvat-ui

# Custom host/port for UI dev server
CVAT_UI_HOST=0.0.0.0 CVAT_UI_PORT=3001 yarn start:cvat-ui

# Type checking
yarn workspace cvat-ui run type-check
yarn workspace cvat-core run type-check

# Lint frontend
yarn run eslint .
```

### Backend Commands (run against the running stack)
Use the `_everex` service/container names — bare `cvat_server` does not exist in this fork.
```bash
# Run Django tests (one-off container)
docker compose -f docker-compose.yml -f docker-compose.dev.yml run --rm cvat_server_everex python manage.py test cvat/apps

# Make/check migrations (against the running container)
docker exec cvat_server_everex python manage.py makemigrations --check
docker exec cvat_server_everex python manage.py migrate

# Generate API schema
docker exec cvat_server_everex python manage.py spectacular > cvat/schema.yml

# Create superuser
docker exec -it cvat_server_everex python manage.py createsuperuser
```

#### Running Django tests against uncommitted source
The one-off `run` above uses the code baked into the image. To test **live local source** without a rebuild:
```bash
# 1. Bring up the backend dependencies — OPA and the server included
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.local.yml \
  up -d cvat_db_everex cvat_redis_inmem_everex cvat_redis_ondisk_everex \
        cvat_opa_everex cvat_server_everex

# 2. One-off container, repo source mounted over the image's code, deps skipped
docker compose -f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.local.yml \
  run --rm --no-deps -v $(pwd)/cvat:/home/django/cvat --entrypoint python \
  cvat_server_everex manage.py test cvat.apps.engine.tests.test_issue_snapshots_hooks --keepdb
```
Notes:
- Code lives at `/home/django/cvat/`, `manage.py` at `/home/django/manage.py`. The image has a custom entrypoint, so override it with `--entrypoint python`.
- **`cvat_opa_everex` and `cvat_server_everex` have to be up too**, even though the one-off container runs with `--no-deps`. OPA pulls its policy bundle from the *running* server (`--set=bundles.cvat.resource=/api/auth/rules`, `docker-compose.yml`), so with the server down the bundle is empty, every permission check returns `{}`, and the whole suite dies on `KeyError: 'result'` rather than on anything in your change. Give OPA ~15s after the server comes up (its polling window is 5-15s).
- Tests run under the container's default **production** settings against PostgreSQL (`manage.py test` creates a separate `test_cvat` db, so the dev db is safe). `--keepdb` speeds re-runs.
- `cvat.settings.testing` (sqlite + fakeredis) **will not load in the server image** — it inherits `development.py`, which requires `django_extensions`, a dev-only dependency not installed there. RQ enqueues therefore hit real Redis; tests needing synchronous RQ must stub `django_rq.get_queue` themselves.
- Expect benign noise in the output: `logstash_async`/`vector` connection tracebacks (analytics logging to an absent host) and deliberate isolation-test tracebacks.

### SDK Generation
```bash
pip3 install -r cvat-sdk/gen/requirements.txt
./cvat-sdk/gen/generate.sh
```

## Testing

### Python Tests (REST API, SDK, CLI)
```bash
# Install test dependencies
pip install -r tests/python/requirements.txt -e './cvat-sdk[masks,pytorch]' -e ./cvat-cli

# Run all Python tests
pytest tests/python/

# Run specific test file
pytest tests/python/rest_api/test_tasks.py

# Run tests matching pattern
pytest tests/python/ -k "test_task_data"

# With coverage
pytest tests/python/ --cov --cov-report=json
```

### E2E Tests (Cypress)
```bash
cd tests
yarn --immutable

# Run Cypress tests
npx cypress run --browser chrome --spec 'cypress/e2e/actions_tasks/**/*.js'
```

### OPA Authorization Tests
```bash
python cvat/apps/iam/rules/tests/generate_tests.py
docker compose run --rm cvat_opa_everex test cvat/apps/*/rules
```

## Linting

### Python
```bash
# Black formatter
black --check --diff .

# isort
isort --check --diff --resolve-all-configs .

# Pylint
pylint -j0 .

# Bandit security scanner
bandit -a file --ini .bandit --recursive .

# Typos spell checker
typos
```

### JavaScript/TypeScript
```bash
yarn run eslint .
yarn run stylelint '**/*.css' '**/*.scss'
npx remark --quiet --frail -i .remarkignore .
```

## Architecture

### Frontend Package Structure (Yarn Workspaces)
- `cvat-data/` - Data parsing utilities (video frames, image archives)
- `cvat-core/` - API client library, business logic, models
- `cvat-canvas/` - 2D annotation canvas (SVG-based, uses svg.js)
- `cvat-ui/` - React application with Redux state management

Dependencies flow: `cvat-data` <- `cvat-core` <- `cvat-canvas` <- `cvat-ui`

### UI State Management
Redux store slices (in `cvat-ui/src/reducers/`): auth, projects, tasks, jobs, about, formats, plugins, notifications, annotation, settings, shortcuts, userAgreements, review, export, import, consensus, cloudStorages, organizations, webhooks, invitations, requests, serverAPI, navigation, bulkActions. Uses Redux Thunk middleware.

### UI Plugin System
The cvat-ui includes `plugins/sam` by default. Additional plugins via the `CLIENT_PLUGINS` environment variable (colon-separated paths). Plugins must export from `src/ts/index.tsx`.
```bash
CLIENT_PLUGINS=/path/to/plugin1:/path/to/plugin2 yarn start:cvat-ui
```

### Browser Support
Chrome >= 99, Firefox >= 110, >2% market share (no IE11)

### Backend Django Apps (`cvat/apps/`)
- `engine/` - Core models (Task, Job, Label, Shape), views, task creation, data handling
- `iam/` - Identity/access management, OPA authorization rules
- `organizations/` - Multi-tenant organization support
- `dataset_manager/` - Import/export in various annotation formats (COCO, YOLO, Pascal VOC, etc.)
- `quality_control/` - Annotation quality reports and ground truth management
- `consensus/` - Multi-annotator consensus merging
- `webhooks/` - External webhook integrations
- `events/` - Analytics events (stored in ClickHouse)
- `redis_handler/` - Redis data caching and storage utilities
- `access_tokens/` - Personal access token management
- `health/` - Health check endpoints
- `log_viewer/` - Log viewing utilities
- `production_stats/` - (fork-added) admin-only read API for Beacon — see _Everex Fork Customizations_

### Key Backend Patterns
- Authorization via OPA (Open Policy Agent) with Rego rules in `cvat/apps/*/rules/`
- Background jobs via django-rq with specialized workers (import, export, annotation, etc.)
- Two Redis instances: inmem (cache/queue) and ondisk (kvrocks for persistent data)
- File uploads via TUS protocol for resumable uploads
- Server runs nginx + uvicorn (ASGI) via supervisord (`supervisord/server.conf`), workers run RQ via supervisord (`supervisord/worker.conf`) with custom worker class `cvat.rqworker.DefaultWorker`

### Everex Fork Customizations
These are the divergences from upstream CVAT that span many files — read the linked entry points before touching the surrounding code, and expect merge conflicts here when pulling from upstream.

**ImageLab branding.** The product is presented as _ImageLab_: `cvat/apps/engine/static/logo.svg` (server-served; rendered by both the header and the sign-in page), `cvat-ui/src/assets/favicon.png` (wired via the HtmlWebpackPlugin `favicon` option in `cvat-ui/webpack.config.js`), and the title/meta in `cvat-ui/src/index.html`. Production hostname is `imagelab.mora.center`.

**`reviewer` IAM role.** A fork-added role — `IAM_ROLES = [admin, user, reviewer, worker]` in `cvat/settings/base.py`, with `utils.is_reviewer` / `organizations.is_reviewer` used across `cvat/apps/*/rules/*.rego` (jobs, comments, issues, annotation guides, users). On the UI side, a _reviewer-only_ user (in group `reviewer` but not `admin`) skips `saveAnnotationsAsync()` when finishing a job — see `isReviewerOnly` in `cvat-ui/src/actions/annotation-actions.ts`. Changes to reviewer permissions need matching `*_test.rego` cases (e.g. `cvat/apps/engine/rules/jobs_reviewer_test.rego`).

**Skeleton bounding box as a first-class field.** Skeletons persist an annotator-drawn axis-aligned `bbox = [xtl, ytl, xbr, ybr]` instead of deriving it from keypoints. It is a `FloatArrayField` on the shape model (`cvat/apps/engine/models.py`), validated in `cvat/apps/engine/serializers.py` (valid values: `[]` = never drawn, `[0,0,0,0]`, or a strictly ordered 4-tuple), backfilled by migration `0098_add_skeleton_bbox`, round-tripped through `dataset_manager/bindings.py` and the CVAT XML / COCO Keypoints formats, (de)serialized in `cvat-core` (`annotations-objects.ts`, `object-state.ts`, `annotations-collection.ts`), and read by `cvat-canvas` (`canvasView.ts`, `drawHandler.ts`). Rotation is _baked into keypoints_ while the bbox stays axis-aligned; corner handles resize the bbox only. Full decision record: `docs/plans/2026-05-19-001-feat-skeleton-bbox-persistence-plan.md`.

**Issue annotation snapshots.** `cvat/apps/engine/issue_snapshots.py` + the `IssueAnnotationSnapshot` model (migrations `0099`, `0100`) capture a densified per-frame annotation snapshot of the _problematic_ state when a reviewer raises or reopens an Issue — that state is ephemeral, while the corrected state is durable and read live at export. Densification reuses the `dataset_manager` read path (`JobAnnotation` → `JobData.group_by_frame`) with `use_server_track_ids=True`; `Issue.frame` is task-relative and must not go through `rel_frame_id`. `mask` shapes are excluded. Capture is enqueued to the **utils worker**, so testing it end-to-end requires the srcmount override on workers too. Tests: `cvat/apps/engine/tests/test_issue_snapshots_*.py`.

**Job round-boundary snapshots.** `cvat/apps/engine/job_snapshots.py` freezes a job's whole densified geometry (`JobAnnotationSnapshot` + per-frame `JobAnnotationSnapshotFrame`, migrations `0101`, `0103`) at each round boundary — submit (state → `completed`), reject/reopen, and accept (stage → `acceptance`); other stage moves are deliberately not boundaries (`classify_job_transition`). The row is written with a `JobSnapshotStatus` when the transition commits, then the capture runs async on its own **`snapshots` queue** (`cvat_worker_snapshots_everex`), kept off `notifications` so whole-job captures don't delay issue captures. Capture is best-effort and must never fail the transition. It reuses `load_job_data`/`serialize_frame` from `issue_snapshots.py`. Separately, `IssueResolutionChange` (migration `0102`) records every resolve/reopen synchronously in `IssueViewSet.perform_update`, because `Issue` keeps only the current flag.

**`production_stats` app (Beacon read API).** Admin-only endpoints under `/api/production_stats/` (`urls.py`: `job_facts`, `job_rounds`, `object_counts`, `issue_facts`, `user_day_activity`, plus the job-viewer endpoints `job_snapshots`, `job_issues`, `job_outline`, `job_frames` in `job_history.py`) consumed by the external Beacon dashboard. Key constraints:
- **Excluded from the OpenAPI schema** (`extend_schema(exclude=True)`) — CI diffs a regenerated `cvat/schema.yml` against the checked-in copy, and these aren't for generated clients.
- Authorization is the `ProductionStatsPermission` OPA class; the package name `production_stats` must match the `.rego` filename under `rules/` and the URL segment.
- ClickHouse access goes only through `queries/clickhouse.py` (per-call client, timeouts sized to fit a dedicated nginx `location /api/production_stats/` block in `cvat/nginx.conf` and Beacon's 90s cutoff); the other `queries/*` builders are pure functions. Lists use `SingleResponsePagination` (one page) because each request re-runs a full ClickHouse aggregation.
- Dates are emitted as **KST calendar days**; ClickHouse timestamps are normalized to tz-aware UTC (`_as_utc`) before serialization. Freshness logic is ported from `docs/analytics/annotation-time-metrics.sql` (also backs the Grafana `annotation_time.json` dashboard).
- Tests in `cvat/apps/production_stats/tests/` mock ClickHouse wherever it is touched, so they run with the live-source procedure above without a ClickHouse instance.

**Auth events.** `cvat/apps/events/signals.py` emits `login:user` / `logout:user` events (skipping anonymous logouts), which feed per-user activity stats.

**COCO Keypoints job metadata.** Export attaches per-image job metadata; the conflict-resolution and stem-joining logic is isolated in `cvat/apps/dataset_manager/formats/_coco_job_meta.py` (unit-tested separately) and applied from `formats/coco.py` as a post-processor — the extractor is untouched, so other formats are unaffected.

### Migrations
Fork-local migrations start at `cvat/apps/engine/migrations/0097_drop_legacy_analytics_report.py` and continue through `0098`–`0103`. Upstream numbers from the same range will collide on a merge; renumber the incoming upstream migration rather than the fork's, since the fork's are already applied on the production DB.

### Planning Docs
Feature work in this fork is recorded under `docs/brainstorms/` (requirements, `YYYY-MM-DD-<slug>-requirements.md`) and `docs/plans/` (`YYYY-MM-DD-NNN-<slug>-plan.md`). Check for an existing plan before starting work on skeleton bbox or issue-snapshot code — they carry key decisions and cross-review findings not visible in the diff.

### Settings
- `cvat/settings/base.py` - Base Django settings
- `cvat/settings/development.py` - Development overrides
- `cvat/settings/production.py` - Production settings
- `cvat/settings/testing.py` - Test settings

## Code Style

### Python
- Black formatter with 100 char line length
- isort for import sorting (profile: black)
- Target Python 3.10+
- **`pyproject.toml` excludes several core files from Black** (`dataset_manager/bindings.py` and `engine/{mixins,models,permissions,serializers,task,views}.py`). Do not reformat them — match the surrounding style by hand, or a `black .` run will produce a huge unrelated diff.

### TypeScript/JavaScript
- ESLint with Airbnb config
- 4-space indentation
- 120 char max line length
- Single quotes

## Debug Ports (docker-compose.dev.yml)
- Server: 9090
- Worker annotation: 9091
- Worker export: 9092
- Worker import: 9093
- Worker quality_reports: 9094
- Worker consensus: 9096

Set `CVAT_DEBUG_ENABLED=yes` environment variable to enable debugging.

## RQ Workers
This fork uses workers with `_everex` suffix:
- `cvat_worker_utils_everex` - Notifications/cleaning (incl. issue snapshot capture)
- `cvat_worker_snapshots_everex` - Job round-boundary snapshot capture (`snapshots` queue)
- `cvat_worker_import_everex` - Data import
- `cvat_worker_export_everex` - Data export
- `cvat_worker_annotation_everex` - Annotation processing
- `cvat_worker_webhooks_everex` - Webhook delivery
- `cvat_worker_quality_reports_everex` - Quality report generation
- `cvat_worker_chunks_everex` - Chunk processing
- `cvat_worker_consensus_everex` - Consensus merging

## Local Development without Docker

VS Code launch configurations are provided in `.vscode/launch.json`:
- `server: django` - Run Django dev server on localhost:7000
- `server: RQ - *` - Individual RQ worker configurations (import, export, annotation, webhooks, quality reports, cleaning, chunks, consensus)
- `server: debug` - Compound configuration to run all services together
- `server: REST API tests` / `sdk: tests` / `cli: tests` - Test runners

Prerequisites for local development: PostgreSQL, Redis instances must be accessible (can use Docker Compose services with exposed ports from `docker-compose.dev.yml`).

## Package-Specific Documentation

Each frontend package and SDK has its own CLAUDE.md with detailed architecture:
- `cvat-data/CLAUDE.md` - Video/image decoding with H.264 (Broadway.js) and zip archives
- `cvat-core/CLAUDE.md` - API client library, plugin system, session management
- `cvat-canvas/CLAUDE.md` - 2D SVG-based annotation canvas (MVC pattern, handler classes)
- `cvat-sdk/CLAUDE.md` - Python SDK with auto-generated OpenAPI client
- `cvat-cli/CLAUDE.md` - CLI tool command structure and authentication
