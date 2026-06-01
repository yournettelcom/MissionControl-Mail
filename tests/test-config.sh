#!/usr/bin/env bash
# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================


# Test configuration - sourced by all test scripts
# Override by setting env vars before running tests

SERVER_IP="${SERVER_IP:-127.0.0.1}"
DOMAIN="${DOMAIN:-example.com}"
ADMIN_USER="${ADMIN_USER:-admin@example.com}"
ADMIN_PASS="${ADMIN_PASS:-CHANGEME_PASSWORD}"
TEST_EMAIL="${TEST_EMAIL:-test@example.com}"
API_BASE="${API_BASE:-http://127.0.0.1/api/v1}"

# Derived
IMAP_PORT=143
IMAPS_PORT=993
SMTP_PORT=25
SMTPS_PORT=465
SUBMISSION_PORT=587
WEBMAIL_URL="${WEBMAIL_URL:-https://webmail.${DOMAIN}}"

# Color output
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

pass() { echo -e "${GREEN}[PASS]${NC} $1"; }
fail() { echo -e "${RED}[FAIL]${NC} $1"; }
info() { echo -e "${YELLOW}[INFO]${NC} $1"; }
die() { fail "$1"; exit 1; }

check_cmd() {
    if ! command -v "$1" &>/dev/null; then
        die "Required command not found: $1"
    fi
}
