# 선택적 기능 삭제 계획

## 전체 진행 상황

| 카테고리 | 상태 | 완료일 | 비고 |
|---------|------|--------|------|
| **1. 즉시 삭제 대상 - dataset_repo** | ✅ 완료 | 2026-01-19 | 삭제 완료 |
| **1. 즉시 삭제 대상 - AI/ML** | ✅ 완료 | 2026-01-22 | serverless, ai-models, lambda_manager 삭제 완료 |
| **1. 즉시 삭제 대상 - Kubernetes** | ✅ 완료 | 2026-01-22 | helm-chart 삭제 완료 |
| **2. 유지할 기능** | ✅ 확인됨 | - | 모든 기능 정상 동작 중 |
| **3. 추가 삭제 검토** | ⏸️ 보류 | - | 필요 시 선택적 삭제 |

---

## 1. 즉시 삭제 대상

### 1.1 ✅ dataset_repo 앱 (완료)

**현재 상태**: ✅ 삭제 완료 (커밋 691baaa5e, 2026-01-19)

**위험도**: 최소 - 기능이 없고 다른 앱에서 참조하지 않음

#### 완료된 작업

| 파일 | 작업 | 상태 |
|------|------|------|
| `cvat/settings/base.py` | INSTALLED_APPS에서 `"cvat.apps.dataset_repo"` 제거 | ✅ |
| `cvat/apps/dataset_repo/` | 디렉토리 전체 삭제 | ✅ |
| 빌드 검증 스크립트 | `scripts/verify-*.sh` 추가 | ✅ |
| 테스트 설정 | `docker-compose.test.yml` 추가 | ✅ |

---

### 1.2 ✅ AI/ML 관련 기능 (완료)

**현재 상태**: ✅ 삭제 완료 (2026-01-22)

**결정**: AI 자동 어노테이션 기능 불필요로 확정, 삭제 완료

**삭제된 영향**: AI 자동 어노테이션 기능 완전 제거

**위험도**: 낮음 - 선택적 기능이며 핵심 어노테이션 기능과 독립적

| 항목 | 위치 | 설명 | 크기 영향 |
|------|------|------|----------|
| 샘플 AI 모델 | `ai-models/` | Detector, Tracker 샘플 | 소형 |
| 서버리스 함수 | `serverless/` | YOLO, SAM, Mask R-CNN 등 | **대형** |
| 관련 Django 앱 | `cvat/apps/lambda_manager/` | AI 함수 관리 앱 | 중형 |

**serverless 디렉토리 상세**:
- `serverless/pytorch/` - PyTorch 기반 모델 (SAM, IOG, MMPose 등)
- `serverless/tensorflow/` - TensorFlow 모델 (Faster R-CNN 등)
- `serverless/openvino/` - OpenVINO 모델 (Face Detection, Mask R-CNN 등)
- `serverless/onnx/` - ONNX 모델 (YOLOv7 등)

#### 완료된 작업

| 작업 | 파일/디렉토리 | 상태 |
|------|--------------|------|
| **백엔드 삭제** | | |
| Lambda Manager 앱 삭제 | `cvat/apps/lambda_manager/` | ✅ |
| Settings 수정 | `cvat/settings/base.py` - INSTALLED_APPS에서 제거 | ✅ |
| URL 라우팅 제거 | `cvat/urls.py` - lambda_manager 라우팅 삭제 | ✅ |
| Redis 직렬화 수정 | `cvat/apps/redis_handler/serializers.py` - LambdaRQMeta 제거 | ✅ |
| **프론트엔드 삭제** | | |
| Lambda Manager 제거 | `cvat-core/src/lambda-manager.ts` 삭제 | ✅ |
| API 통합 제거 | `cvat-core/src/api.ts` - lambda 객체 제거 | ✅ |
| Server Proxy 제거 | `cvat-core/src/server-proxy.ts` - 6개 lambda 함수 삭제 | ✅ |
| UI 액션 수정 | `cvat-ui/src/actions/models-actions.ts` - 에러 처리로 변경 | ✅ |
| 도구 컨트롤 수정 | `cvat-ui/src/components/.../tools-control.tsx` - 로컬 타입 정의 추가 | ✅ |
| **AI 모델 및 서버리스** | | |
| AI 모델 샘플 삭제 | `ai-models/` (52KB) | ✅ |
| 서버리스 함수 삭제 | `serverless/` (220KB) | ✅ |
| **검증** | | |
| 빌드 검증 | `./scripts/verify-build.sh` 통과 | ✅ |
| API 헬스체크 | `/api/server/about` 정상 응답 | ✅ |
| Lambda 엔드포인트 확인 | `/api/lambda/*` 404 반환 (정상) | ✅ |
| Django 앱 확인 | lambda_manager 앱 목록에서 제거됨 | ✅ |

**삭제 통계**:
- 총 101개 파일 삭제
- 총 13개 파일 수정
- 약 456KB 공간 절약 (serverless 220KB + ai-models 52KB + lambda_manager 184KB)

---

### 1.3 ✅ Kubernetes 배포 설정 (완료)

**현재 상태**: ✅ 삭제 완료 (2026-01-22)

**결정**: Kubernetes 미사용 확정, helm-chart 삭제 완료

**삭제된 영향**: Kubernetes 배포 불가 (Docker Compose는 유지됨)

**위험도**: 최소 - Kubernetes 사용하지 않으면 불필요

| 항목 | 위치 | 설명 |
|------|------|------|
| Helm Chart | `helm-chart/` | Kubernetes 배포 차트 (삭제됨) |

#### 완료된 작업

| 작업 | 파일/디렉토리 | 상태 |
|------|--------------|------|
| Helm Chart 삭제 | `helm-chart/` (184KB) | ✅ |
| GitHub Workflow 수정 | `.github/workflows/publish-artifacts.yml` - helm job 제거 | ✅ |
| GitHub Workflow 수정 | `.github/workflows/main.yml` - helm_rest_api_testing job 제거 | ✅ |
| CODEOWNERS 수정 | `.github/CODEOWNERS` - /helm-chart/ 라인 제거 | ✅ |
| 버전 스크립트 수정 | `dev/update_version.py` - helm-chart 버전 규칙 제거 | ✅ |
| **검증** | | |
| 빌드 검증 | Docker Compose 빌드 정상 | ✅ |

**삭제 통계**:
- helm-chart 디렉토리 삭제 (184KB)
- GitHub Actions 워크플로우 2개 수정
- CODEOWNERS 및 버전 관리 스크립트 업데이트

---

## 2. 유지할 기능

다음 기능들은 프로젝트 요구사항에 따라 **유지**합니다:

### 2.1 Django 앱

| 기능 | 앱 | 사유 |
|------|-----|------|
| 로그 시각화 | log_viewer | 운영 모니터링 |
| API 토큰 | access_tokens | API 인증 |
| 웹훅 | webhooks | 외부 시스템 연동 |
| 합의 병합 | consensus | 다중 어노테이터 품질 관리 |
| 품질 평가 | quality_control | consensus 의존성 |
| **분석 이벤트** | **events** | **ClickHouse 이벤트 저장 (Analytics 필요)** |

**현재 상태**: `cvat/settings/base.py`의 INSTALLED_APPS에 모두 등록됨 (총 12개 앱)

```python
INSTALLED_APPS = [
    # ...
    "cvat.apps.iam",
    "cvat.apps.dataset_manager",
    "cvat.apps.organizations",
    "cvat.apps.engine",
    "cvat.apps.webhooks",
    "cvat.apps.health",
    "cvat.apps.events",              # 유지 (Analytics 필요)
    "cvat.apps.quality_control",
    "cvat.apps.redis_handler",
    "cvat.apps.consensus",
    "cvat.apps.access_tokens",
    "cvat.apps.log_viewer",
    # "cvat.apps.lambda_manager",    # ✅ 삭제 완료 (2026-01-22)
]
```

### 2.2 SDK 및 CLI

| 항목 | 위치 | 사유 |
|------|------|------|
| Python SDK | `cvat-sdk/` | 프로그래밍 방식 API 접근 |
| CLI 도구 | `cvat-cli/` | 커맨드라인 작업 자동화 |

**유지 이유**: API를 통한 자동화, 스크립팅, 외부 통합에 필수적입니다.

### 2.3 분석 및 모니터링

**결정**: 사용량 분석 및 모니터링 필요, **유지 확정**

| 항목 | 위치 | 설명 | 용도 |
|------|------|------|------|
| Analytics 스택 | `components/analytics/` | ClickHouse, Grafana, Vector | 사용량 분석 대시보드 |
| Events 앱 | `cvat/apps/events/` | ClickHouse 이벤트 저장 | 분석 데이터 수집 |

**components/analytics 상세**:
- `clickhouse/` - 이벤트 데이터베이스
- `grafana/` - 대시보드 및 시각화
- `vector/` - 로그 수집 파이프라인

**사용 방법**: Docker Compose에서 analytics 스택 포함하여 실행
```bash
# Analytics 포함 실행 (docker-compose.yml에 analytics 설정이 있는 경우)
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d
```

**주의**: `cvat/apps/events/`는 analytics와 연동되므로 함께 유지 필요

### 2.4 핵심 유틸리티

| 도구 | 위치 | 설명 | 필수 여부 |
|------|------|------|----------|
| **Dataset Manifest** | `utils/dataset_manifest/` | **비디오/이미지 메타데이터 관리** | **✅ 필수** |
| DICOM Converter | `utils/dicom_converter/` | 의료 영상 변환 도구 | △ 특수 용도 |
| FFmpeg Compatibility | `utils/ffmpeg_compatibility/` | 비디오 코덱 테스트 도구 | △ 개발 시만 |

**Dataset Manifest 상세 설명**:
- **용도**: CVAT 엔진의 핵심 컴포넌트
- **기능**:
  - 태스크 생성 시 이미지/비디오 파일의 메타데이터(해상도, 프레임 수, 키프레임 위치 등) 생성 및 관리
  - 클라우드 스토리지에서 데이터 다운로드 시 파일 순서 및 정보 보존
  - 비디오 프레임 인덱싱 및 효율적인 탐색
- **의존성**: `cvat/apps/engine/task.py`, `media_extractors.py`, `cache.py`, `backup.py` 등에서 직접 사용
- **삭제 불가**: 엔진의 핵심 기능이므로 **절대 삭제 금지**

### 2.5 개발 도구 및 문서

**결정**: 프로젝트 관리 및 협업에 유용, **유지 확정**

| 항목 | 위치 | 설명 | 유지 이유 |
|------|------|------|----------|
| 변경로그 도구 | `changelog.d/` | scriv 기반 changelog 생성 | 릴리스 관리 |
| 개발 스크립트 | `dev/` | version update, release notes 등 | 버전 관리 |
| GitHub Actions | `.github/workflows/` | 15개 워크플로우 (CI/CD, lint 등) | 코드 품질 및 자동화 |
| 공식 문서 사이트 | `site/` | Hugo 기반 사용자/개발자 문서 | 온보딩 및 참고 |
| 변경 로그 | `CHANGELOG.md` | 전체 변경 이력 | 히스토리 참고 |
| GitHub 설정 | `.github/` | Issue/PR 템플릿, CODEOWNERS | 협업 프로세스 |
| 보안 정책 | `SECURITY.md` | 보안 취약점 보고 정책 | 보안 관리 |

**site/ 디렉토리**:
- **내용**: Hugo + Docsy 테마로 작성된 전체 사용자 문서
- **포함 항목**: 계정 관리, 어노테이션 가이드, API/SDK 문서, 기여 가이드, FAQ 등
- **유지 이유**: 개발자 온보딩과 운영/사용에 유용

**GitHub Actions 워크플로우** (총 15개):
- `docs.yml` - 문서 빌드/배포
- `finalize-release.yml`, `prepare-release.yml` - 릴리스 자동화
- `linters.yml` - 코드 품질 검사
- `full.yml`, `main.yml` - CI/CD
- 기타: `cache.yml`, `codeql-analysis.yml`, `generate-allure-report.yml` 등

---

## 3. 추가 삭제 가능 항목 (선택적)

향후 필요 시 삭제를 검토할 수 있는 항목들입니다.

### 3.1 특수 용도 유틸리티

| 도구 | 위치 | 설명 | 사용 빈도 |
|------|------|------|----------|
| DICOM Converter | `utils/dicom_converter/` | 의료 영상 변환 도구 | 낮음 (특수 용도) |
| FFmpeg Compatibility | `utils/ffmpeg_compatibility/` | 비디오 코덱 테스트 도구 | 낮음 (개발 시만) |

**삭제 가능 조건**: 의료 영상이나 특수 비디오 코덱을 사용하지 않는 경우

### 3.2 불필요한 포맷 (dataset_manager 내)

사용하지 않는 import/export 포맷을 제거하여 경량화 가능:

| 카테고리 | 제거 가능 포맷 | 파일명 |
|---------|---------------|--------|
| 객체 탐지 | Pascal VOC | `pascal_voc.py` |
|  | KITTI | `kitti.py` |
|  | OpenImages | `openimages.py` |
| 세그멘테이션 | Cityscapes | `cityscapes.py` |
|  | CamVid | `camvid.py` |
| 트래킹 | MOT | `mot.py` |
|  | MOTS | `mots.py` |
| 얼굴 인식 | VGGFace2 | `vggface2.py` |
|  | WiderFace | `widerface.py` |
|  | LFW | `lfw.py` |
| 문서 분석 | ICDAR | `icdar.py` |
| 3D | PointCloud | `pointcloud.py` |
|  | VeloPoint | `velodynepoint.py` |
| 범용 | LabelMe | `labelme.py` |
|  | ImageNet | `imagenet.py` |
|  | Market-1501 | `market1501.py` |

**포맷 파일 위치**: `cvat/apps/dataset_manager/formats/` (총 25개 파일)

**주의**:
- COCO, YOLO는 널리 사용되므로 **유지 권장**
- CVAT, Datumaro는 자체 포맷이므로 **유지 필수**

**삭제 절차**:
```bash
# 예: Pascal VOC 포맷 삭제
rm cvat/apps/dataset_manager/formats/pascal_voc.py

# registry.py에서 해당 포맷 등록 제거
# cvat/apps/dataset_manager/formats/registry.py 편집
```

### 3.3 3D 어노테이션

3D 기능이 불필요한 경우 제거 가능:

| 항목 | 위치 | 설명 |
|------|------|------|
| 3D 캔버스 패키지 | `cvat-canvas3d/` | Three.js 기반 3D UI |
| 3D 포맷 | `cvat/apps/dataset_manager/formats/pointcloud.py` | Point Cloud 포맷 |
|  | `cvat/apps/dataset_manager/formats/velodynepoint.py` | Velodyne 포맷 |

**삭제 절차**:
```bash
# 1. 프론트엔드 패키지 제거
rm -rf cvat-canvas3d/

# 2. cvat-ui의 의존성에서 제거
# cvat-ui/package.json 확인 및 수정

# 3. 백엔드 포맷 제거
rm cvat/apps/dataset_manager/formats/pointcloud.py
rm cvat/apps/dataset_manager/formats/velodynepoint.py

# 4. 검증
./scripts/verify-build.sh
```

### 3.4 Docker Compose 변형

특수 환경 설정 파일들 (사용하지 않는 것만 선택적 삭제):

**Docker Compose 파일들**:
- `docker-compose.yml` - **기본** (✅ 필수)
- `docker-compose.dev.yml` - **개발** (✅ 필수)
- `docker-compose.test.yml` - 통합 테스트 (✅ 빌드 검증용, 유지)
- `docker-compose.ci.yml` - CI 전용 (△ CI 미사용 시 삭제 가능)
- `docker-compose.https.yml` - HTTPS 설정 (△ HTTPS 미사용 시 삭제 가능)
- `docker-compose.external_db.yml` - 외부 DB (△ 외부 DB 미사용 시 삭제 가능)
- `docker-compose.unit-test.yml` - 유닛 테스트 (△ 유닛 테스트 미사용 시 삭제 가능)

---

## 4. 삭제 검증 절차

삭제 작업 후 반드시 다음 검증 스크립트를 실행하여 빌드 및 기능이 정상 동작하는지 확인합니다.

### 4.1 빌드 검증 스크립트 (`scripts/` 디렉토리)

```bash
# 1. 빠른 검증 (기본 빌드만 확인)
./scripts/verify-quick.sh

# 2. 전체 빌드 검증 (빌드 + 컨테이너 시작 + 기본 헬스체크)
./scripts/verify-build.sh

# 3. 빌드만 검증 (컨테이너 시작 없이 빌드만)
./scripts/verify-build-only.sh
```

### 4.2 수동 검증

```bash
# 1. Docker Compose 빌드 및 시작
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build

# 2. 로그 확인 (에러 없는지 확인)
docker compose logs -f

# 3. 헬스체크
curl http://localhost:7000/api/server/health

# 4. Python 테스트 실행 (선택적)
pytest tests/python/

# 5. 정리
docker compose down
./scripts/cleanup.sh  # 볼륨 및 임시 파일 정리
```

### 4.3 검증 체크리스트

삭제 후 다음 항목들이 정상 동작하는지 확인:

```
[ ] Docker 빌드 성공 (에러 없음)
[ ] 모든 서비스 정상 시작 (cvat_server, cvat_worker_*, cvat_ui 등)
[ ] 웹 UI 접속 가능 (http://localhost:7000 또는 3000)
[ ] API 헬스체크 통과 (/api/server/health)
[ ] 태스크 생성 및 어노테이션 기능 동작
[ ] 로그에 에러 메시지 없음
```

---

## 5. 삭제 우선순위 요약

### 즉시 삭제 (모두 완료)

| 항목 | 상태 | 완료일 | 효과 |
|------|------|--------|------|
| dataset_repo 앱 | ✅ 완료 | 2026-01-19 | 코드 정리 |
| AI/ML 기능 (serverless, ai-models, lambda_manager) | ✅ 완료 | 2026-01-22 | **456KB 공간 절약, AI 의존성 제거** |
| Kubernetes (helm-chart) | ✅ 완료 | 2026-01-22 | 184KB 공간 절약, K8s 의존성 제거 |

**총 삭제 통계**:
- 총 101개 파일 삭제
- 총 17개 파일 수정 (코드 13개 + 워크플로우/설정 4개)
- 약 640KB 공간 절약

### 유지 확정

- Django 앱: log_viewer, access_tokens, webhooks, consensus, quality_control, **events**
- SDK 및 CLI
- **분석 및 모니터링 (Analytics 스택, events 앱)**
- **Dataset Manifest** (엔진 핵심 기능)
- 개발 도구 (changelog.d, dev, GitHub Actions)
- 문서 (site, CHANGELOG.md, .github, SECURITY.md)

### 선택적 삭제 가능

- 특수 유틸리티 (DICOM Converter, FFmpeg Compatibility)
- 불필요한 dataset 포맷 (사용하지 않는 것만)
- 3D 어노테이션 (3D 기능 미사용 시)
- 특수 Docker Compose 파일 (해당 환경 미사용 시)

---

## 참고

### 관련 문서

- [기능 분류 문서](./CVAT-Everex%20기능%20분류%202df6ba33d582803cb8ebdae3c909fdc9.md)
- [CLAUDE.md](./CLAUDE.md)

### 주의사항

1. **삭제 작업 전 필수 확인**:
   - Git 백업 또는 새 브랜치 생성
   - 삭제할 항목이 다른 곳에서 참조되는지 확인 (grep 활용)
   - 롤백 계획 준비

2. **삭제 후 검증 (필수)**:
   - 빌드 성공 확인: `./scripts/verify-build.sh`
   - 테스트 실행: `pytest tests/python/` (선택적)
   - 기능 동작 확인 (웹 UI, API)

3. **점진적 삭제 권장**:
   - 한 번에 여러 항목 삭제 시 문제 발생 시 원인 파악 어려움
   - 항목별로 삭제 → 테스트 → 커밋 반복
   - 우선순위: AI/ML → Helm Chart → 선택적 항목

---

*최초 생성: 2026-01-13*
*최종 업데이트: 2026-01-22 - 모든 즉시 삭제 대상 완료 (AI/ML, Kubernetes 삭제 완료 및 검증)*
