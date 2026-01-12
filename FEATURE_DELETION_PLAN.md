# 선택적 기능 삭제 계획

---

## 1. 즉시 삭제 대상

### dataset_repo 앱 삭제

**현재 상태**: 레거시 앱, models.py 비어있음, 마이그레이션만 존재

**위험도**: 최소 - 기능이 없고 다른 앱에서 참조하지 않음

#### 수정 대상

| 파일 | 작업 |
|------|------|
| `cvat/settings/base.py` | INSTALLED_APPS에서 `"cvat.apps.dataset_repo"` 제거 |
| `cvat/apps/dataset_repo/` | 디렉토리 전체 삭제 |

#### 삭제 절차

```bash
# 1. INSTALLED_APPS에서 제거 (cvat/settings/base.py 편집)

# 2. 앱 디렉토리 삭제
rm -rf cvat/apps/dataset_repo/

# 3. 서버 재시작하여 정상 동작 확인
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d --build
```

#### 체크리스트

```
[ ] 작업 전 브랜치 생성
[ ] cvat/settings/base.py에서 INSTALLED_APPS의 "cvat.apps.dataset_repo" 제거
[ ] cvat/apps/dataset_repo/ 디렉토리 삭제
[ ] 서버 재시작 및 정상 동작 확인
[ ] 테스트 실행
[ ] 변경사항 커밋
```

---

## 2. 유지할 기능

다음 기능들은 프로젝트 요구사항에 따라 유지합니다:

| 기능 | 앱 | 사유 |
|------|-----|------|
| 로그 시각화 | log_viewer | 운영 모니터링 |
| API 토큰 | access_tokens | API 인증 |
| 웹훅 | webhooks | 외부 시스템 연동 |
| AI 함수 | lambda_manager | AI 자동 어노테이션 |
| 합의 병합 | consensus | 다중 어노테이터 품질 관리 |
| 품질 평가 | quality_control | consensus 의존성 |

---

## 3. 추가 삭제 가능 항목

향후 필요 시 삭제를 검토할 수 있는 항목들입니다.

### 3.1 유틸리티 도구

| 도구 | 위치 | 설명 |
|------|------|------|
| Dataset Manifest | `utils/dataset_manifest/` | 대용량 데이터셋 인덱싱 도구 |
| DICOM Converter | `utils/dicom_converter/` | 의료 영상 변환 도구 |
| FFmpeg Compatibility | `utils/ffmpeg_compatibility/` | 비디오 코덱 테스트 도구 |

### 3.2 SDK/CLI

| 항목 | 위치 | 설명 |
|------|------|------|
| SDK | `cvat-sdk/` | Python SDK |
| CLI | `cvat-cli/` | CLI 도구 |

### 3.3 테스트

| 테스트 | 위치 |
|--------|------|
| Python 테스트 | `tests/python/` |
| E2E 테스트 | `tests/cypress/` |
| CI 설정 | `docker-compose.ci.yml` |

### 3.4 불필요한 포맷 (dataset_manager 내)

사용하지 않는 import/export 포맷을 제거하여 경량화 가능:

| 카테고리 | 제거 가능 포맷 |
|---------|---------------|
| 객체 탐지 | Pascal VOC, KITTI, OpenImages |
| 세그멘테이션 | Cityscapes, CamVid |
| 트래킹 | MOT, MOTS |
| 얼굴 인식 | VGGFace2, WideFace, LFW |
| 문서 분석 | ICDAR |
| 3D | PointCloud, VeloPoint (3D 불필요 시) |
| 범용 | LabelMe, ImageNet |

**포맷 파일 위치**: `cvat/apps/dataset_manager/formats/`

### 3.5 3D 어노테이션

3D 기능이 불필요한 경우 제거 가능:

| 항목 | 위치 |
|------|------|
| 3D 캔버스 패키지 | `cvat-canvas3d/` |
| 3D 포맷 | `cvat/apps/dataset_manager/formats/pointcloud.py`, `velodynepoint.py` |

### 3.6 문서

| 항목 | 위치 |
|------|------|
| 사이트 문서 | `site/` |
| 변경 로그 | `CHANGELOG.md` |
| GitHub 설정 | `.github/` |

---

## 참고

### 관련 문서

- [기능 분류 문서](./CVAT-Everex%20기능%20분류%202df6ba33d582803cb8ebdae3c909fdc9.md)
- [CLAUDE.md](./CLAUDE.md)

### 주의사항

1. 삭제 작업 전 백업 필수
2. 삭제 후 테스트 검증 필수
3. 롤백 계획 준비

---

*2026-01-13 생성*
