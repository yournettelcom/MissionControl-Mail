# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

POSTFIX_MAIN_CF = "/etc/postfix/main.cf"
POSTFIX_VIRTUAL_DOMAINS = "/etc/postfix/virtual_domains"
POSTFIX_TRANSPORT = "/etc/postfix/transport"
MAIL_LOG = "/var/log/mail.log"


class PostfixService:
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
            rc, out, err = await self._run_cmd(["systemctl", "is-active", "postfix"])
            return out.strip() == "active"
        except Exception as e:
            logger.error("Error checking postfix status: %s", e)
            return False

    async def get_config(self) -> dict:
        config: dict[str, str] = {}
        try:
            rc, out, err = await self._run_bash("postconf")
            if rc != 0:
                logger.error("postconf failed: %s", err)
                return config
            for line in out.splitlines():
                line = line.strip()
                if "=" in line:
                    key, _, value = line.partition("=")
                    config[key.strip()] = value.strip()
        except Exception as e:
            logger.error("Error reading postfix config: %s", e)
        return config

    async def update_config(self, key: str, value: str) -> bool:
        try:
            rc, out, err = await self._run_bash(f'postconf -e "{key}={value}"')
            if rc != 0:
                logger.error("postconf update failed: %s", err)
                return False
            return await self.reload()
        except Exception as e:
            logger.error("Error updating postfix config: %s", e)
            return False

    async def reload(self) -> bool:
        try:
            rc, out, err = await self._run_cmd(["postfix", "reload"])
            if rc == 0:
                return True
            rc2, out2, err2 = await self._run_bash("sudo postfix reload 2>/dev/null")
            if rc2 == 0:
                return True
            logger.error("postfix reload failed: %s", err)
            return False
        except Exception as e:
            logger.error("Error reloading postfix: %s", e)
            return False

    async def get_queue_status(self) -> dict:
        result: dict = {"count": 0, "queue_ids": []}
        try:
            rc, out, err = await self._run_bash("mailq 2>/dev/null || echo 'empty'")
            if rc != 0:
                return result
            lines = out.splitlines()
            queue_ids = []
            for line in lines:
                match = re.match(r"^([A-F0-9]+)\*?\s", line)
                if match:
                    queue_ids.append(match.group(1))
            result["queue_ids"] = queue_ids
            result["count"] = len(queue_ids)
        except Exception as e:
            logger.error("Error reading mail queue: %s", e)
        return result

    async def flush_queue(self) -> bool:
        try:
            rc, out, err = await self._run_cmd(["postfix", "flush"])
            if rc != 0:
                logger.error("postfix flush failed: %s", err)
                return False
            return True
        except Exception as e:
            logger.error("Error flushing queue: %s", e)
            return False

    async def get_mail_log(self, lines: int = 50) -> list:
        try:
            rc, out, err = await self._run_bash(f"tail -n {lines} {MAIL_LOG} 2>/dev/null || echo ''")
            if rc != 0:
                return []
            return [line for line in out.splitlines() if line.strip()]
        except Exception as e:
            logger.error("Error reading mail log: %s", e)
            return []

    async def get_virtual_domains(self) -> list:
        try:
            if os.path.exists(POSTFIX_VIRTUAL_DOMAINS):
                with open(POSTFIX_VIRTUAL_DOMAINS) as f:
                    domains = []
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            domains.append(line.split()[0])
                    return domains
            config = await self.get_config()
            vd = config.get("virtual_mailbox_domains", "")
            if vd and vd != "static:":
                parts = vd.replace("static:", "").replace("proxy:", "").split(",")
                return [p.strip() for p in parts if p.strip()]
            return []
        except Exception as e:
            logger.error("Error reading virtual domains: %s", e)
            return []

    async def _postmap(self) -> bool:
        try:
            rc, out, err = await self._run_bash(
                f"postmap {POSTFIX_VIRTUAL_DOMAINS} 2>/dev/null"
            )
            if rc == 0:
                return True
            rc2, out2, err2 = await self._run_bash(
                f"sudo postmap {POSTFIX_VIRTUAL_DOMAINS} 2>/dev/null"
            )
            return rc2 == 0
        except Exception:
            return False

    async def add_virtual_domain(self, domain: str) -> bool:
        try:
            domains = await self.get_virtual_domains()
            if domain in domains:
                return True
            with open(POSTFIX_VIRTUAL_DOMAINS, "a") as f:
                f.write(f"{domain}\n")
            ok = await self._postmap()
            if ok:
                return await self.reload()
            return ok
        except Exception as e:
            logger.error("Error adding virtual domain: %s", e)
            return False

    async def remove_virtual_domain(self, domain: str) -> bool:
        try:
            if not os.path.exists(POSTFIX_VIRTUAL_DOMAINS):
                return False
            with open(POSTFIX_VIRTUAL_DOMAINS) as f:
                lines = f.readlines()
            with open(POSTFIX_VIRTUAL_DOMAINS, "w") as f:
                for line in lines:
                    if line.strip() != domain:
                        f.write(line)
            ok = await self._postmap()
            if ok:
                return await self.reload()
            return ok
        except Exception as e:
            logger.error("Error removing virtual domain: %s", e)
            return False

    async def get_transport_maps(self) -> dict:
        maps: dict[str, str] = {}
        try:
            if os.path.exists(POSTFIX_TRANSPORT):
                with open(POSTFIX_TRANSPORT) as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            parts = line.split()
                            if len(parts) >= 2:
                                maps[parts[0]] = parts[1]
            else:
                config = await self.get_config()
                transport = config.get("transport_maps", "")
                if transport:
                    transport_val = transport.strip()
                    if transport_val.startswith("static:"):
                        parts = transport_val.replace("static:", "").split(",")
                        for p in parts:
                            if ":" in p:
                                k, v = p.split(":", 1)
                                maps[k.strip()] = v.strip()
                    elif transport_val.startswith("hash:") or transport_val.startswith("lmdb:"):
                        filepath = transport_val.split(":", 1)[1].strip()
                        if os.path.exists(filepath):
                            rc, out, err = await self._run_bash(f"postmap -s {filepath} 2>/dev/null")
                            if rc == 0:
                                for line in out.splitlines():
                                    if " " in line:
                                        k, v = line.split(" ", 1)
                                        maps[k.strip()] = v.strip()
        except Exception as e:
            logger.error("Error reading transport maps: %s", e)
        return maps

    async def update_transport_maps(self, maps: dict) -> bool:
        try:
            with open(POSTFIX_TRANSPORT, "w") as f:
                for key, value in maps.items():
                    f.write(f"{key}\t{value}\n")
            rc, out, err = await self._run_bash(f"postmap {POSTFIX_TRANSPORT} 2>/dev/null")
            if rc != 0:
                logger.error("postmap failed: %s", err)
                return False
            return await self.reload()
        except Exception as e:
            logger.error("Error updating transport maps: %s", e)
            return False
