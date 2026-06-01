#!/usr/bin/env bash
# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================


set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/test-config.sh"

ALL_TESTS=(
    "$DIR/01-test-smtp.sh"
    "$DIR/02-test-imap.sh"
    "$DIR/03-test-api.sh"
    "$DIR/04-test-webmail.sh"
    "$DIR/05-test-dns.sh"
)

TOTAL_TESTS=${#ALL_TESTS[@]}
TOTAL_PASS=0
TOTAL_FAIL=0
REPORT_FILE="$DIR/test-report-$(date +%Y%m%d-%H%M%S).txt"

echo ""
echo "=========================================="
echo "  MissionControl Test Suite"
echo "  Started: $(date)"
echo "=========================================="
echo ""
echo "  Server:  $SERVER_IP"
echo "  Domain:  $DOMAIN"
echo "  API:     $API_BASE"
echo "  Webmail: $WEBMAIL_URL"
echo ""

echo "=========================================="
echo "  Running $TOTAL_TESTS test suites..."
echo "=========================================="

declare -A SUITE_PASS SUITE_FAIL SUITE_STATUS

for test_script in "${ALL_TESTS[@]}"; do
    test_name="$(basename "$test_script")"
    echo ""
    echo "------------------------------------------"
    echo "  Running: $test_name"
    echo "------------------------------------------"

    set +e
    output=$("$test_script" 2>&1)
    exit_code=$?
    set -e

    # Parse pass/fail from the suite's own output
    suite_pass=$(echo "$output" | grep -oE '[0-9]+ passed' | grep -oE '[0-9]+' || echo "0")
    suite_fail=$(echo "$output" | grep -oE '[0-9]+ failed' | grep -oE '[0-9]+' || echo "0")

    SUITE_PASS["$test_name"]=$suite_pass
    SUITE_FAIL["$test_name"]=$suite_fail
    TOTAL_PASS=$((TOTAL_PASS + suite_pass))
    TOTAL_FAIL=$((TOTAL_FAIL + suite_fail))

    if [ "$exit_code" -eq 0 ] && [ "$suite_fail" -eq 0 ]; then
        SUITE_STATUS["$test_name"]="PASS"
    else
        SUITE_STATUS["$test_name"]="FAIL"
    fi

    echo "$output"
done

# --- Final Summary ---
echo ""
echo "=========================================="
echo "  FINAL SUMMARY"
echo "=========================================="
echo ""

for test_script in "${ALL_TESTS[@]}"; do
    test_name="$(basename "$test_script")"
    status="${SUITE_STATUS[$test_name]}"
    p="${SUITE_PASS[$test_name]}"
    f="${SUITE_FAIL[$test_name]}"
    if [ "$status" = "PASS" ]; then
        echo -e "  ${GREEN}[PASS]${NC} $test_name  (${p} passed)"
    else
        echo -e "  ${RED}[FAIL]${NC} $test_name  (${p} passed, ${f} failed)"
    fi
done

echo ""
echo "  Total: $TOTAL_PASS passed, $TOTAL_FAIL failed"
echo ""

if [ "$TOTAL_FAIL" -eq 0 ]; then
    echo -e "  ${GREEN}All tests passed!${NC}"
else
    echo -e "  ${RED}Some tests failed. Review output above.${NC}"
fi

echo ""
echo "=========================================="
echo "  Test report saved to:"
echo "  $REPORT_FILE"
echo "=========================================="

# Generate report file
{
    echo "=========================================="
    echo "  MissionControl Test Report"
    echo "  Generated: $(date)"
    echo "=========================================="
    echo ""
    echo "  Server:  $SERVER_IP"
    echo "  Domain:  $DOMAIN"
    echo "  API:     $API_BASE"
    echo "  Webmail: $WEBMAIL_URL"
    echo ""
    echo "=========================================="
    echo "  Results Summary"
    echo "=========================================="
    echo ""
    for test_script in "${ALL_TESTS[@]}"; do
        test_name="$(basename "$test_script")"
        status="${SUITE_STATUS[$test_name]}"
        p="${SUITE_PASS[$test_name]}"
        f="${SUITE_FAIL[$test_name]}"
        echo "  [$status] $test_name — ${p} passed, ${f} failed"
    done
    echo ""
    echo "  Total: $TOTAL_PASS passed, $TOTAL_FAIL failed"
    echo ""
    if [ "$TOTAL_FAIL" -eq 0 ]; then
        echo "  All tests passed!"
    else
        echo "  Some tests failed."
    fi
} > "$REPORT_FILE"

exit $TOTAL_FAIL
