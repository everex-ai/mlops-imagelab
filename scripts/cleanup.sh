#!/bin/bash
# CVAT 테스트 환경 정리 스크립트

cd "$(dirname "$0")/.."

export CVAT_TEST_DATA_PATH="/tmp/cvat-test"
COMPOSE_FILES="-f docker-compose.yml -f docker-compose.dev.yml -f docker-compose.test.yml"

echo "CVAT 테스트 환경 정리 중..."
docker compose $COMPOSE_FILES down -v 2>/dev/null || true

echo "테스트 데이터 디렉토리 정리..."
rm -rf "$CVAT_TEST_DATA_PATH"

echo "완료"
