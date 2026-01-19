#!/bin/bash
# verify-quick과 verify-build를 병렬로 실행
# 둘 다 성공해야 통과

set -e

cd "$(dirname "$0")/.."

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "========================================"
echo "병렬 검증 시작"
echo "  - verify-quick (Django 설정)"
echo "  - verify-build (Docker 빌드/배포)"
echo "========================================"
echo ""

# 임시 파일로 결과 저장
QUICK_RESULT="/tmp/verify-quick-result-$$"
BUILD_RESULT="/tmp/verify-build-result-$$"

# 병렬 실행
(
    ./scripts/verify-quick.sh > /tmp/verify-quick-output-$$ 2>&1
    echo $? > "$QUICK_RESULT"
) &
QUICK_PID=$!

(
    ./scripts/verify-build.sh > /tmp/verify-build-output-$$ 2>&1
    echo $? > "$BUILD_RESULT"
) &
BUILD_PID=$!

# 진행 상황 표시
echo -e "${YELLOW}[실행 중]${NC} verify-quick (PID: $QUICK_PID)"
echo -e "${YELLOW}[실행 중]${NC} verify-build (PID: $BUILD_PID)"
echo ""

# 대기
QUICK_DONE=false
BUILD_DONE=false

while ! $QUICK_DONE || ! $BUILD_DONE; do
    if ! $QUICK_DONE && ! kill -0 $QUICK_PID 2>/dev/null; then
        QUICK_DONE=true
        QUICK_EXIT=$(cat "$QUICK_RESULT" 2>/dev/null || echo "1")
        if [ "$QUICK_EXIT" = "0" ]; then
            echo -e "${GREEN}[완료]${NC} verify-quick 통과"
        else
            echo -e "${RED}[실패]${NC} verify-quick"
            echo "--- verify-quick 출력 ---"
            cat /tmp/verify-quick-output-$$ 2>/dev/null || true
            echo "------------------------"
        fi
    fi

    if ! $BUILD_DONE && ! kill -0 $BUILD_PID 2>/dev/null; then
        BUILD_DONE=true
        BUILD_EXIT=$(cat "$BUILD_RESULT" 2>/dev/null || echo "1")
        if [ "$BUILD_EXIT" = "0" ]; then
            echo -e "${GREEN}[완료]${NC} verify-build 통과"
        else
            echo -e "${RED}[실패]${NC} verify-build"
            echo "--- verify-build 출력 ---"
            cat /tmp/verify-build-output-$$ 2>/dev/null || true
            echo "------------------------"
        fi
    fi

    sleep 2
done

# 정리
rm -f /tmp/verify-quick-output-$$ /tmp/verify-build-output-$$
rm -f "$QUICK_RESULT" "$BUILD_RESULT"

# 결과 확인
echo ""
echo "========================================"
if [ "$QUICK_EXIT" = "0" ] && [ "$BUILD_EXIT" = "0" ]; then
    echo -e "${GREEN}병렬 검증 통과${NC}"
    exit 0
else
    echo -e "${RED}병렬 검증 실패${NC}"
    exit 1
fi
