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
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .cloudflare_service import CloudflareService
from .dns_service import DnsService
from .dovecot_service import DovecotService
from .postfix_service import PostfixService

logger = logging.getLogger(__name__)

DB_PATH = "/etc/missioncontrol/missioncontrol.db"


class DomainService:
    def __init__(self):
        self.postfix = PostfixService()
        self.dovecot = DovecotService()
        self.dns = DnsService()
        self._ensure_db()

    def _ensure_db(self):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH)
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS domains (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT UNIQUE NOT NULL,
                    description TEXT,
                    created_at TEXT DEFAULT (datetime('now')),
                    updated_at TEXT DEFAULT (datetime('now')),
                    status TEXT DEFAULT 'active',
                    dkim_selector TEXT,
                    dkim_private_key TEXT,
                    dkim_public_key TEXT,
                    dns_configured INTEGER DEFAULT 0,
                    cloudflare_zone_id TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mailboxes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    domain_id INTEGER NOT NULL,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT,
                    quota_limit INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT (datetime('now')),
                    status TEXT DEFAULT 'active',
                    FOREIGN KEY (domain_id) REFERENCES domains(id)
                )
            """)
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

    async def create_domain_with_dns(
        self,
        domain_data: dict,
        cloudflare_token: str | None = None,
    ) -> dict:
        report: dict[str, Any] = {
            "domain": domain_data.get("name", ""),
            "steps": {},
            "status": "pending",
        }
        domain_name = domain_data.get("name", "")

        try:
            conn = sqlite3.connect(DB_PATH)
            try:
                cursor = conn.execute(
                    "INSERT INTO domains (name, description) VALUES (?, ?)",
                    (domain_name, domain_data.get("description", "")),
                )
                domain_id = cursor.lastrowid
                conn.commit()
                report["steps"]["database"] = {
                    "success": True,
                    "domain_id": domain_id,
                }
            except sqlite3.IntegrityError:
                cursor = conn.execute(
                    "SELECT id FROM domains WHERE name = ?", (domain_name,)
                )
                row = cursor.fetchone()
                domain_id = row[0] if row else None
                report["steps"]["database"] = {
                    "success": True,
                    "domain_id": domain_id,
                    "note": "domain already exists",
                }
            finally:
                conn.close()

            vmail_path = f"/var/vmail/{domain_name}"
            os.makedirs(vmail_path, exist_ok=True)
            report["steps"]["vmail_directory"] = {
                "success": True,
                "path": vmail_path,
            }

            vd_added = await self.postfix.add_virtual_domain(domain_name)
            report["steps"]["postfix_virtual_domain"] = {"success": vd_added}

            dkim_private, dkim_public = await self.dns.generate_dkim_keypair()
            selector = f"dkim.{domain_name.replace('.', '_')}"
            dkim_dir = f"/etc/opendkim/keys/{domain_name}"
            os.makedirs(dkim_dir, exist_ok=True)
            with open(f"{dkim_dir}/{selector}.private", "w") as f:
                f.write(dkim_private)
            with open(f"{dkim_dir}/{selector}.public", "w") as f:
                f.write(dkim_public)
            os.chmod(f"{dkim_dir}/{selector}.private", 0o600)
            report["steps"]["dkim_keys"] = {
                "success": True,
                "selector": selector,
            }

            conn = sqlite3.connect(DB_PATH)
            try:
                conn.execute(
                    "UPDATE domains SET dkim_selector=?, dkim_private_key=?, dkim_public_key=? WHERE id=?",
                    (selector, dkim_private, dkim_public, domain_id),
                )
                conn.commit()
            finally:
                conn.close()

            mail_server_hostname = domain_data.get(
                "mail_server", f"mail.{domain_name}"
            )
            if cloudflare_token:
                report["steps"]["dns_wizard"] = await self.dns.wizard(
                    domain=domain_name,
                    mail_server_hostname=mail_server_hostname,
                    cloudflare_token=cloudflare_token,
                )

                if report["steps"]["dns_wizard"].get("status") == "completed":
                    conn = sqlite3.connect(DB_PATH)
                    try:
                        zone_id = (
                            report["steps"]["dns_wizard"]
                            .get("steps", {})
                            .get("zone_found", {})
                            .get("zone_id", "")
                        )
                        conn.execute(
                            "UPDATE domains SET dns_configured=1, cloudflare_zone_id=? WHERE id=?",
                            (zone_id, domain_id),
                        )
                        conn.commit()
                    finally:
                        conn.close()

            propagation = await self.dns.check_propagation(
                domain_name, "MX", mail_server_hostname
            )
            report["steps"]["propagation"] = propagation

            report["domain_id"] = domain_id
            report["status"] = "completed"

        except Exception as e:
            logger.error("Domain creation failed: %s", e)
            report["status"] = "error"
            report["error"] = str(e)

        return report

    async def delete_domain(self, domain_id: int) -> dict:
        report: dict[str, Any] = {"domain_id": domain_id, "steps": {}, "status": "pending"}

        try:
            conn = sqlite3.connect(DB_PATH)
            try:
                cursor = conn.execute(
                    "SELECT name, cloudflare_zone_id, dkim_selector FROM domains WHERE id=?",
                    (domain_id,),
                )
                row = cursor.fetchone()
                if not row:
                    report["status"] = "domain_not_found"
                    return report
                domain_name = row[0]
                cloudflare_zone_id = row[1]
            finally:
                pass

            backup_dir = f"/tmp/missioncontrol_backup/{domain_name}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}"
            shutil.copytree(f"/var/vmail/{domain_name}", backup_dir, dirs_exist_ok=True)
            report["steps"]["backup"] = {"success": True, "path": backup_dir}

            conn.execute(
                "SELECT email FROM mailboxes WHERE domain_id=?",
                (domain_id,),
            )
            mailboxes = conn.fetchall()
            for (email,) in mailboxes:
                await self.dovecot.delete_user(email)
            conn.execute("DELETE FROM mailboxes WHERE domain_id=?", (domain_id,))
            report["steps"]["mailboxes_deleted"] = {"count": len(mailboxes)}

            await self.postfix.remove_virtual_domain(domain_name)
            report["steps"]["postfix_removed"] = {"success": True}

            if os.path.exists(f"/var/vmail/{domain_name}"):
                shutil.rmtree(f"/var/vmail/{domain_name}")
            report["steps"]["vmail_removed"] = {"success": True}

            conn.execute("DELETE FROM domains WHERE id=?", (domain_id,))
            conn.commit()
            report["steps"]["database"] = {"success": True}

            if cloudflare_zone_id:
                try:
                    cf = CloudflareService("")
                    report["steps"]["cloudflare_cleanup"] = {"note": "requires cloudflare_token to clean DNS records"}
                except Exception as e:
                    logger.warning(f"Cloudflare cleanup failed for domain {domain_name}: {e}")

            report["status"] = "completed"

        except Exception as e:
            logger.error("Domain deletion failed: %s", e)
            report["status"] = "error"
            report["error"] = str(e)
        finally:
            try:
                conn.close()
            except Exception:
                pass

        return report
