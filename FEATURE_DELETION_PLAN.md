# CVAT-Everex 선택적 기능 삭제 계획

이 문서는 CVAT-Everex 코드베이스에서 필수가 아닌 기능들을 점진적으로 삭제하기 위한 상세 계획입니다.

---

## 목차

1. [개요](#1-개요)
2. [의존성 분석](#2-의존성-분석)
3. [삭제 순서](#3-삭제-순서)
4. [Phase별 상세 작업](#4-phase별-상세-작업)
5. [추가 삭제 가능 항목](#5-추가-삭제-가능-항목)
6. [작업 체크리스트](#6-작업-체크리스트)

---

## 1. 개요

### 1.1 삭제 대상 기능 목록

| 구분 | 앱/기능 | 설명 | 관련 워커 |
|------|---------|------|-----------|
| Django 앱 | dataset_repo | Git 동기화 (레거시) | - |
| Django 앱 | log_viewer | Grafana 로그 시각화 | - |
| Django 앱 | access_tokens | 개인 API 액세스 토큰 | - |
| Django 앱 | webhooks | 외부 이벤트 알림 | cvat_worker_webhooks |
| Django 앱 | lambda_manager | 서버리스 함수 관리 | cvat_worker_annotation |
| Django 앱 | consensus | 다중 어노테이터 합의 병합 | cvat_worker_consensus |
| Django 앱 | quality_control | 어노테이션 품질 평가 | cvat_worker_quality_reports |

### 1.2 삭제 위험도

| Phase | 대상 | 위험도 | 비고 |
|-------|------|--------|------|
| 1 | dataset_repo | 🟢 최소 | 마이그레이션만 존재, 기능 없음 |
| 2 | log_viewer | 🟢 최소 | 조건부 로딩 앱, 단독 |
| 3 | access_tokens | 🟡 중간 | 인증 시스템 연결 |
| 4 | webhooks | 🟡 중간 | 외부 연동 기능 |
| 5 | lambda_manager | 🟠 높음 | AI 자동 어노테이션 전체 |
| 6 | consensus | 🟠 높음 | 다중 어노테이터 기능 |
| 7 | quality_control | 🔴 최고 | 품질 관리 시스템 전체 |

---

## 2. 의존성 분석

### 2.1 Optional → Optional 의존성

```
consensus ──────────────▶ quality_control (하드 의존성)
                          - ComparisonParameters 사용
                          - JobDataProvider 사용
                          - DatasetComparator 사용
```

**⚠️ 중요**: consensus는 quality_control에 하드 의존성이 있으므로, quality_control을 삭제하려면 반드시 consensus를 먼저 삭제해야 합니다.

### 2.2 Core → Optional 역참조

Core 앱에서 Optional 앱을 import하는 부분으로, 삭제 시 수정이 필요합니다.

| Core 앱 | 파일 | 참조하는 Optional 앱 |
|---------|------|---------------------|
| engine | serializers.py | webhooks (Webhook 모델) |
| events | handlers.py | access_tokens, webhooks, lambda_manager |
| events | signals.py | access_tokens, webhooks, lambda_manager |
| iam | urls.py | access_tokens |
| redis_handler | - | lambda_manager (LambdaRQMeta) |

### 2.3 RQ 큐 설정 의존성

`cvat/settings/base.py`에서 삭제해야 할 큐 설정:

| 큐 이름 | 관련 앱 | 특수 설정 |
|---------|---------|-----------|
| webhooks | webhooks | - |
| quality_reports | quality_control | PARSED_JOB_ID_CLASS |
| consensus | consensus | PARSED_JOB_ID_CLASS |

### 2.4 의존성 그래프

```
┌─────────────────────────────────────────────────────────────────┐
│                    OPTIONAL APPS 의존성 구조                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  독립적 (단독 삭제 가능)                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐          │
│  │ dataset_repo │  │  log_viewer  │  │access_tokens │          │
│  │   (레거시)    │  │  (조건부)    │  │   (인증)     │          │
│  └──────────────┘  └──────────────┘  └──────────────┘          │
│                                                                 │
│  ┌──────────────┐  ┌──────────────┐                            │
│  │   webhooks   │  │lambda_manager│                            │
│  │  (외부 알림)  │  │   (AI/ML)    │                            │
│  └──────────────┘  └──────────────┘                            │
│                                                                 │
│  순서 의존적 (consensus → quality_control 순서로 삭제)            │
│  ┌──────────────┐      ┌─────────────────┐                     │
│  │  consensus   │ ───▶ │ quality_control │                     │
│  │  (합의 병합)  │      │   (품질 평가)    │                     │
│  └──────────────┘      └─────────────────┘                     │
│       먼저 삭제              나중 삭제                            │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 삭제 순서

### 3.1 권장 삭제 순서

```
Phase 1: dataset_repo     ─▶ 즉시 삭제 가능 (레거시, 기능 없음)
    │
    ▼
Phase 2: log_viewer       ─▶ 조건부 로딩 앱 (CVAT_ANALYTICS)
    │
    ▼
Phase 3: access_tokens    ─▶ API 토큰 관리 기능
    │
    ▼
Phase 4: webhooks         ─▶ 외부 알림 + cvat_worker_webhooks
    │
    ▼
Phase 5: lambda_manager   ─▶ AI 자동 어노테이션 + cvat_worker_annotation
    │
    ▼
Phase 6: consensus        ─▶ 합의 병합 + cvat_worker_consensus (먼저!)
    │
    ▼
Phase 7: quality_control  ─▶ 품질 평가 + cvat_worker_quality_reports (마지막!)
```

### 3.2 순서 변경 가능 여부

| Phase | 독립 실행 | 선행 조건 |
|-------|----------|-----------|
| 1 (dataset_repo) | ✅ 가능 | 없음 |
| 2 (log_viewer) | ✅ 가능 | 없음 |
| 3 (access_tokens) | ✅ 가능 | 없음 |
| 4 (webhooks) | ✅ 가능 | 없음 |
| 5 (lambda_manager) | ✅ 가능 | 없음 |
| 6 (consensus) | ⚠️ 조건부 | Phase 7 이전에 실행 필수 |
| 7 (quality_control) | ⚠️ 조건부 | Phase 6 완료 필수 |

Phase 1~5는 순서에 관계없이 독립적으로 실행 가능합니다.
Phase 6과 7은 반드시 6 → 7 순서로 진행해야 합니다.

---

## 4. Phase별 상세 작업

### Phase 1: dataset_repo 삭제

**현재 상태**: 레거시 앱, models.py 비어있음, 마이그레이션만 존재

#### 백엔드 수정

| 파일 | 작업 |
|------|------|
| `cvat/settings/base.py` | INSTALLED_APPS에서 `"cvat.apps.dataset_repo"` 제거 |
| `cvat/apps/dataset_repo/` | 디렉토리 전체 삭제 |

#### 데이터베이스

- 잔여 테이블 없음 (이미 삭제 마이그레이션 완료됨)

#### 프론트엔드

- 수정 없음

---

### Phase 2: log_viewer 삭제

**현재 상태**: CVAT_ANALYTICS=True일 때만 로딩되는 조건부 앱

#### 백엔드 수정

| 파일 | 라인 | 작업 |
|------|------|------|
| `cvat/settings/base.py` | 180-183 | 조건부 INSTALLED_APPS 추가 로직 제거 |
| `cvat/urls.py` | - | log_viewer URL 패턴 제거 (있는 경우) |
| `cvat/apps/log_viewer/` | - | 디렉토리 전체 삭제 |

#### 삭제할 코드 (settings/base.py)

```python
# 삭제 대상
ANALYTICS_ENABLED = to_bool(os.getenv("CVAT_ANALYTICS", False))

if ANALYTICS_ENABLED:
    INSTALLED_APPS += ["cvat.apps.log_viewer"]
```

#### 프론트엔드

- Analytics 관련 UI 검토 필요 (있는 경우)

---

### Phase 3: access_tokens 삭제

**현재 상태**: API 토큰 관리, 인증 시스템과 연결

#### 백엔드 수정

| 파일 | 작업 |
|------|------|
| `cvat/settings/base.py` | INSTALLED_APPS에서 `"cvat.apps.access_tokens"` 제거 |
| `cvat/settings/base.py` | REST_FRAMEWORK.DEFAULT_AUTHENTICATION_CLASSES에서 관련 클래스 제거 |
| `cvat/apps/iam/urls.py` | access_tokens URL 패턴 import 및 include 제거 |
| `cvat/apps/events/handlers.py` | access_tokens 관련 이벤트 핸들러 제거 |
| `cvat/apps/events/signals.py` | access_tokens 관련 시그널 제거 |
| `cvat/apps/access_tokens/` | 디렉토리 전체 삭제 |

#### 프론트엔드 수정

| 파일/디렉토리 | 작업 |
|--------------|------|
| `cvat-core/src/api-token.ts` | ApiToken 클래스 삭제 |
| `cvat-core/src/api-implementation.ts` | 토큰 관련 메서드 제거 |
| `cvat-ui/src/reducers/auth-reducer.ts` | apiTokens 상태 제거 |
| 프로필/설정 페이지 | 토큰 관리 UI 제거 |

#### 데이터베이스 마이그레이션

```bash
# 마이그레이션 생성 (access_token 테이블 삭제)
python manage.py makemigrations access_tokens --empty --name delete_all_tables
# 또는 앱 삭제 후 수동으로 테이블 삭제
```

---

### Phase 4: webhooks 삭제

**현재 상태**: 외부 이벤트 알림, cvat_worker_webhooks 워커 포함

#### 백엔드 수정

| 파일 | 작업 |
|------|------|
| `cvat/settings/base.py` | INSTALLED_APPS에서 `"cvat.apps.webhooks"` 제거 |
| `cvat/settings/base.py` | RQ_QUEUES에서 `"webhooks"` 큐 설정 제거 |
| `cvat/apps/engine/serializers.py` | Webhook import 및 관련 직렬화 코드 제거 |
| `cvat/apps/events/handlers.py` | webhooks 관련 핸들러 제거 |
| `cvat/apps/events/signals.py` | webhooks 관련 시그널 제거 |
| `cvat/urls.py` | webhooks URL 패턴 제거 |
| `cvat/apps/webhooks/` | 디렉토리 전체 삭제 |

#### Docker Compose 수정

| 파일 | 작업 |
|------|------|
| `docker-compose.yml` | `cvat_worker_webhooks` 서비스 전체 제거 |
| `docker-compose.dev.yml` | `cvat_worker_webhooks` 서비스 전체 제거 |

#### 프론트엔드 수정

| 파일/디렉토리 | 작업 |
|--------------|------|
| `cvat-core/src/webhook.ts` | Webhook, WebhookDelivery 클래스 삭제 |
| `cvat-core/src/api-implementation.ts` | webhooks 관련 메서드 제거 |
| `cvat-ui/src/components/webhooks-page/` | 디렉토리 전체 삭제 |
| `cvat-ui/src/components/setup-webhook-pages/` | 디렉토리 전체 삭제 |
| `cvat-ui/src/actions/webhooks-actions.ts` | 파일 삭제 |
| `cvat-ui/src/reducers/webhooks-reducer.ts` | 파일 삭제 |
| `cvat-ui/src/reducers/index.ts` | webhooks reducer import 제거 |
| `cvat-ui/src/components/cvat-app.tsx` | webhooks 라우트 정의 제거 |

#### 삭제할 라우트

- `/organization/webhooks`
- `/projects/:id/webhooks`
- `/webhooks/create`
- `/webhooks/update/:id`

#### 데이터베이스 마이그레이션

- Webhook 테이블 삭제
- WebhookDelivery 테이블 삭제

---

### Phase 5: lambda_manager 삭제

**현재 상태**: 서버리스 AI 함수 관리, 자동 어노테이션 기능

**⚠️ 주의**: 이 Phase 완료 후 AI 자동 어노테이션 기능이 완전히 비활성화됩니다.

#### 백엔드 수정

| 파일 | 작업 |
|------|------|
| `cvat/settings/base.py` | INSTALLED_APPS에서 `"cvat.apps.lambda_manager"` 제거 |
| `cvat/settings/base.py` | RQ_QUEUES의 annotation 큐 설정 검토/수정 |
| `cvat/apps/redis_handler/` | LambdaRQMeta 참조 제거 |
| `cvat/apps/events/handlers.py` | lambda 관련 핸들러 제거 |
| `cvat/apps/events/signals.py` | lambda 관련 시그널 제거 |
| `cvat/urls.py` | lambda URL 패턴 제거 |
| `cvat/apps/lambda_manager/` | 디렉토리 전체 삭제 |

#### Docker Compose 수정

| 파일 | 작업 |
|------|------|
| `docker-compose.yml` | `cvat_worker_annotation` 서비스 제거 또는 수정 |
| `docker-compose.dev.yml` | `cvat_worker_annotation` 서비스 제거 또는 수정 |
| `components/serverless/` | Nuclio 관련 설정 제거 (선택) |

#### 프론트엔드 수정

| 파일/디렉토리 | 작업 |
|--------------|------|
| `cvat-core/src/lambda-manager.ts` | LambdaManager 클래스 삭제 |
| `cvat-core/src/ml-model.ts` | MLModel 클래스 삭제 |
| `cvat-core/src/api-implementation.ts` | lambda 관련 메서드 제거 |
| `cvat-ui/src/components/models-page/` | 디렉토리 전체 삭제 |
| `cvat-ui/src/components/model-runner-modal/` | 디렉토리 전체 삭제 |
| `cvat-ui/src/actions/models-actions.ts` | 파일 삭제 |
| `cvat-ui/src/reducers/models-reducer.ts` | 파일 삭제 |
| `cvat-ui/src/reducers/index.ts` | models reducer import 제거 |
| `cvat-ui/src/components/annotation-page/` | AI 도구 관련 컴포넌트 수정/제거 |
| `cvat-ui/src/components/cvat-app.tsx` | models 라우트 정의 제거 |

#### CLI 수정

| 파일 | 작업 |
|------|------|
| `cvat-cli/src/cvat_cli/cli.py` | `function` 명령어 그룹 제거 |
| `cvat-cli/_internal/agent.py` | 파일 삭제 |

#### 삭제할 라우트

- `/models`

---

### Phase 6: consensus 삭제

**현재 상태**: 다중 어노테이터 합의 병합 기능

**⚠️ 중요**: 이 Phase는 반드시 Phase 7 (quality_control) 이전에 실행해야 합니다.

#### 백엔드 수정

| 파일 | 작업 |
|------|------|
| `cvat/settings/base.py` | INSTALLED_APPS에서 `"cvat.apps.consensus"` 제거 |
| `cvat/settings/base.py` | RQ_QUEUES에서 `"consensus"` 큐 설정 제거 |
| `cvat/settings/base.py` | consensus 큐의 `PARSED_JOB_ID_CLASS` 설정 제거 |
| `cvat/urls.py` | consensus URL 패턴 제거 |
| `cvat/apps/consensus/` | 디렉토리 전체 삭제 |

#### Docker Compose 수정

| 파일 | 작업 |
|------|------|
| `docker-compose.yml` | `cvat_worker_consensus` 서비스 전체 제거 |
| `docker-compose.dev.yml` | `cvat_worker_consensus` 서비스 전체 제거 |

#### 프론트엔드 수정

| 파일/디렉토리 | 작업 |
|--------------|------|
| `cvat-core/src/consensus-settings.ts` | 파일 삭제 |
| `cvat-core/src/api-implementation.ts` | consensus 관련 메서드 제거 |
| `cvat-ui/src/components/consensus-management-page/` | 디렉토리 전체 삭제 |
| `cvat-ui/src/actions/consensus-actions.ts` | 파일 삭제 |
| `cvat-ui/src/reducers/consensus-reducer.ts` | 파일 삭제 |
| `cvat-ui/src/reducers/index.ts` | consensus reducer import 제거 |
| `cvat-ui/src/components/cvat-app.tsx` | consensus 라우트 정의 제거 |

#### 삭제할 라우트

- `/tasks/:tid/consensus`

#### 데이터베이스 마이그레이션

- ConsensusSettings 테이블 삭제

---

### Phase 7: quality_control 삭제

**현재 상태**: 어노테이션 품질 평가 시스템

**⚠️ 중요**: 이 Phase는 반드시 Phase 6 (consensus) 완료 후에 실행해야 합니다.

#### 백엔드 수정

| 파일 | 작업 |
|------|------|
| `cvat/settings/base.py` | INSTALLED_APPS에서 `"cvat.apps.quality_control"` 제거 |
| `cvat/settings/base.py` | RQ_QUEUES에서 `"quality_reports"` 큐 설정 제거 |
| `cvat/settings/base.py` | quality_reports 큐의 `PARSED_JOB_ID_CLASS` 설정 제거 |
| `cvat/urls.py` | quality URL 패턴 제거 |
| `cvat/apps/quality_control/` | 디렉토리 전체 삭제 |

#### Docker Compose 수정

| 파일 | 작업 |
|------|------|
| `docker-compose.yml` | `cvat_worker_quality_reports` 서비스 전체 제거 |
| `docker-compose.dev.yml` | `cvat_worker_quality_reports` 서비스 전체 제거 |

#### 프론트엔드 수정

| 파일/디렉토리 | 작업 |
|--------------|------|
| `cvat-core/src/quality-report.ts` | 파일 삭제 |
| `cvat-core/src/quality-settings.ts` | 파일 삭제 |
| `cvat-core/src/quality-conflict.ts` | 파일 삭제 |
| `cvat-core/src/api-implementation.ts` | quality 관련 메서드 제거 |
| `cvat-ui/src/components/quality-control/` | 디렉토리 전체 삭제 |
| `cvat-ui/src/components/create-task-page/quality-configuration-form.tsx` | 파일 삭제 |
| `cvat-ui/src/reducers/annotation-reducer.ts` | groundTruthInfo 상태 제거 |
| `cvat-ui/src/components/cvat-app.tsx` | quality-control 라우트 정의 제거 |

#### 삭제할 라우트

- `/tasks/:tid/quality-control`
- `/projects/:pid/quality-control`

#### 데이터베이스 마이그레이션

- QualityReport 테이블 삭제
- AnnotationConflict 테이블 삭제
- AnnotationId 테이블 삭제
- QualitySettings 테이블 삭제

---

## 5. 추가 삭제 가능 항목

Phase 1-7 외에 추가로 삭제할 수 있는 선택적 항목들입니다.

### 5.1 플러그인

| 항목 | 위치 | 설명 |
|------|------|------|
| SAM Plugin | `cvat-ui/plugins/sam/` | Segment Anything Model 통합 |

### 5.2 유틸리티 도구

| 항목 | 위치 | 설명 |
|------|------|------|
| Dataset Manifest | `utils/dataset_manifest/` | 데이터셋 매니페스트 생성 도구 |
| DICOM Converter | `utils/dicom_converter/` | 의료 영상(DICOM) 변환 도구 |
| FFmpeg Compatibility | `utils/ffmpeg_compatibility/` | FFmpeg 버전 호환성 도구 |

### 5.3 외부 연동 설정

| 항목 | 위치 | 설명 |
|------|------|------|
| Nuclio (Serverless) | `components/serverless/` | 서버리스 AI 함수 인프라 |
| 외부 PostgreSQL | `docker-compose.external_db.yml` | 외부 DB 연결 설정 |
| HTTPS/Let's Encrypt | `docker-compose.https.yml` | TLS/SSL 인증서 설정 |
| MinIO/S3 | `tests/docker-compose.minio.yml` | S3 호환 스토리지 |
| 파일 공유/NFS | `tests/docker-compose.file_share.yml` | 네트워크 파일 공유 |

### 5.4 SDK/CLI

| 항목 | 위치 | 설명 |
|------|------|------|
| CVAT SDK | `cvat-sdk/` | Python SDK 전체 |
| CVAT CLI | `cvat-cli/` | CLI 도구 전체 |

### 5.5 테스트

| 항목 | 위치 | 설명 |
|------|------|------|
| Python 테스트 | `tests/python/` | REST API, SDK, CLI 테스트 |
| E2E 테스트 | `tests/cypress/` | Cypress E2E 테스트 |
| OPA 테스트 | `cvat/apps/*/rules/tests/` | 권한 규칙 테스트 |
| CI 설정 | `docker-compose.ci.yml` | CI/CD 설정 |

---

## 6. 작업 체크리스트

각 Phase 실행 시 사용할 체크리스트입니다.

### 6.1 공통 체크리스트

```
□ 1. 작업 전 브랜치 생성
□ 2. 현재 상태 백업 (필요시)
□ 3. Django INSTALLED_APPS에서 앱 제거
□ 4. settings/base.py의 관련 설정 제거
     □ RQ_QUEUES 큐 설정
     □ PARSED_JOB_ID_CLASS 설정
     □ 기타 앱 관련 설정
□ 5. urls.py에서 URL 패턴 제거
□ 6. Core 앱의 역참조 import 수정/제거
     □ engine/serializers.py
     □ events/handlers.py
     □ events/signals.py
     □ iam/urls.py
     □ redis_handler
□ 7. 앱의 signals.py 연결 해제
□ 8. OPA 권한 규칙 파일 삭제 (rules/ 디렉토리)
□ 9. Docker Compose 워커 서비스 제거
     □ docker-compose.yml
     □ docker-compose.dev.yml
□ 10. 프론트엔드 수정
     □ cvat-core 관련 클래스/메서드 삭제
     □ cvat-ui 컴포넌트 삭제
     □ Redux actions 삭제
     □ Redux reducers 삭제
     □ 라우트 정의 제거
□ 11. CLI 수정 (해당되는 경우)
□ 12. 앱 디렉토리 전체 삭제
□ 13. DB 마이그레이션 생성 및 실행
□ 14. 테스트 실행
     □ 백엔드 테스트
     □ 프론트엔드 빌드
     □ 통합 테스트
□ 15. Docker 이미지 재빌드 및 테스트
□ 16. 변경사항 커밋
```

### 6.2 Phase별 특수 체크리스트

#### Phase 1 (dataset_repo)
```
□ 마이그레이션 파일만 존재하는지 확인
□ 다른 앱에서 참조하지 않는지 확인
```

#### Phase 2 (log_viewer)
```
□ CVAT_ANALYTICS 환경변수 관련 코드 제거
□ 조건부 로딩 로직 제거
```

#### Phase 3 (access_tokens)
```
□ REST_FRAMEWORK 인증 클래스 설정 수정
□ 사용자 인증 플로우 테스트
```

#### Phase 4 (webhooks)
```
□ engine/serializers.py의 Webhook 참조 제거
□ 이벤트 핸들러에서 webhook 관련 코드 제거
□ cvat_worker_webhooks 서비스 제거
```

#### Phase 5 (lambda_manager)
```
□ AI 자동 어노테이션 기능 비활성화 확인
□ cvat_worker_annotation 서비스 제거/수정
□ CLI function 명령어 제거
□ Nuclio 설정 제거 (선택)
```

#### Phase 6 (consensus)
```
□ Phase 7 이전에 실행하는지 확인
□ quality_control 앱이 아직 존재하는지 확인
□ cvat_worker_consensus 서비스 제거
```

#### Phase 7 (quality_control)
```
□ Phase 6 완료 확인
□ consensus 앱이 이미 삭제되었는지 확인
□ cvat_worker_quality_reports 서비스 제거
□ Task 생성 폼에서 품질 설정 옵션 제거
```

---

## 참고

### 관련 문서

- [CVAT-Everex 기능 분류](./CVAT-Everex%20기능%20분류%202df6ba33d582803cb8ebdae3c909fdc9.md) - 전체 기능 분류 문서
- [CLAUDE.md](./CLAUDE.md) - 개발 가이드
- [docker-compose.yml](./docker-compose.yml) - 기본 Docker 구성
- [docker-compose.dev.yml](./docker-compose.dev.yml) - 개발 환경 구성

### 주의사항

1. **백업 필수**: 각 Phase 시작 전 데이터베이스와 코드를 백업하세요.
2. **순서 준수**: Phase 6과 7은 반드시 순서대로 진행해야 합니다.
3. **테스트 검증**: 각 Phase 완료 후 전체 시스템 테스트를 수행하세요.
4. **롤백 계획**: 문제 발생 시 롤백할 수 있는 계획을 준비하세요.

---

*이 문서는 2026-01-13에 생성되었습니다.*
