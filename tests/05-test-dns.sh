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

check_cmd dig

info "Testing DNS configuration for $DOMAIN"

# --- MX records ---
info "Checking MX records..."
MX_RECORDS=$(dig MX "$DOMAIN" +short 2>&1 || true)
if [ -n "$MX_RECORDS" ]; then
    check "MX records exist for $DOMAIN" 0
    while IFS= read -r line; do
        info "  MX: $line"
    done <<< "$MX_RECORDS"
    if echo "$MX_RECORDS" | grep -qi "$SERVER_IP"; then
        info "  MX references server IP $SERVER_IP"
    fi
else
    check "MX records exist for $DOMAIN" 1
fi

# --- SPF record ---
info "Checking SPF record..."
TXT_RECORDS=$(dig TXT "$DOMAIN" +short 2>&1 || true)
SPF_FOUND=0
if [ -n "$TXT_RECORDS" ]; then
    while IFS= read -r line; do
        if echo "$line" | grep -qi "v=spf1"; then
            check "SPF record found" 0
            info "  SPF: $line"
            SPF_FOUND=1
            break
        fi
    done <<< "$TXT_RECORDS"
fi
if [ "$SPF_FOUND" -eq 0 ]; then
    check "SPF record found" 1
fi

# --- DKIM record ---
info "Checking DKIM record..."
DKIM_FOUND=0
for selector in default dkim 2026 mail; do
    DKIM_RECORD=$(dig TXT "${selector}._domainkey.$DOMAIN" +short 2>&1 || true)
    if [ -n "$DKIM_RECORD" ] && echo "$DKIM_RECORD" | grep -qi "v=dkim1"; then
        check "DKIM record found (selector: $selector)" 0
        info "  DKIM ($selector): $DKIM_RECORD"
        DKIM_FOUND=1
        break
    fi
done
if [ "$DKIM_FOUND" -eq 0 ]; then
    check "DKIM record found" 1
fi

# --- DMARC record ---
info "Checking DMARC record..."
DMARC_RECORD=$(dig TXT "_dmarc.$DOMAIN" +short 2>&1 || true)
if [ -n "$DMARC_RECORD" ] && echo "$DMARC_RECORD" | grep -qi "v=dmarc1"; then
    check "DMARC record found" 0
    info "  DMARC: $DMARC_RECORD"
else
    check "DMARC record found" 1
fi

# --- Reverse DNS (PTR) ---
info "Checking reverse DNS..."
PTR_RECORD=$(dig -x "$SERVER_IP" +short 2>&1 || true)
if [ -n "$PTR_RECORD" ]; then
    check "PTR record exists for $SERVER_IP" 0
    info "  PTR: $PTR_RECORD"
    if echo "$PTR_RECORD" | grep -qi "$DOMAIN"; then
        info "  PTR matches domain $DOMAIN"
    fi
else
    check "PTR record exists for $SERVER_IP" 1
fi

# --- A record ---
info "Checking A record..."
A_RECORD=$(dig A "$DOMAIN" +short 2>&1 || true)
if [ -n "$A_RECORD" ]; then
    check "A record exists for $DOMAIN" 0
    info "  A: $A_RECORD"
else
    check "A record exists for $DOMAIN" 1
fi

# --- swaks delivery test (optional) ---
if command -v swaks &>/dev/null; then
    info "Testing email delivery with swaks..."
    SWAKS_RESULT=$(swaks --to "$TEST_EMAIL" \
        --from "$ADMIN_USER" \
        --server "$SERVER_IP" \
        --port "$SMTP_PORT" \
        --body "DNS test email from MissionControl $(date)" \
        --header "Subject: DNS Test" \
        --timeout 30 2>&1 || true)

    if echo "$SWAKS_RESULT" | grep -qiE "sent|queued|accepted|250"; then
        check "swaks email delivery" 0
    else
        check "swaks email delivery" 1
        info "swaks output: $(echo "$SWAKS_RESULT" | tail -5)"
    fi
else
    info "swaks not installed — skipping delivery test"
    info "Install with: apt install swaks  or  brew install swaks"
fi

# --- Summary ---
echo ""
echo "=========================================="
echo "  DNS Test Results: $PASS passed, $FAIL failed"
echo "=========================================="
for r in "${RESULTS[@]}"; do echo "  $r"; done
exit $FAIL
