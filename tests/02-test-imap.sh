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
info "Testing IMAP port connectivity..."

for port in "$IMAP_PORT" "$IMAPS_PORT"; do
    label="Port $port"
    if timeout 5 bash -c "echo > /dev/tcp/$SERVER_IP/$port" 2>/dev/null; then
        check "IMAP port $port reachable" 0
    else
        check "IMAP port $port reachable" 1
    fi
done

# --- STARTTLS on 143 ---
info "Testing STARTTLS on port $IMAP_PORT..."
STARTTLS_RESULT=$(echo "" | timeout 10 openssl s_client -starttls imap \
    -connect "$SERVER_IP:$IMAP_PORT" 2>&1 || true)
if echo "$STARTTLS_RESULT" | grep -q "CONNECTED"; then
    check "STARTTLS on port $IMAP_PORT" 0
else
    check "STARTTLS on port $IMAP_PORT" 1
fi

# --- IMAPS (993) ---
info "Testing IMAPS on port $IMAPS_PORT..."
IMAPS_RESULT=$(echo "" | timeout 10 openssl s_client -connect "$SERVER_IP:$IMAPS_PORT" 2>&1 || true)
if echo "$IMAPS_RESULT" | grep -q "CONNECTED"; then
    check "IMAPS on port $IMAPS_PORT" 0
else
    check "IMAPS on port $IMAPS_PORT" 1
fi

# --- IMAP login and basic commands ---
info "Testing IMAP commands via openssl..."

# Build the IMAP command sequence
IMAP_CMDS="a001 LOGIN $ADMIN_USER $ADMIN_PASS\r\na002 LIST \"\" \"*\"\r\na003 SELECT INBOX\r\na004 FETCH 1:* (FLAGS)\r\na005 LOGOUT\r\n"

# Use openssl with STARTTLS for cleartext testing, or plain TCP for IMAPS
IMAP_RESP=$(printf "%b" "$IMAP_CMDS" | timeout 15 openssl s_client -starttls imap \
    -connect "$SERVER_IP:$IMAP_PORT" 2>&1 || true)

if echo "$IMAP_RESP" | grep -qiE "a001 OK.*LOGIN|a001 OK.*completed"; then
    check "IMAP LOGIN" 0
else
    check "IMAP LOGIN" 1
fi

if echo "$IMAP_RESP" | grep -qiE "a002 OK.*LIST|a002 OK.*completed"; then
    check "IMAP LIST" 0
else
    check "IMAP LIST" 1
fi

if echo "$IMAP_RESP" | grep -qiE "a003 OK.*SELECT|a003 OK.*completed"; then
    check "IMAP SELECT INBOX" 0
else
    check "IMAP SELECT INBOX" 1
fi

if echo "$IMAP_RESP" | grep -qiE "a004 OK.*FETCH|a004 OK.*completed"; then
    check "IMAP FETCH" 0
else
    check "IMAP FETCH" 1
fi

# --- Summary ---
echo ""
echo "=========================================="
echo "  IMAP Test Results: $PASS passed, $FAIL failed"
echo "=========================================="
for r in "${RESULTS[@]}"; do echo "  $r"; done
exit $FAIL
