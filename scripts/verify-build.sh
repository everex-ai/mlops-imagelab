#!/bin/bash
# CVAT 빌드 및 배포 검증 스크립트
# 기능 삭제 전후 무결성 확인용

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

RESULTS=()
FAILED=0

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

# 테스트용 볼륨 경로
export CVAT_TEST_DATA_PATH="/tmp/cvat-test"
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.test.yml"

echo "========================================"
echo "CVAT 빌드 검증 스크립트"
echo "프로젝트 루트: $PROJECT_ROOT"
echo "테스트 데이터 경로: $CVAT_TEST_DATA_PATH"
echo "시작 시간: $(date)"
echo "========================================"
echo ""

# 테스트용 디렉토리 생성
log_info "테스트용 볼륨 디렉토리 생성..."
mkdir -p "$CVAT_TEST_DATA_PATH"/{cvat_db,cvat_data,cvat_keys,cvat_logs,cvat_events_db,cvat_cache_db}

# 기존 테스트 환경 정리
log_info "기존 테스트 환경 정리..."
docker compose $COMPOSE_FILES down -v 2>/dev/null || true

# 1. Django 설정 검증
log_info "1/6 Django 설정 검증 중..."
if docker compose $COMPOSE_FILES \
    run --rm --no-deps --entrypoint="" cvat_server_everex python manage.py check --deploy 2>&1; then
    log_success "Django 설정 검증"
else
    log_error "Django 설정 검증 실패"
fi
echo ""

# 2. 마이그레이션 파일 검증 (새 마이그레이션 필요 여부)
log_info "2/6 마이그레이션 파일 검증 중..."
if docker compose $COMPOSE_FILES \
    run --rm --no-deps --entrypoint="" cvat_server_everex python manage.py makemigrations --check --dry-run 2>&1; then
    log_success "마이그레이션 파일 정상"
else
    log_error "마이그레이션 파일 오류"
fi
echo ""

# 3. 도커 이미지 빌드
log_info "3/6 도커 이미지 빌드 중... (시간이 소요될 수 있습니다)"
if docker compose $COMPOSE_FILES build 2>&1; then
    log_success "도커 이미지 빌드"
else
    log_error "도커 이미지 빌드 실패"
fi
echo ""

# 4. 서비스 시작
log_info "4/6 서비스 시작 중..."
if docker compose $COMPOSE_FILES up -d 2>&1; then
    log_success "서비스 시작"
else
    log_error "서비스 시작 실패"
fi
echo ""

# 5. 서비스 안정화 대기 및 헬스체크
log_info "5/6 서비스 안정화 대기 중... (최대 120초)"
MAX_WAIT=120
WAIT_INTERVAL=5
ELAPSED=0

# 컨테이너 내부에서 직접 헬스체크 (traefik 우회)
while [ $ELAPSED -lt $MAX_WAIT ]; do
    if docker exec cvat_server_everex curl -sf http://localhost:8080/api/server/about > /dev/null 2>&1; then
        log_success "API 헬스체크 (${ELAPSED}초 후 응답)"
        break
    fi
    sleep $WAIT_INTERVAL
    ELAPSED=$((ELAPSED + WAIT_INTERVAL))
    echo "  대기 중... ${ELAPSED}초"
done

if [ $ELAPSED -ge $MAX_WAIT ]; then
    log_error "API 헬스체크 실패 (${MAX_WAIT}초 타임아웃)"
fi
echo ""

# 6. 컨테이너 상태 확인
log_info "6/6 컨테이너 상태 확인 중..."
echo ""
docker compose $COMPOSE_FILES ps
echo ""

# 모든 컨테이너가 running 상태인지 확인
UNHEALTHY=$(docker compose $COMPOSE_FILES ps --format json 2>/dev/null | \
    grep -v '"running"' | grep -v '"exited"' | wc -l || echo "0")

if [ "$UNHEALTHY" -eq 0 ]; then
    log_success "컨테이너 상태 정상"
else
    log_error "일부 컨테이너 비정상"
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

if [ $FAILED -eq 0 ]; then
    echo -e "${GREEN}모든 검증 통과${NC}"
    exit 0
else
    echo -e "${RED}일부 검증 실패${NC}"
    exit 1
fi
