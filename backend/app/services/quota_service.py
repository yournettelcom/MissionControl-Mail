# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import json
import logging
import os
import re
import sqlite3
import smtplib
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any, Optional

from .dovecot_service import DovecotService
from .postfix_service import PostfixService
from .system_service import SystemService

logger = logging.getLogger(__name__)

DB_PATH = "/etc/missioncontrol/missioncontrol.db"
AUDIT_LOG = "/var/log/missioncontrol/quota_audit.log"


class QuotaService:
    def __init__(self):
        self.dovecot = DovecotService()
        self.postfix = PostfixService()
        self.system = SystemService()
        self._ensure_db()

    def _ensure_db(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quota_templates (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    mailbox_limit_mb INTEGER NOT NULL DEFAULT 1024,
                    domain_limit_mb INTEGER DEFAULT 0,
                    warn_percent INTEGER DEFAULT 80,
                    critical_percent INTEGER DEFAULT 95,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS domain_quota (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain_id INTEGER UNIQUE NOT NULL,
                    template_id INTEGER,
                    custom_limit_mb INTEGER DEFAULT 0,
                    FOREIGN KEY (domain_id) REFERENCES domains(id),
                    FOREIGN KEY (template_id) REFERENCES quota_templates(id)
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS quota_audit (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    mailbox_id INTEGER,
                    email TEXT,
                    current_bytes INTEGER,
                    limit_bytes INTEGER,
                    percent REAL,
                    recorded_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()

            cursor = conn.execute("SELECT COUNT(*) FROM quota_templates")
            if cursor.fetchone()[0] == 0:
                templates = [
                    ("Bronze", 512, 5120, 80, 95),
                    ("Silver", 1024, 10240, 80, 95),
                    ("Gold", 2048, 20480, 85, 95),
                    ("Platinum", 5120, 51200, 90, 98),
                    ("Custom", 1024, 0, 80, 95),
                ]
                for name, mb_limit, domain_limit, warn, crit in templates:
                    conn.execute(
                        "INSERT OR IGNORE INTO quota_templates (name, mailbox_limit_mb, domain_limit_mb, warn_percent, critical_percent) VALUES (?, ?, ?, ?, ?)",
                        (name, mb_limit, domain_limit, warn, crit),
                    )
                conn.commit()
        finally:
            conn.close()

    async def _run_bash(self, cmd: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    def _log_audit(self, mailbox_id: int | None, email: str, current_bytes: int, limit_bytes: int, percent: float):
        os.makedirs(os.path.dirname(AUDIT_LOG), exist_ok=True)
        try:
            with open(AUDIT_LOG, "a") as f:
                f.write(
                    f"{datetime.utcnow().isoformat()} | {mailbox_id or 'N/A'} | {email} | "
                    f"{current_bytes} | {limit_bytes} | {percent:.1f}%\n"
                )
            conn = sqlite3.connect(DB_PATH)
            try:
                conn.execute(
                    "INSERT INTO quota_audit (mailbox_id, email, current_bytes, limit_bytes, percent) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (mailbox_id, email, current_bytes, limit_bytes, percent),
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as e:
            logger.error("Error logging quota audit: %s", e)

    async def apply_template(self, domain_id: int, template_id: int) -> bool:
        try:
            conn = sqlite3.connect(DB_PATH)
            try:
                cursor = conn.execute(
                    "SELECT mailbox_limit_mb, domain_limit_mb FROM quota_templates WHERE id=?",
                    (template_id,),
                )
                template = cursor.fetchone()
                if not template:
                    logger.error("Template %d not found", template_id)
                    return False

                mailbox_limit_mb, domain_limit_mb = template

                conn.execute(
                    "INSERT OR REPLACE INTO domain_quota (domain_id, template_id, custom_limit_mb) "
                    "VALUES (?, ?, ?)",
                    (domain_id, template_id, 0),
                )

                cursor = conn.execute(
                    "SELECT id, email FROM mailboxes WHERE domain_id=?",
                    (domain_id,),
                )
                mailboxes = cursor.fetchall()

                limit_bytes = mailbox_limit_mb * 1024 * 1024
                for mb_id, email in mailboxes:
                    conn.execute(
                        "UPDATE mailboxes SET quota_limit=? WHERE id=?",
                        (limit_bytes, mb_id),
                    )

                    user_part = email.split("@")[0]
                    rc, out, err = await self._run_bash(
                        f'doveadm quota set -u "{email}" "User quota" {limit_bytes} 2>/dev/null'
                    )
                    if rc != 0:
                        logger.warning("Failed to set quota for %s: %s", email, err)

                conn.commit()
                return True
            finally:
                conn.close()
        except Exception as e:
            logger.error("Error applying quota template: %s", e)
            return False

    async def check_quotas(self) -> list:
        warnings: list[dict] = []
        try:
            conn = sqlite3.connect(DB_PATH)
            try:
                cursor = conn.execute(
                    "SELECT m.id, m.email, m.quota_limit, m.domain_id, "
                    "COALESCE(dq.custom_limit_mb, t.mailbox_limit_mb, 0) as effective_limit_mb, "
                    "COALESCE(t.warn_percent, 80) as warn_pct, "
                    "COALESCE(t.critical_percent, 95) as critical_pct "
                    "FROM mailboxes m "
                    "LEFT JOIN domain_quota dq ON m.domain_id = dq.domain_id "
                    "LEFT JOIN quota_templates t ON dq.template_id = t.id "
                    "WHERE m.status = 'active'"
                )
                mailboxes = cursor.fetchall()
            finally:
                conn.close()

            for row in mailboxes:
                mb_id, email, quota_limit, domain_id, limit_mb, warn_pct, critical_pct = row
                if limit_mb:
                    quota_limit = limit_mb * 1024 * 1024

                quota = await self.dovecot.get_quota_usage(email)
                current = quota.get("current", 0)
                limit = quota.get("limit", 0) or quota_limit or (1024 * 1024 * 1024)
                percent = (current / limit * 100) if limit > 0 else 0

                self._log_audit(mb_id, email, current, limit, percent)

                if percent >= critical_pct:
                    level = "critical"
                elif percent >= warn_pct:
                    level = "warning"
                else:
                    continue

                warnings.append({
                    "mailbox_id": mb_id,
                    "email": email,
                    "domain_id": domain_id,
                    "current_bytes": current,
                    "limit_bytes": limit,
                    "percent": round(percent, 1),
                    "level": level,
                    "current_human": self._bytes_to_human(current),
                    "limit_human": self._bytes_to_human(limit),
                })

        except Exception as e:
            logger.error("Error checking quotas: %s", e)
        return warnings

    async def get_usage_summary(self) -> dict:
        summary: dict[str, Any] = {
            "domains_count": 0,
            "mailboxes_count": 0,
            "total_allocated_gb": 0,
            "total_used_gb": 0,
            "percent_used": 0,
        }
        try:
            conn = sqlite3.connect(DB_PATH)
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM domains WHERE status='active'")
                summary["domains_count"] = cursor.fetchone()[0] or 0

                cursor = conn.execute("SELECT COUNT(*) FROM mailboxes WHERE status='active'")
                summary["mailboxes_count"] = cursor.fetchone()[0] or 0

                cursor = conn.execute(
                    "SELECT SUM(quota_limit) FROM mailboxes WHERE status='active'"
                )
                total_alloc = cursor.fetchone()[0] or 0
                summary["total_allocated_gb"] = round(total_alloc / (1024**3), 2)
            finally:
                conn.close()

            vmail_base = "/var/vmail"
            total_used = 0
            if os.path.exists(vmail_base):
                for item in os.listdir(vmail_base):
                    item_path = os.path.join(vmail_base, item)
                    if os.path.isdir(item_path):
                        for root, dirs, files in os.walk(item_path):
                            for f in files:
                                try:
                                    total_used += os.path.getsize(
                                        os.path.join(root, f)
                                    )
                                except OSError:
                                    pass

            summary["total_used_gb"] = round(total_used / (1024**3), 2)
            if summary["total_allocated_gb"] > 0:
                summary["percent_used"] = round(
                    (total_used / (summary["total_allocated_gb"] * (1024**3))) * 100, 1
                )

        except Exception as e:
            logger.error("Error getting usage summary: %s", e)
        return summary

    async def notify_quota_warnings(self) -> list:
        notifications: list[dict] = []
        try:
            warnings = await self.check_quotas()
            for warning in warnings:
                if warning["level"] not in ("warning", "critical"):
                    continue

                subject = (
                    f"URGENT: Mailbox quota critical - {warning['email']}"
                    if warning["level"] == "critical"
                    else f"Warning: Mailbox quota at {warning['percent']}% - {warning['email']}"
                )

                body = (
                    f"Hello,\n\n"
                    f"Your mailbox {warning['email']} is using "
                    f"{warning['current_human']} of {warning['limit_human']} "
                    f"({warning['percent']}%).\n\n"
                )
                if warning["level"] == "critical":
                    body += (
                        "This mailbox has exceeded the critical threshold. "
                        "Please delete unnecessary emails or upgrade your quota immediately "
                        "to avoid service interruption.\n\n"
                    )
                else:
                    body += (
                        "Please consider cleaning up your mailbox or requesting a quota "
                        "increase to avoid service interruption.\n\n"
                    )
                body += f"Regards,\nMissionControl Mail System"

                try:
                    msg = MIMEText(body)
                    msg["Subject"] = subject
                    msg["From"] = "postmaster@localhost"
                    msg["To"] = warning["email"]

                    with smtplib.SMTP("localhost", 25, timeout=10) as smtp:
                        smtp.send_message(msg)

                    notifications.append({
                        "email": warning["email"],
                        "level": warning["level"],
                        "sent": True,
                    })
                    logger.info(
                        "Quota warning sent to %s (%s)",
                        warning["email"],
                        warning["level"],
                    )
                except Exception as e:
                    logger.error(
                        "Failed to send quota warning to %s: %s",
                        warning["email"],
                        e,
                    )
                    notifications.append({
                        "email": warning["email"],
                        "level": warning["level"],
                        "sent": False,
                        "error": str(e),
                    })

        except Exception as e:
            logger.error("Error sending quota warnings: %s", e)
        return notifications

    async def get_quota_history(self, mailbox_id: int) -> list:
        history: list[dict] = []
        try:
            conn = sqlite3.connect(DB_PATH)
            try:
                cursor = conn.execute(
                    "SELECT email, current_bytes, limit_bytes, percent, recorded_at "
                    "FROM quota_audit WHERE mailbox_id=? "
                    "ORDER BY recorded_at DESC LIMIT 100",
                    (mailbox_id,),
                )
                for row in cursor.fetchall():
                    history.append({
                        "email": row[0],
                        "current_bytes": row[1],
                        "limit_bytes": row[2],
                        "percent": row[3],
                        "recorded_at": row[4],
                    })
            finally:
                conn.close()

            audit_file = AUDIT_LOG
            if not history and os.path.exists(audit_file):
                with open(audit_file) as f:
                    for line in f:
                        if f"| {mailbox_id} |" in line:
                            parts = line.split(" | ")
                            if len(parts) >= 6:
                                history.append({
                                    "recorded_at": parts[0].strip(),
                                    "current_bytes": int(parts[3].strip()),
                                    "limit_bytes": int(parts[4].strip()),
                                    "percent": float(parts[5].strip().rstrip("%")),
                                })
                history = history[-100:]

        except Exception as e:
            logger.error("Error getting quota history: %s", e)
        return history

    def _bytes_to_human(self, bytes_val: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"
