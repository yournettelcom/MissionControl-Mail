#!/bin/bash
# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================


set -euo pipefail

# Single-command deploy for Debian 12+ / Ubuntu 22+
# Usage: sudo bash deploy.sh
# All secrets are auto-generated during install (never shipped in repo).

# ---- Colors ----
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'
BOLD='\033[1m'; NC='\033[0m'
ok()  { echo -e "  ${GREEN}✓${NC} $1"; }
fail(){ echo -e "  ${RED}✗${NC} $1"; }
info(){ echo -e "  ${YELLOW}ℹ${NC} $1"; }
step(){ echo -e "\n${CYAN}━━━ $1 ━━━${NC}"; }

# ---- Root check ----
if [[ $EUID -ne 0 ]]; then fail "Run with sudo: sudo bash deploy.sh"; exit 1; fi

# ---- Variables (auto-detected or prompted) ----
HOSTNAME=$(hostname -f 2>/dev/null || hostname)
DOMAIN="${MC_DOMAIN:-}"
IP="${MC_IP:-}"

if [[ -z "$DOMAIN" ]]; then
  read -rp "Server domain (e.g. mail.example.com) [$HOSTNAME]: " input
  DOMAIN="${input:-$HOSTNAME}"
fi
if [[ -z "$IP" ]]; then
  IP=$(curl -s ifconfig.me 2>/dev/null || ip route get 1 | awk '{print $7; exit}')
  read -rp "Public server IP [$IP]: " input
  IP="${input:-$IP}"
fi

# ---- Generated secrets ----
DB_PASS=$(openssl rand -base64 24)
SECRET_KEY=$(openssl rand -hex 32)
ADMIN_PASS="admin$(openssl rand -base64 12 | tr -dc a-zA-Z0-9)"
# Generate bcrypt hash for Dovecot/Postfix admin password
ADMIN_HASH=$(python3 -c "
import bcrypt; h=bcrypt.hashpw(b'$ADMIN_PASS', bcrypt.gensalt(rounds=10)); print(h.decode())
" 2>/dev/null || echo "\$2b\$10\$PLACEHOLDER_HASH_REGENERATE_ON_FIRST_LOGIN")

REPO_DIR="$(cd "$(dirname "$0")" && pwd)"
echo ""
echo -e "${BOLD}MissionControl - Automatic Deploy${NC}"
echo "  Domain: $DOMAIN"
echo "  IP: $IP"
echo ""
echo -e "  ${YELLOW}Admin password: $ADMIN_PASS${NC}"
echo -e "  ${YELLOW}Save this password — it will not be shown again.${NC}"
echo ""

# ============================================================================
step "1/10 — Installing system dependencies"
# ============================================================================
export DEBIAN_FRONTEND=noninteractive

if grep -qi ubuntu /etc/os-release 2>/dev/null; then
  apt-get update -qq
  apt-get install -y -qq software-properties-common
elif grep -qi debian /etc/os-release 2>/dev/null; then
  apt-get update -qq
fi

apt-get install -y -qq \
  postfix postfix-mysql \
  dovecot-core dovecot-imapd dovecot-mysql dovecot-lmtpd \
  mariadb-server \
  apache2 \
  rspamd redis-server \
  python3 python3-venv python3-pip python3-dev \
  build-essential git curl wget openssl ssl-cert \
  certbot python3-certbot-apache \
  ufw dnsutils netcat-openbsd \
  rsyslog

ok "Dependencies installed"

# ============================================================================
step "2/10 — Configuring firewall (UFW)"
# ============================================================================
ufw --force reset >/dev/null 2>&1
ufw default deny incoming >/dev/null
ufw default allow outgoing >/dev/null
for port in 22 25 80 443 143 465 587 993 995; do
  ufw allow "$port/tcp" >/dev/null 2>&1
done
ufw --force enable >/dev/null 2>&1
ok "Firewall configured (ports 22,25,80,443,143,465,587,993)"

# ============================================================================
step "3/10 — Configuring database"
# ============================================================================
systemctl enable mariadb --quiet 2>/dev/null || true
systemctl start mariadb 2>/dev/null || true

mysql -u root <<SQL
CREATE DATABASE IF NOT EXISTS missioncontrol CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS 'missioncontrol'@'127.0.0.1' IDENTIFIED BY '$DB_PASS';
CREATE USER IF NOT EXISTS 'missioncontrol'@'localhost' IDENTIFIED BY '$DB_PASS';
GRANT ALL PRIVILEGES ON missioncontrol.* TO 'missioncontrol'@'127.0.0.1';
GRANT ALL PRIVILEGES ON missioncontrol.* TO 'missioncontrol'@'localhost';
FLUSH PRIVILEGES;
SQL
ok "Database 'missioncontrol' created"

if [[ -f "$REPO_DIR/sql/01-schema.sql" ]]; then
  mysql -u root missioncontrol < "$REPO_DIR/sql/01-schema.sql"
  ok "Tables created"
fi
if [[ -f "$REPO_DIR/sql/02-seed.sql" ]]; then
  # Replace placeholder password hash with real one
  sed "s|ADMIN_PASSWORD_HASH|$ADMIN_HASH|g" "$REPO_DIR/sql/02-seed.sql" | \
    mysql -u root missioncontrol 2>/dev/null || true
  ok "Seed data inserted"
fi

# ============================================================================
step "4/10 — Configuring Postfix"
# ============================================================================
systemctl stop postfix 2>/dev/null || true

# Copy configs
cp "$REPO_DIR/configs/postfix/main.cf" /etc/postfix/main.cf
cp "$REPO_DIR/configs/postfix/master.cf" /etc/postfix/master.cf

# Replace placeholders
sed -i "s/mail\.example\.com/$DOMAIN/g" /etc/postfix/main.cf
sed -i "s/PLACEHOLDER_SERVER_IP/$IP/g" /etc/postfix/main.cf
sed -i "s/PLACEHOLDER_NETWORK/${IP%.*}.0\/24/g" /etc/postfix/main.cf

# Virtual domains
touch /etc/postfix/virtual_domains /etc/postfix/virtual
postmap /etc/postfix/virtual_domains 2>/dev/null || true
postmap /etc/postfix/virtual 2>/dev/null || true

# SASL auth socket directory
mkdir -p /var/spool/postfix/private
chown postfix:postfix /var/spool/postfix/private

# TLS self-signed cert
mkdir -p /etc/postfix
cp /etc/ssl/certs/ssl-cert-snakeoil.pem /etc/postfix/ 2>/dev/null || true
cp /etc/ssl/private/ssl-cert-snakeoil.key /etc/postfix/ 2>/dev/null || true

# Chroot TLS
mkdir -p /var/spool/postfix/etc/ssl/certs /var/spool/postfix/etc/postfix
cp /etc/ssl/certs/ssl-cert-snakeoil.pem /var/spool/postfix/etc/ssl/certs/ 2>/dev/null || true
cp /etc/ssl/private/ssl-cert-snakeoil.key /var/spool/postfix/etc/postfix/ 2>/dev/null || true
chown root:postfix /var/spool/postfix/etc/postfix/ssl-cert-snakeoil.key 2>/dev/null || true

systemctl enable postfix --quiet 2>/dev/null || true
systemctl start postfix
ok "Postfix configured"

# ============================================================================
step "5/10 — Configuring Dovecot"
# ============================================================================
systemctl stop dovecot 2>/dev/null || true

# Create vmail user
id -u vmail &>/dev/null || useradd -r -u 5000 -g mail -d /var/vmail -s /sbin/nologin vmail
mkdir -p /var/vmail
chown vmail:mail /var/vmail
chmod 755 /var/vmail

# Copy configs
cp -r "$REPO_DIR/configs/dovecot/"* /etc/dovecot/ 2>/dev/null || true
if [[ -d "$REPO_DIR/configs/dovecot/conf.d" ]]; then
  mkdir -p /etc/dovecot/conf.d
  cp "$REPO_DIR/configs/dovecot/conf.d/"* /etc/dovecot/conf.d/ 2>/dev/null || true
fi

# Replace placeholders in dovecot SQL config
for f in /etc/dovecot/dovecot-sql.conf.ext /etc/dovecot/dovecot-dict-sql.conf.ext; do
  [[ -f "$f" ]] && sed -i "s/CHANGEME_DB_PASSWORD/$DB_PASS/g" "$f" 2>/dev/null || true
done

# Self-signed SSL cert for Dovecot
mkdir -p /etc/dovecot/private
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/dovecot/private/dovecot.key \
  -out /etc/dovecot/private/dovecot.pem \
  -subj "/C=BR/ST=State/L=City/O=MissionControl/OU=Email/CN=$DOMAIN" 2>/dev/null
chmod 600 /etc/dovecot/private/dovecot.key
chmod 644 /etc/dovecot/private/dovecot.pem

# Maildir format
sed -i "s|mail_location = .*|mail_location = maildir:/var/vmail/%d/%n|g" \
  /etc/dovecot/dovecot.conf /etc/dovecot/conf.d/10-mail.conf 2>/dev/null || true

systemctl enable dovecot --quiet 2>/dev/null || true
systemctl start dovecot
ok "Dovecot configured"

# ============================================================================
step "6/10 — Configuring Apache"
# ============================================================================
a2enmod proxy proxy_http rewrite headers ssl 2>/dev/null || true

if [[ -f "$REPO_DIR/configs/apache/missioncontrol.conf" ]]; then
  cp "$REPO_DIR/configs/apache/missioncontrol.conf" /etc/apache2/sites-available/missioncontrol.conf
  sed -i "s/mail\.example\.com/$DOMAIN/g" /etc/apache2/sites-available/missioncontrol.conf
fi

a2dissite 000-default 2>/dev/null || true
a2ensite missioncontrol 2>/dev/null || true
systemctl enable apache2 --quiet 2>/dev/null || true
systemctl restart apache2
ok "Apache configured"

# ============================================================================
step "7/10 — Configuring Rspamd"
# ============================================================================
if [[ -d "$REPO_DIR/configs/rspamd" ]]; then
  cp -r "$REPO_DIR/configs/rspamd/"* /etc/rspamd/ 2>/dev/null || true
fi
systemctl enable rspamd --quiet 2>/dev/null || true
systemctl restart rspamd 2>/dev/null || true
ok "Rspamd configured"

# ============================================================================
step "8/10 — Configuring Python backend"
# ============================================================================
mkdir -p /opt/missioncontrol/backend
cp -r "$REPO_DIR/backend/"* /opt/missioncontrol/backend/ 2>/dev/null || true

python3 -m venv /opt/missioncontrol/backend/venv
source /opt/missioncontrol/backend/venv/bin/activate
pip install -q -U pip wheel setuptools
pip install -q -r /opt/missioncontrol/backend/requirements.txt
deactivate

# Create .env (only on server, never in repo)
cat > /opt/missioncontrol/backend/.env <<EOF
DATABASE_URL=mysql+aiomysql://missioncontrol:$DB_PASS@127.0.0.1:3306/missioncontrol
SECRET_KEY=$SECRET_KEY
ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=60
REFRESH_TOKEN_EXPIRE_DAYS=7
REDIS_URL=redis://localhost:6379/0
POSTFIX_CONFIG_DIR=/etc/postfix
DOVECOT_CONFIG_DIR=/etc/dovecot
VMAIL_DIR=/var/vmail
API_TITLE=MissionControl API
API_VERSION=1.0.0
CORS_ORIGINS=["*"]
EOF

chmod 600 /opt/missioncontrol/backend/.env

# Systemd service
cat > /etc/systemd/system/missioncontrol.service <<UNIT
[Unit]
Description=MissionControl - Mail Server Manager API
After=network.target mariadb.service postfix.service dovecot.service
Wants=mariadb.service

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=/opt/missioncontrol/backend
Environment="PYTHONPATH=/opt/missioncontrol/backend"
ExecStart=/opt/missioncontrol/backend/venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8000 --workers 1 --log-level info
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable missioncontrol --quiet 2>/dev/null || true
systemctl start missioncontrol
ok "Backend installed and running"

# ============================================================================
step "9/10 — Installing frontend"
# ============================================================================
mkdir -p /opt/missioncontrol/frontend
cp -r "$REPO_DIR/frontend/"* /opt/missioncontrol/frontend/ 2>/dev/null || true
chmod -R 755 /opt/missioncontrol/frontend
ok "Frontend copied"

# ============================================================================
step "10/10 — Verifying system health"
# ============================================================================
echo ""
echo -e "${BOLD}Waiting for backend to start...${NC}"
for i in $(seq 1 15); do
  sleep 2
  if curl -sf http://127.0.0.1:8000/api/v1/health/check >/dev/null 2>&1; then
    ok "Backend is responding"
    break
  fi
  if [[ $i -eq 15 ]]; then
    fail "Backend did not start after 30s"
  fi
done

# ============================================================================
# Summary
# ============================================================================
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo -e "${BOLD}${GREEN}  MissionControl — Deploy completed successfully!${NC}"
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "  ${CYAN}Access:${NC}"
echo -e "  Web UI:     ${BOLD}http://$IP${NC}"
echo -e "  API Docs:   ${BOLD}http://$IP/docs${NC}"
echo ""
echo -e "  ${CYAN}Credentials:${NC}"
echo -e "  Admin:      ${BOLD}admin${NC}"
echo -e "  Password:   ${BOLD}${YELLOW}$ADMIN_PASS${NC}"
echo -e "  (Change after first login)"
echo ""
echo -e "  ${CYAN}Email Services:${NC}"
echo -e "  SMTP:       $IP:25 / SMTPS: $IP:465"
echo -e "  Submission: $IP:587 (STARTTLS)"
echo -e "  IMAP:       $IP:143 / IMAPS: $IP:993"
echo ""
echo -e "  ${CYAN}Configured domain:${NC}  $DOMAIN"
echo -e "  ${CYAN}Database:${NC}          missioncontrol@127.0.0.1"
echo ""
echo -e "  ${YELLOW}⚠  Save the admin password above!${NC}"
echo -e "  ${YELLOW}⚠  Configure DNS: MX → $DOMAIN, SPF, DKIM, DMARC${NC}"
echo -e "  ${YELLOW}⚠  For production: certbot --apache -d $DOMAIN${NC}"
echo ""
echo -e "${BOLD}${GREEN}══════════════════════════════════════════════════════════════${NC}"
echo ""
echo -e "Tests: cd $(dirname "$REPO_DIR")/tests && bash run-all-tests.sh"
echo ""

# Generate test config with the real credentials
cat > /tmp/mc-test-config.sh <<EOF
SERVER_IP="$IP"
DOMAIN="$DOMAIN"
ADMIN_USER="admin"
ADMIN_PASS="$ADMIN_PASS"
API_BASE="http://$IP/api/v1"
EOF

echo -e "  ${GREEN}Test config saved to: /tmp/mc-test-config.sh${NC}"
echo ""
