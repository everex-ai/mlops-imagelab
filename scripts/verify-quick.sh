#!/bin/bash
# CVAT 빠른 검증 스크립트 (빌드 없이 설정만 확인)
# 코드 변경 후 빠른 검증용

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

FAILED=0

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
    FAILED=1
}

cd "$(dirname "$0")/.."

# 테스트용 볼륨 경로
export CVAT_TEST_DATA_PATH="/tmp/cvat-test"
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.test.yml"

echo "========================================"
echo "CVAT 빠른 검증 (설정만 확인)"
echo "테스트 데이터 경로: $CVAT_TEST_DATA_PATH"
echo "========================================"
echo ""

# 테스트용 디렉토리 생성
log_info "테스트용 볼륨 디렉토리 생성..."
mkdir -p "$CVAT_TEST_DATA_PATH"/{cvat_db,cvat_data,cvat_keys,cvat_logs,cvat_events_db,cvat_cache_db}

# 기존 테스트 볼륨 정리
log_info "기존 테스트 볼륨 정리..."
docker compose $COMPOSE_FILES down -v 2>/dev/null || true

# 1. Django 설정 검증
log_info "1/3 Django 설정 검증..."
if docker compose $COMPOSE_FILES \
    run --rm --no-deps --entrypoint="" cvat_server_everex python manage.py check 2>&1; then
    log_success "Django 설정"
else
    log_error "Django 설정 오류"
fi

# 2. 마이그레이션 파일 검증 (새 마이그레이션 필요 여부)
log_info "2/3 마이그레이션 파일 검증..."
if docker compose $COMPOSE_FILES \
    run --rm --no-deps --entrypoint="" cvat_server_everex python manage.py makemigrations --check --dry-run 2>&1; then
    log_success "마이그레이션 파일"
else
    log_error "마이그레이션 파일 오류 (새 마이그레이션 필요)"
fi

# 3. Import 검증 (앱이 정상적으로 로드되는지)
log_info "3/3 앱 Import 검증..."
if docker compose $COMPOSE_FILES \
    run --rm --no-deps --entrypoint="" cvat_server_everex python -c "
import django
django.setup()
from django.apps import apps
configs = apps.get_app_configs()
print('Installed apps:', len(configs))
for c in sorted(configs, key=lambda x: x.name):
    if 'cvat' in c.name:
        print(f'  - {c.name}')
" 2>&1; then
    log_success "앱 Import"
else
    log_error "앱 Import 오류"
fi

echo ""
echo "========================================"
if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}빠른 검증 통과${NC}"
    exit 0
else
    echo -e "${RED}검증 실패${NC}"
    exit 1
fi
