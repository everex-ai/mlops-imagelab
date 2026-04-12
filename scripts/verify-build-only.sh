#!/bin/bash
# CVAT 이미지 빌드 전용 검증 스크립트
# 볼륨 마운트 없이 빌드와 설정만 확인

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAILED=0
RESULTS=()

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
    RESULTS+=("✓ $1")
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    RESULTS+=("✗ $1")
    FAILED=1
}

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

echo "========================================"
echo "CVAT 이미지 빌드 검증"
echo "프로젝트: $PROJECT_ROOT"
echo "시작: $(date)"
echo "========================================"
echo ""

# 1. 도커 이미지 빌드
log_info "1/3 서버 이미지 빌드 중..."
if docker build -t cvat-everex/server:test -f Dockerfile . 2>&1; then
    log_success "서버 이미지 빌드"
else
    log_error "서버 이미지 빌드 실패"
fi
echo ""

# 2. Django 설정 검증 (컨테이너 내에서)
log_info "2/3 Django 설정 검증 중..."
if docker run --rm --entrypoint="" \
    -e DJANGO_SETTINGS_MODULE=cvat.settings.production \
    -e ALLOWED_HOSTS='*' \
    -e DJANGO_SECRET_KEY='test-secret-key-for-validation-only' \
    cvat-everex/server:test \
    python manage.py check 2>&1; then
    log_success "Django 설정 검증"
else
    log_error "Django 설정 검증 실패"
fi
echo ""

# 3. 앱 Import 검증
log_info "3/3 앱 Import 검증 중..."
if docker run --rm --entrypoint="" \
    -e DJANGO_SETTINGS_MODULE=cvat.settings.production \
    -e ALLOWED_HOSTS='*' \
    -e DJANGO_SECRET_KEY='test-secret-key-for-validation-only' \
    cvat-everex/server:test \
    python -c "
import django
django.setup()
from django.apps import apps
configs = apps.get_app_configs()
print('=== Installed Django Apps ===')
for config in sorted(configs, key=lambda x: x.name):
    print(f'  {config.name}')
print(f'Total: {len(configs)} apps')
" 2>&1; then
    log_success "앱 Import 검증"
else
    log_error "앱 Import 검증 실패"
fi
echo ""

# 결과 요약
echo "========================================"
echo "검증 결과 요약"
echo "========================================"
for result in "${RESULTS[@]}"; do
    echo "$result"
done
echo ""

# 테스트 이미지 정리
log_info "테스트 이미지 정리 중..."
docker rmi cvat-everex/server:test 2>/dev/null || true

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}모든 검증 통과${NC}"
    exit 0
else
    echo -e "${RED}일부 검증 실패${NC}"
    exit 1
fi
