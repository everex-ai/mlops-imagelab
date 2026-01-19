#!/bin/bash
# CVAT 테스트 실행 스크립트
# 사용법: ./scripts/run-tests.sh [unit|api|e2e|all]

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() {
    echo -e "${YELLOW}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

log_error() {
    echo -e "${RED}[FAIL]${NC} $1"
}

cd "$(dirname "$0")/.."
PROJECT_ROOT=$(pwd)

# 테스트용 볼륨 경로
export CVAT_TEST_DATA_PATH="/tmp/cvat-test"
# 기본 compose 파일 (운영/개발 환경)
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.test.yml"
# 유닛 테스트용 compose 파일 (동기 RQ + fakeredis)
COMPOSE_FILES_UNIT="-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.test.yml -f docker-compose.unit-test.yml"

show_help() {
    echo "CVAT 테스트 실행 스크립트"
    echo ""
    echo "사용법: $0 [옵션]"
    echo ""
    echo "옵션:"
    echo "  unit     Django 유닛 테스트 실행 (cvat/apps)"
    echo "  api      REST API 테스트 실행 (tests/python)"
    echo "  e2e      Cypress E2E 테스트 실행 (tests/cypress)"
    echo "  all      모든 테스트 실행"
    echo "  help     도움말 표시"
    echo ""
    echo "예시:"
    echo "  $0 unit              # 유닛 테스트만 실행"
    echo "  $0 api               # API 테스트만 실행"
    echo "  $0 unit api          # 유닛 + API 테스트 실행"
    echo ""
}

# 테스트용 디렉토리 생성
setup_test_env() {
    log_info "테스트 환경 설정 중..."
    mkdir -p "$CVAT_TEST_DATA_PATH"/{cvat_db,cvat_data,cvat_keys,cvat_logs,cvat_events_db,cvat_cache_db}
}

# 서비스 실행 중인지 확인
check_services_running() {
    docker exec cvat_server_everex curl -sf http://localhost:8080/api/server/about > /dev/null 2>&1
}

# 서비스 시작 및 대기 (이미 실행 중이면 건너뜀)
start_services() {
    # 이미 실행 중인지 확인
    if check_services_running; then
        log_success "서비스가 이미 실행 중 (건너뜀)"
        return 0
    fi

    log_info "서비스 시작 중..."
    docker compose $COMPOSE_FILES up -d

    log_info "서비스 안정화 대기 중... (최대 120초)"
    MAX_WAIT=120
    WAIT_INTERVAL=5
    ELAPSED=0

    while [ $ELAPSED -lt $MAX_WAIT ]; do
        if check_services_running; then
            log_success "서비스 준비 완료 (${ELAPSED}초)"
            return 0
        fi
        sleep $WAIT_INTERVAL
        ELAPSED=$((ELAPSED + WAIT_INTERVAL))
        echo "  대기 중... ${ELAPSED}초"
    done

    log_error "서비스 시작 타임아웃"
    return 1
}

# 유닛 테스트용 서비스 시작 (동기 RQ + fakeredis)
start_unit_test_services() {
    log_info "유닛 테스트용 서비스 빌드 및 시작 중..."
    log_info "(동기 RQ + fakeredis 설정으로 빌드)"

    # 유닛 테스트용 이미지 빌드 및 시작
    docker compose $COMPOSE_FILES_UNIT up -d --build

    log_info "서비스 안정화 대기 중... (최대 120초)"
    MAX_WAIT=120
    WAIT_INTERVAL=5
    ELAPSED=0

    while [ $ELAPSED -lt $MAX_WAIT ]; do
        if docker exec cvat_server_everex curl -sf http://localhost:8080/api/server/about > /dev/null 2>&1; then
            log_success "유닛 테스트 서비스 준비 완료 (${ELAPSED}초)"
            return 0
        fi
        sleep $WAIT_INTERVAL
        ELAPSED=$((ELAPSED + WAIT_INTERVAL))
        echo "  대기 중... ${ELAPSED}초"
    done

    log_error "서비스 시작 타임아웃"
    return 1
}

# Django 유닛 테스트
run_unit_tests() {
    log_info "Django 유닛 테스트 실행 중..."
    echo ""

    # 유닛 테스트용 서비스 시작 (동기 RQ 모드)
    start_unit_test_services || return 1

    if docker compose $COMPOSE_FILES_UNIT \
        exec -T cvat_server_everex python manage.py test -v 2 cvat/apps 2>&1; then
        log_success "Django 유닛 테스트 통과"
        return 0
    else
        log_error "Django 유닛 테스트 실패"
        return 1
    fi
}

# REST API 테스트 (pytest)
run_api_tests() {
    log_info "REST API 테스트 실행 중..."
    echo ""

    # SDK 생성 확인
    if [ ! -d "cvat-sdk/cvat_sdk" ]; then
        log_info "SDK 생성 중..."
        pip3 install -r cvat-sdk/gen/requirements.txt 2>/dev/null || true
        ./cvat-sdk/gen/generate.sh 2>/dev/null || true
    fi

    # 테스트 의존성 설치
    log_info "테스트 의존성 설치 중..."
    pip3 install -r tests/python/requirements.txt \
        -e './cvat-sdk[masks,pytorch]' -e ./cvat-cli \
        --extra-index-url https://download.pytorch.org/whl/cpu 2>/dev/null || {
        log_error "테스트 의존성 설치 실패"
        return 1
    }

    # pytest 실행
    if pytest tests/python/ --timeout=60 -v 2>&1; then
        log_success "REST API 테스트 통과"
        return 0
    else
        log_error "REST API 테스트 실패"
        return 1
    fi
}

# E2E 테스트 (Cypress)
run_e2e_tests() {
    log_info "E2E 테스트 실행 중..."
    echo ""

    cd tests

    # 의존성 설치
    if [ ! -d "node_modules" ]; then
        log_info "E2E 테스트 의존성 설치 중..."
        corepack enable yarn 2>/dev/null || true
        yarn --immutable
    fi

    # 관리자 계정 생성
    log_info "테스트용 관리자 계정 생성..."
    docker exec cvat_server_everex python manage.py shell -c "
from django.contrib.auth.models import User
if not User.objects.filter(username='admin').exists():
    User.objects.create_superuser('admin', 'admin@localhost.company', '12qwaszx')
    print('Admin user created')
else:
    print('Admin user already exists')
" 2>/dev/null || true

    # Cypress 실행
    if npx cypress run --browser chrome --spec 'cypress/e2e/actions_tasks/**/*.js' 2>&1; then
        log_success "E2E 테스트 통과"
        cd "$PROJECT_ROOT"
        return 0
    else
        log_error "E2E 테스트 실패"
        cd "$PROJECT_ROOT"
        return 1
    fi
}

# 메인 실행
main() {
    if [ $# -eq 0 ] || [ "$1" == "help" ] || [ "$1" == "-h" ] || [ "$1" == "--help" ]; then
        show_help
        exit 0
    fi

    echo "========================================"
    echo "CVAT 테스트 실행"
    echo "프로젝트 루트: $PROJECT_ROOT"
    echo "시작 시간: $(date)"
    echo "========================================"
    echo ""

    RUN_UNIT=false
    RUN_API=false
    RUN_E2E=false
    FAILED=0

    for arg in "$@"; do
        case $arg in
            unit) RUN_UNIT=true ;;
            api) RUN_API=true ;;
            e2e) RUN_E2E=true ;;
            all)
                RUN_UNIT=true
                RUN_API=true
                RUN_E2E=true
                ;;
            *)
                echo "알 수 없는 옵션: $arg"
                show_help
                exit 1
                ;;
        esac
    done

    # 환경 설정
    setup_test_env

    # 테스트 실행
    # 유닛 테스트는 자체적으로 동기 RQ 서비스 시작
    if $RUN_UNIT; then
        run_unit_tests || FAILED=1
        echo ""
    fi

    # API/E2E 테스트는 일반 서비스 필요
    if $RUN_API || $RUN_E2E; then
        start_services || exit 1
    fi

    if $RUN_API; then
        run_api_tests || FAILED=1
        echo ""
    fi

    if $RUN_E2E; then
        run_e2e_tests || FAILED=1
        echo ""
    fi

    # 결과 요약
    echo "========================================"
    echo "테스트 완료"
    echo "========================================"

    if [ $FAILED -eq 0 ]; then
        echo -e "${GREEN}모든 테스트 통과${NC}"
        exit 0
    else
        echo -e "${RED}일부 테스트 실패${NC}"
        exit 1
    fi
}

main "$@"
