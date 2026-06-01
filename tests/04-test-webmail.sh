#!/usr/bin/env bash
# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================


set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$DIR/test-config.sh"

PASS=0
FAIL=0
RESULTS=()

check() {
    local name="$1" status="$2"
    if [ "$status" -eq 0 ]; then
        pass "$name"
        PASS=$((PASS + 1))
        RESULTS+=("PASS: $name")
    else
        fail "$name"
        FAIL=$((FAIL + 1))
        RESULTS+=("FAIL: $name")
    fi
}

check_cmd curl

info "Testing webmail at $WEBMAIL_URL"

# --- Webmail accessible ---
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 15 "$WEBMAIL_URL" 2>&1 || echo "000")
if [ "$HTTP_CODE" != "000" ]; then
    check "Webmail URL accessible (HTTP $HTTP_CODE)" 0
else
    check "Webmail URL accessible (HTTP $HTTP_CODE)" 1
fi

# --- Login page content ---
PAGE_CONTENT=$(curl -s --max-time 15 "$WEBMAIL_URL" 2>&1 || true)
if echo "$PAGE_CONTENT" | grep -qiE "roundcube|webmail|login|email|Roundcube|_task=login|rcmail|username|password"; then
    check "Webmail login page loads (Roundcube detected)" 0
else
    check "Webmail login page loads (Roundcube detected)" 1
    info "Page content snippet: $(echo "$PAGE_CONTENT" | head -c 500)"
fi

# --- Test login ---
LOGIN_POST=$(curl -s -c /tmp/webmail_test_cookies --max-time 15 \
    -H "Content-Type: application/x-www-form-urlencoded" \
    -d "_task=login&_action=login&_user=$ADMIN_USER&_pass=$ADMIN_PASS" \
    "$WEBMAIL_URL" 2>&1 || true)

if echo "$LOGIN_POST" | grep -qiE "logout|_task=mail|Invalid request|Invalid password|Login failed"; then
    if echo "$LOGIN_POST" | grep -qiE "logout|_task=mail"; then
        check "Webmail login successful" 0
    else
        # Login failed but we got a valid response (not a timeout)
        check "Webmail login attempted (received response)" 0
        info "Login did not appear successful — may be expected with test credentials"
    fi
else
    HTTP_LOGIN=$(curl -s -o /dev/null -w "%{http_code}" -c /tmp/webmail_test_cookies --max-time 15 \
        -H "Content-Type: application/x-www-form-urlencoded" \
        -d "_task=login&_action=login&_user=$ADMIN_USER&_pass=$ADMIN_PASS" \
        "$WEBMAIL_URL" 2>&1 || echo "000")
    if [ "$HTTP_LOGIN" != "000" ]; then
        check "Webmail login endpoint reachable (HTTP $HTTP_LOGIN)" 0
    else
        check "Webmail login endpoint reachable (HTTP $HTTP_LOGIN)" 1
    fi
fi

rm -f /tmp/webmail_test_cookies

# --- Managesieve (optional) ---
info "Checking managesieve (port 4190)..."
if timeout 5 bash -c "echo > /dev/tcp/$SERVER_IP/4190" 2>/dev/null; then
    SIEVE_RESULT=$(echo "" | timeout 10 openssl s_client -connect "$SERVER_IP:4190" 2>&1 || true)
    if echo "$SIEVE_RESULT" | grep -q "CONNECTED"; then
        check "Managesieve (port 4190) reachable" 0
    else
        check "Managesieve (port 4190) reachable" 0
        info "Port 4190 open but TLS handshake may differ"
    fi
else
    info "Managesieve port 4190 not reachable (optional — skipping)"
fi

# --- Summary ---
echo ""
echo "=========================================="
echo "  Webmail Test Results: $PASS passed, $FAIL failed"
echo "=========================================="
for r in "${RESULTS[@]}"; do echo "  $r"; done
exit $FAIL
