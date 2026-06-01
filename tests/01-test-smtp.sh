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

# --- Port connectivity ---
info "Testing SMTP port connectivity..."

for port in "$SMTP_PORT" "$SMTPS_PORT" "$SUBMISSION_PORT"; do
    label="Port $port"
    if timeout 5 bash -c "echo > /dev/tcp/$SERVER_IP/$port" 2>/dev/null; then
        check "SMTP port $port reachable" 0
    else
        check "SMTP port $port reachable" 1
    fi
done

# --- STARTTLS on 587 ---
info "Testing STARTTLS on port $SUBMISSION_PORT..."
STARTTLS_RESULT=$(echo "" | timeout 10 openssl s_client -starttls smtp \
    -connect "$SERVER_IP:$SUBMISSION_PORT" 2>&1 || true)
if echo "$STARTTLS_RESULT" | grep -q "CONNECTED"; then
    check "STARTTLS on port $SUBMISSION_PORT" 0
else
    check "STARTTLS on port $SUBMISSION_PORT" 1
fi

# --- Extended SMTP banner (EHLO) ---
info "Testing SMTP EHLO..."
EHLO_RESULT=$(echo -e "EHLO test\r\nQUIT\r\n" | timeout 10 nc "$SERVER_IP" "$SMTP_PORT" 2>&1 || true)
if echo "$EHLO_RESULT" | grep -qiE "250|ESMTP"; then
    check "SMTP EHLO response" 0
else
    check "SMTP EHLO response" 1
fi

# --- Send email via API ---
info "Sending test email via API..."

AUTH_RESULT=$(curl -s -X POST "$API_BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" 2>&1 || true)
TOKEN=$(echo "$AUTH_RESULT" | grep -o '"token"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')

if [ -n "$TOKEN" ]; then
    check "API authentication obtained token" 0
else
    check "API authentication obtained token" 1
    # If auth fails, skip send test but show partial results
    info "Skipping send test because auth failed"
fi

if [ -n "$TOKEN" ]; then
    SEND_RESULT=$(curl -s -X POST "$API_BASE/send" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -d "{
            \"from\": \"$ADMIN_USER\",
            \"to\": [\"$TEST_EMAIL\"],
            \"subject\": \"Test from MissionControl $(date)\",
            \"text\": \"This is a test email sent by 01-test-smtp.sh\"
        }" 2>&1 || true)

    if echo "$SEND_RESULT" | grep -qiE '"id"|"message_id"|"queued"|"accepted"|"success"'; then
        check "Send email via API" 0

        # Check queue
        sleep 2
        QUEUE_RESULT=$(curl -s "$API_BASE/admin/queue" \
            -H "Authorization: Bearer $TOKEN" 2>&1 || true)
        if echo "$QUEUE_RESULT" | grep -qiE '"count"|"messages"|"queue"|"total"'; then
            check "Email queue accessible" 0
        else
            check "Email queue accessible" 1
        fi
    else
        check "Send email via API" 1
        info "Send response: $SEND_RESULT"
    fi
fi

# --- Summary ---
echo ""
echo "=========================================="
echo "  SMTP Test Results: $PASS passed, $FAIL failed"
echo "=========================================="
for r in "${RESULTS[@]}"; do echo "  $r"; done
exit $FAIL
