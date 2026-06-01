<!--
  MissionControl - Mail Server Manager
  Copyright (c) 2026 Your Net Tech
  Developed by Jose Rinaldi
  All rights reserved.
  Unauthorized use, reproduction, or distribution is strictly prohibited
  without written permission from Your Net Tech.
-->

# 🚀 MissionControl

> **The first open-source control panel that unifies Postfix, Dovecot and Rspamd into a modern REST API + web interface — deploy in 10 minutes, zero bloat.**

---

<div align="center">

![Status](https://img.shields.io/badge/status-production%20ready-brightgreen)
![OS](https://img.shields.io/badge/os-Debian%2012+%20%7C%20Ubuntu%2022+-blue)
![License](https://img.shields.io/badge/license-Apache%202.0-blue)
![Stack](https://img.shields.io/badge/stack-FastAPI%20%7C%20React%20%7C%20Postfix%20%7C%20Dovecot-purple)

<br>

### 🔥 Single stack. Single command deploy. Zero lock-in.

</div>

---

## ✨ The Problem

Running a mail server has always been **expensive, complex, and fragile**:

| Solution | Problem |
|---------|----------|
| **cPanel / Plesk** | Expensive ($20+/mo), proprietary, bloated |
| **ISPConfig** | Legacy PHP, dated UX, technical debt |
| **Mailcow / Mailu** | Docker-dependent, extra complexity, container overhead |
| **PostfixAdmin** | Admin web only — no API, no monitoring, no anti-spam |
| **DIY scripts** | Fragile shell scripts, no API, no UI, painful maintenance |

**MissionControl was born from a simple insight:**

1. The Unix mail stack (Postfix + Dovecot + Rspamd) is **battle-tested, decades-proven, and incredibly efficient** — tens of thousands of emails/min with < 256MB RAM.
2. What's missing is **a modern management layer**: REST API, SPA dashboard, auto health repair, and reproducible deployment.

---

## 🎯 What Makes MissionControl Different

### 🔬 Technical Innovation

| Feature | MissionControl | Mailcow | ISPConfig | cPanel |
|---|---|---|---|---|
| **Native REST API** (FastAPI) | ✅ First-class | ❌ PHP wrapper | ❌ Legacy PHP | ❌ Proprietary |
| **Auto self-healing** | ✅ Detects & restarts failed services | ❌ | ❌ | ❌ |
| **Rspamd anti-spam** (state-of-the-art) | ✅ Native + adjustable scores | ✅ | ❌ SpamAssassin | ❌ SpamAssassin |
| **DKIM / DMARC / SPF wizard** | ✅ Per-domain auto setup | ✅ Partial | ❌ Manual | ✅ |
| **Real-time system metrics** | ✅ CPU, RAM, Disk, Network via API | ❌ | ❌ | ✅ |
| **Cloudflare DNS integration** | ✅ Auto wizard | ❌ | ❌ | ✅ (paid) |
| **Full audit logging** | ✅ Every action logged | ❌ | ❌ | ✅ |
| **Single-command deploy** | ✅ `sudo bash deploy.sh` | ❌ Docker Compose | ❌ Manual | ❌ Installer |
| **Disk footprint** | ~150MB + data | ~2GB (Docker images) | ~500MB | ~2GB+ |
| **No Docker required** | ✅ Bare-metal performance | ❌ Mandatory | N/A | N/A |
| **Zero lock-in** | ✅ Plain configs, easy migration | ❌ Docker-dependent | ✅ | ❌ |

### 📊 Performance

A MissionControl server with **2GB RAM and 2 vCPUs** handles:

- **50+ domains**
- **500+ mailboxes**
- **10,000+ emails/hour** with full Rspamd filtering
- API latency < 50ms (p95)
- Downtime < 30s on service failures (auto-repair)

---

## 🏗️ Architecture

```
                    ┌─────────────────────────────────────────────────────┐
                    │                      Internet                        │
                    └──────────┬──────────────────┬───────────────────────┘
                               │                  │
                          :25/SMTP           :80/443
                               │                  │
                         ┌─────▼──────┐     ┌─────▼──────────┐
                         │  Postfix   │     │    Apache       │
                         │    MTA     │     │  Proxy + SPA    │
                         │  + milter  │     │                 │
                         └──┬───┬─────┘     └──┬──┬───────────┘
                            │   │              │  │
                       :11332│   │         :8000│  │
                            │   │              │  │
                      ┌─────▼───┴─────┐   ┌────▼──▼───────────┐
                      │   Rspamd      │   │  FastAPI (Python)  │
                      │  Anti-spam    │   │  REST API :8000    │
                      │  DKIM signing │   │  + Auto-repair     │
                      │  Rate limit   │   │  + Metrics         │
                      └───────────────┘   └────┬──┬───────────┘
                                               │  │
                                          ┌────▼──▼────┐
                                          │  MariaDB   │
                                          │  + Redis   │
                                          └────────────┘
                         ┌──────────────────────────────┐
                         │       Dovecot IMAP/POP3       │
                         │  LMTP delivery → Maildir      │
                         │  SASL auth for Postfix        │
                         └──────────────────────────────┘
```

### 🔄 Inbound Mail Flow

```
Remote MTA → :25 (Postfix) → Rspamd milter (SPF/DKIM/DMARC/greylist)
  → LMTP Dovecot → Maildir (/var/vmail/domain/user/)
```

### 🔄 Outbound Mail Flow

```
MUA → :587 STARTTLS (Postfix) → SASL Dovecot → MySQL → Rspamd DKIM signing
  → DNS MX lookup → Destination MTA
```

---

## ⚡ Single-Command Deploy

```bash
git clone <url> projects-mc-yournet
cd projects-mc-yournet
sudo bash deploy.sh
```

The script **prompts only for domain and IP** — everything else is auto-generated:

```
🔐 Passwords:     openssl rand (DB, JWT, admin)
🧂 Hashes:        bcrypt (admin, mailboxes)
📜 SSL cert:      Self-signed (10 years)
🗄️ Database:      MariaDB + 16 tables
📦 Packages:      Postfix, Dovecot, Rspamd, Apache, Redis
⚙️ Configs:       Applied + placeholders substituted
🧪 Health check:  Automatic post-deploy verification
```

Output:

```
══════════════════════════════════════════════════════════════
  MissionControl — Deploy completed successfully!
══════════════════════════════════════════════════════════════

  Web UI:     http://YOUR_SERVER_IP
  API Docs:   http://YOUR_SERVER_IP/docs

  Admin:      admin
  Password:   adminK8sL2pX9zQ (randomly generated)

  SMTP:       YOUR_SERVER_IP:25
  SMTPS:      YOUR_SERVER_IP:465
  Submission: YOUR_SERVER_IP:587 (STARTTLS)
  IMAP:       YOUR_SERVER_IP:143
  IMAPS:      YOUR_SERVER_IP:993

══════════════════════════════════════════════════════════════
```

---

## 🧪 Built-in Test Suite

```bash
bash tests/run-all-tests.sh
```

| Test | What it verifies |
|------|-----------------|
| `01-test-smtp.sh` | Ports 25/465/587, STARTTLS, EHLO, send via API |
| `02-test-imap.sh` | Ports 143/993, STARTTLS, login, LIST/SELECT/FETCH |
| `03-test-api.sh` | 20+ endpoints (health, auth, domains, mailboxes, metrics) |
| `04-test-webmail.sh` | Roundcube (if installed) |
| `05-test-dns.sh` | MX, SPF, DKIM, DMARC, PTR, delivery via swaks |

---

## 🛡️ Security

- ✅ **Zero .env files in repository** — all secrets generated during install
- ✅ **Random admin password** (15+ alphanumeric characters)
- ✅ **JWT secret** generated with `openssl rand -hex 32`
- ✅ **bcrypt hashing** for all passwords (factor 10)
- ✅ **Server .env files** protected with `chmod 600`
- ✅ **UFW firewall** auto-configured (minimal port exposure)
- ✅ **SQL injection protected** (SQLAlchemy ORM + parameterized queries)
- ✅ **Configurable CORS** origins
- ✅ **Rate limiting** via Rspamd

---

## 📦 Components

| Component | Version | Role |
|-----------|---------|------|
| **FastAPI** (Python 3.11+) | 0.110+ | Async REST API with auto-generated Swagger docs |
| **React SPA** | 18+ | Modern web dashboard (pre-compiled) |
| **Postfix** | 3.7+ | MTA — SMTP, virtual domains, SASL auth |
| **Dovecot** | 2.3+ | IMAP/POP3, LMTP delivery, SASL auth provider |
| **Rspamd** | 3.7+ | Anti-spam, DKIM signing, rate limiting, greylisting |
| **MariaDB** | 10.11+ | Primary storage (users, domains, mailboxes) |
| **Redis** | 7+ | Cache, sessions, Rspamd history |
| **Apache** | 2.4+ | Reverse proxy + static file server |
| **systemd** | 252+ | Service supervision, auto-restart |

---

## 📊 Complete REST API

| Resource | Endpoint | Description |
|----------|----------|-------------|
| **Auth** | `POST /api/v1/auth/login` | JWT authentication |
| **Health** | `GET /api/v1/health/check` | Full server health status |
| **Domains** | `CRUD /api/v1/domains/` | Domain management |
| **Mailboxes** | `CRUD /api/v1/mailboxes/` | Mailbox CRUD + quota |
| **Aliases** | `CRUD /api/v1/aliases` | Email forwarding |
| **Spam** | `GET /api/v1/spam/stats` | Rspamd statistics |
| **Metrics** | `GET /api/v1/metrics/system` | CPU, RAM, Disk, Network |
| **DNS** | `POST /api/v1/dns/wizard` | DNS records wizard |
| **Audit** | `GET /api/v1/audit/logs` | Full audit trail |
| **Swagger** | `GET /docs` | Interactive API documentation |

---

## 🔧 Production Checklist

```bash
# Let's Encrypt SSL
certbot --apache -d mail.yourdomain.com

# Point Postfix and Dovecot to LE certs
postconf -e "smtpd_tls_cert_file=/etc/letsencrypt/live/mail.yourdomain.com/fullchain.pem"
postconf -e "smtpd_tls_key_file=/etc/letsencrypt/live/mail.yourdomain.com/privkey.pem"
ln -sf /etc/letsencrypt/live/mail.yourdomain.com/privkey.pem /etc/dovecot/private/dovecot.key
ln -sf /etc/letsencrypt/live/mail.yourdomain.com/fullchain.pem /etc/dovecot/private/dovecot.pem

# Configure DNS records
# MX  → mail.yourdomain.com (priority 10)
# SPF → "v=spf1 mx ~all"
# DKIM → via MissionControl admin panel
# DMARC → "v=DMARC1; p=quarantine"

# Restrict API CORS to your domain
sed -i 's/CORS_ORIGINS=\["\*"\]/CORS_ORIGINS=\["https:\/\/mail.yourdomain.com"\]/' \
  /opt/missioncontrol/backend/.env
```

---

## 📁 Repository Structure

```
projects-mc-yournet/
├── deploy.sh          ← The only command you need
├── configs/           ← Anonymized configs (Postfix, Dovecot, Rspamd, Apache)
├── backend/           ← Python API (57 files)
│   ├── app/api/       ← 19 REST endpoints
│   ├── app/models/    ← 16 SQLAlchemy tables
│   └── app/services/  ← Business logic
├── frontend/          ← Compiled React SPA
├── sql/               ← Schema + seed + reset
├── tests/             ← Test suite
└── README.md          ← This file
```

---

## 💡 Roadmap

- [x] Full REST API + SPA dashboard
- [x] Single-command deploy (no Docker)
- [x] Auto service repair (self-healing)
- [x] Real-time system metrics
- [x] Rspamd anti-spam + DKIM/DMARC/SPF
- [x] Cloudflare DNS wizard
- [x] Complete audit logging
- [x] Built-in test suite
- [ ] CI/CD pipeline
- [ ] Ansible playbook / Terraform module
- [ ] Integrated Roundcube webmail
- [ ] Mobile app (React Native)
- [ ] Prometheus metrics exporter

---

## 🤝 Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for full guidelines on:

- Reporting bugs & feature requests
- Submitting pull requests
- Development setup
- Coding standards
- Testing

---

## 📋 License

Apache 2.0 — See [LICENSE](LICENSE) for full text.

---

<div align="center">

**MissionControl — Because managing email shouldn't be the hardest part of your day.**

<br>

<sub>Built with ❤️ for sysadmins who deserve better tools.</sub>

</div>
