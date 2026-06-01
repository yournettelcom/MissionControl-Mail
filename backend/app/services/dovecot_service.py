# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import hashlib
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DOVECOT_CONF = "/etc/dovecot/dovecot.conf"
DOVECOT_USERS = "/etc/dovecot/users"
DOVECOT_PASSWD = "/etc/dovecot/passwd"
DOVECOT_LOG = "/var/log/dovecot.log"


class DovecotService:
    async def _run_cmd(self, cmd: list[str]) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    async def _run_bash(self, cmd: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    async def get_status(self) -> bool:
        try:
            rc, out, err = await self._run_cmd(["systemctl", "is-active", "dovecot"])
            return out.strip() == "active"
        except Exception as e:
            logger.error("Error checking dovecot status: %s", e)
            return False

    async def get_config(self) -> dict:
        config: dict = {}
        try:
            if not os.path.exists(DOVECOT_CONF):
                logger.warning("Dovecot config not found at %s", DOVECOT_CONF)
                return config
            with open(DOVECOT_CONF) as f:
                content = f.read()
            section = "global"
            config[section] = {}
            for line in content.splitlines():
                stripped = line.strip()
                if not stripped or stripped.startswith("#"):
                    continue
                section_match = re.match(r"^section\s+(\S+)", stripped)
                if section_match:
                    section = section_match.group(1)
                    config[section] = {}
                    continue
                if "=" in stripped:
                    key, _, value = stripped.partition("=")
                    config[section][key.strip()] = value.strip()
        except Exception as e:
            logger.error("Error reading dovecot config: %s", e)
        return config

    async def reload(self) -> bool:
        try:
            rc, out, err = await self._run_cmd(["dovecot", "reload"])
            if rc != 0:
                logger.error("dovecot reload failed: %s", err)
                return await self._run_cmd(["systemctl", "reload", "dovecot"])[0] == 0
            return True
        except Exception as e:
            logger.error("Error reloading dovecot: %s", e)
            try:
                rc, out, err = await self._run_cmd(["systemctl", "reload", "dovecot"])
                return rc == 0
            except Exception:
                return False

    async def get_users(self) -> list:
        users: list[dict] = []
        try:
            passwd_file = None
            if os.path.exists(DOVECOT_USERS):
                passwd_file = DOVECOT_USERS
            elif os.path.exists(DOVECOT_PASSWD):
                passwd_file = DOVECOT_PASSWD

            if passwd_file:
                with open(passwd_file) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            parts = line.split(":")
                            if len(parts) >= 7:
                                users.append({
                                    "username": parts[0],
                                    "uid": parts[2],
                                    "gid": parts[3],
                                    "home": parts[6],
                                })
                            elif len(parts) >= 1:
                                users.append({"username": parts[0]})
            rc, out, err = await self._run_bash("doveadm user '*' 2>/dev/null")
            if rc == 0 and out.strip():
                for line in out.splitlines():
                    if line.strip() and not line.startswith("username"):
                        users.append({"username": line.strip()})
        except Exception as e:
            logger.error("Error listing dovecot users: %s", e)
        return users

    async def create_user(self, username: str, password: str) -> bool:
        try:
            hasher = hashlib.md5 if "MD5" in open(DOVECOT_CONF).read() else hashlib.sha256
            digest = hashlib.sha256(password.encode()).hexdigest()
            rc, out, err = await self._run_bash(
                f'doveadm pw -s SHA256-CRYPT -p "{password}" 2>/dev/null'
            )
            if rc == 0:
                hashed = out.strip()
            else:
                hashed = f"{{SHA256}}{digest}"
            home_dir = f"/var/vmail/{username.split('@')[1] if '@' in username else 'unknown'}/{username.split('@')[0] if '@' in username else username}"
            entry = f"{username}:{hashed}:5000:5000::{home_dir}::\n"
            with open(DOVECOT_USERS, "a") as f:
                f.write(entry)
            return True
        except Exception as e:
            logger.error("Error creating dovecot user: %s", e)
            return False

    async def delete_user(self, username: str) -> bool:
        try:
            passwd_file = None
            if os.path.exists(DOVECOT_USERS):
                passwd_file = DOVECOT_USERS
            elif os.path.exists(DOVECOT_PASSWD):
                passwd_file = DOVECOT_PASSWD
            if not passwd_file:
                return False
            with open(passwd_file) as f:
                lines = f.readlines()
            with open(passwd_file, "w") as f:
                for line in lines:
                    if not line.startswith(f"{username}:"):
                        f.write(line)
            return True
        except Exception as e:
            logger.error("Error deleting dovecot user: %s", e)
            return False

    async def get_quota_usage(self, username: str) -> dict:
        result: dict = {"current": 0, "limit": 0, "percent": 0}
        try:
            rc, out, err = await self._run_bash(
                f'doveadm quota get -u {username} 2>/dev/null'
            )
            if rc == 0:
                for line in out.splitlines():
                    parts = line.split()
                    if len(parts) >= 4:
                        result["current"] = int(parts[2]) if parts[2].isdigit() else 0
                        result["limit"] = int(parts[3]) if parts[3].isdigit() else 0
                        if result["limit"] > 0:
                            result["percent"] = round(
                                (result["current"] / result["limit"]) * 100, 1
                            )
            quota_file = Path(f"/var/vmail/{username.split('@')[1] if '@' in username else ''}/maildir/maildirsize")
            if quota_file.exists():
                with open(quota_file) as f:
                    content = f.read().strip()
                    if content:
                        lines = content.splitlines()
                        if len(lines) >= 2:
                            limit_parts = lines[0].split("S")
                            if limit_parts:
                                result["limit"] = int(limit_parts[0]) * 1024 if limit_parts[0].isdigit() else 0
                            current_bytes = sum(int(x) for x in lines[1:] if x.lstrip("-").isdigit())
                            result["current"] = abs(current_bytes)
                            if result["limit"] > 0:
                                result["percent"] = round(
                                    (result["current"] / result["limit"]) * 100, 1
                                )
        except Exception as e:
            logger.error("Error getting quota for %s: %s", username, e)
        return result

    async def get_log(self, lines: int = 50) -> list:
        try:
            log_file = DOVECOT_LOG
            if not os.path.exists(log_file):
                log_file = "/var/log/mail.log"
            rc, out, err = await self._run_bash(f"tail -n {lines} {log_file} 2>/dev/null || echo ''")
            if rc != 0:
                return []
            return [line for line in out.splitlines() if line.strip()]
        except Exception as e:
            logger.error("Error reading dovecot log: %s", e)
            return []
