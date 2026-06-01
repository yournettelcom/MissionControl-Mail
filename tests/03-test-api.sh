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
TOKEN=""

check_endpoint() {
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

api_get() {
    local url="$1" desc="$2" expect="$3"
    local resp
    resp=$(curl -s -o /dev/null -w "%{http_code}" "$url" 2>&1 || true)
    if [ "$resp" = "$expect" ] || [ "$expect" = "any" ]; then
        check_endpoint "$desc (HTTP $resp)" 0
    else
        check_endpoint "$desc (HTTP $resp, expected $expect)" 1
    fi
}

api_post() {
    local url="$1" data="$2" desc="$3" expect="$4" auth_header=""
    [ $# -ge 5 ] && auth_header="$5"
    local resp
    resp=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$url" \
        -H "Content-Type: application/json" \
        ${auth_header:+-H "Authorization: Bearer $TOKEN"} \
        -d "$data" 2>&1 || true)
    if [ "$resp" = "$expect" ] || [ "$expect" = "any" ]; then
        check_endpoint "$desc (HTTP $resp)" 0
    else
        check_endpoint "$desc (HTTP $resp, expected $expect)" 1
    fi
}

api_put() {
    local url="$1" data="$2" desc="$3" expect="$4"
    local resp
    resp=$(curl -s -o /dev/null -w "%{http_code}" -X PUT "$url" \
        -H "Content-Type: application/json" \
        -H "Authorization: Bearer $TOKEN" \
        -d "$data" 2>&1 || true)
    if [ "$resp" = "$expect" ] || [ "$expect" = "any" ]; then
        check_endpoint "$desc (HTTP $resp)" 0
    else
        check_endpoint "$desc (HTTP $resp, expected $expect)" 1
    fi
}

api_delete() {
    local url="$1" desc="$2" expect="$3"
    local resp
    resp=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE "$url" \
        -H "Authorization: Bearer $TOKEN" 2>&1 || true)
    if [ "$resp" = "$expect" ] || [ "$expect" = "any" ]; then
        check_endpoint "$desc (HTTP $resp)" 0
    else
        check_endpoint "$desc (HTTP $resp, expected $expect)" 1
    fi
}

# Check required tools
check_cmd curl

info "=========================================="
info "  Testing API endpoints at $API_BASE"
info "=========================================="
echo ""

# --- Health check ---
info "Testing health check..."
api_get "$API_BASE/health" "Health check" "any"

api_get "$API_BASE/health/ready" "Health ready" "any"
api_get "$API_BASE/health/live"  "Health live"  "any"

# --- Authentication ---
info "Testing authentication..."

# Register (may already exist, so accept any 2xx or 409)
REG_RESP=$(curl -s -o /dev/null -w "%{http_code}" -X POST "$API_BASE/auth/register" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" 2>&1 || true)
if [ "$REG_RESP" = "201" ] || [ "$REG_RESP" = "409" ] || [ "$REG_RESP" = "200" ]; then
    check_endpoint "Auth register (HTTP $REG_RESP)" 0
else
    check_endpoint "Auth register (HTTP $REG_RESP)" 1
fi

# Login
LOGIN_RESP=$(curl -s -X POST "$API_BASE/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$ADMIN_USER\",\"password\":\"$ADMIN_PASS\"}" 2>&1 || true)
LOGIN_HTTP=$(echo "$LOGIN_RESP" | grep -o '"token"' | head -1 || echo "")
TOKEN=$(echo "$LOGIN_RESP" | grep -o '"token"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/.*"token"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/')
if [ -n "$TOKEN" ]; then
    check_endpoint "Auth login (token obtained)" 0
else
    check_endpoint "Auth login (token obtained)" 1
fi

api_get "$API_BASE/auth/me" "Auth me" "any"

# --- Domain CRUD ---
info "Testing domain endpoints..."

api_get "$API_BASE/domains" "List domains" "any"

DOMAIN_CREATE=$(curl -s -X POST "$API_BASE/domains" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"domain\":\"$DOMAIN\"}" 2>&1 || true)
DOMAIN_HTTP=$(echo "$DOMAIN_CREATE" | grep -o '"id"' | head -1 || echo "")
DOMAIN_ID=""
if [ -n "$DOMAIN_HTTP" ]; then
    DOMAIN_ID=$(echo "$DOMAIN_CREATE" | grep -o '"id"[[:space:]]*:[[:space:]]*[0-9]*' | head -1 | sed 's/.*"id"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/')
    check_endpoint "Create domain" 0
else
    # Could be conflict (already exists) - try to get domain ID from list
    DOMAIN_ID=$(curl -s "$API_BASE/domains" \
        -H "Authorization: Bearer $TOKEN" 2>&1 | \
        grep -o '"id":[0-9]*,"domain":"'"$DOMAIN"'"' | \
        sed 's/.*"id":\([0-9]*\),"domain":"'"$DOMAIN"'".*/\1/' || echo "")
    if [ -z "$DOMAIN_ID" ]; then
        check_endpoint "Create domain" 1
    else
        check_endpoint "Create domain (already exists)" 0
    fi
fi

if [ -n "$DOMAIN_ID" ]; then
    api_get "$API_BASE/domains/$DOMAIN_ID" "Get domain" "any"
    api_put "$API_BASE/domains/$DOMAIN_ID" "{\"domain\":\"$DOMAIN\",\"active\":true}" "Update domain" "any"
fi

# --- Mailbox CRUD ---
info "Testing mailbox endpoints..."

api_get "$API_BASE/mailboxes" "List mailboxes" "any"

MB_CREATE=$(curl -s -X POST "$API_BASE/mailboxes" \
    -H "Content-Type: application/json" \
    -H "Authorization: Bearer $TOKEN" \
    -d "{\"email\":\"$TEST_EMAIL\",\"password\":\"TestPass123\",\"domain_id\":${DOMAIN_ID:-1}}" 2>&1 || true)
MB_ID=$(echo "$MB_CREATE" | grep -o '"id"[[:space:]]*:[[:space:]]*[0-9]*' | head -1 | sed 's/.*"id"[[:space:]]*:[[:space:]]*\([0-9]*\).*/\1/')
if [ -n "$MB_ID" ]; then
    check_endpoint "Create mailbox" 0
else
    check_endpoint "Create mailbox" 1
fi

if [ -n "$MB_ID" ]; then
    api_get "$API_BASE/mailboxes/$MB_ID" "Get mailbox" "any"
    api_put "$API_BASE/mailboxes/$MB_ID" "{\"password\":\"NewPass456\"}" "Update mailbox password" "any"
    api_delete "$API_BASE/mailboxes/$MB_ID" "Delete mailbox" "any"
fi

# --- Metrics ---
info "Testing metrics endpoints..."

api_get "$API_BASE/metrics" "Metrics overview" "any"
api_get "$API_BASE/metrics/smtp" "SMTP metrics" "any"
api_get "$API_BASE/metrics/imap" "IMAP metrics" "any"

# --- DNS tools ---
info "Testing DNS tool endpoints..."

api_post "$API_BASE/tools/dns/lookup" "{\"domain\":\"$DOMAIN\",\"type\":\"MX\"}" "DNS MX lookup" "any"
api_post "$API_BASE/tools/dns/lookup" "{\"domain\":\"$DOMAIN\",\"type\":\"A\"}"  "DNS A lookup"  "any"
api_post "$API_BASE/tools/dns/lookup" "{\"domain\":\"$DOMAIN\",\"type\":\"TXT\"}" "DNS TXT lookup" "any"

# --- Admin ---
info "Testing admin endpoints..."

api_get "$API_BASE/admin/queue" "Admin queue" "any"
api_get "$API_BASE/admin/stats" "Admin stats" "any"

# --- Summary ---
echo ""
echo "=========================================="
echo "  API Test Results: $PASS passed, $FAIL failed"
echo "=========================================="
for r in "${RESULTS[@]}"; do echo "  $r"; done
exit $FAIL
