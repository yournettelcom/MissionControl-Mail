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
from typing import Any, Optional

logger = logging.getLogger(__name__)

SIEVE_DIR = "/var/lib/dovecot/sieve"


class SieveService:
    async def _run_bash(self, cmd: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_shell(
            cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    async def _run_exec(self, *args: str) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    async def list_filters(self, email: str) -> list[dict]:
        filters = []
        try:
            sieve_path = os.path.join(SIEVE_DIR, email.split("@")[0], "default.sieve")
            if not os.path.exists(sieve_path):
                return filters
            with open(sieve_path) as f:
                content = f.read()
            filters = self._parse_sieve(content)
        except Exception as e:
            logger.error("Error listing sieve filters: %s", e)
        return filters

    async def save_filters(self, email: str, filters: list[dict]) -> bool:
        try:
            user_dir = os.path.join(SIEVE_DIR, email.split("@")[0])
            os.makedirs(user_dir, exist_ok=True)
            sieve_path = os.path.join(user_dir, "default.sieve")
            script = self._build_sieve(filters)
            with open(sieve_path, "w") as f:
                f.write(script)
            rc, out, err = await self._run_exec("sievec", sieve_path)
            if rc != 0:
                logger.error("sievec failed: %s", err)
                return False
            if os.path.exists("/usr/lib/dovecot/sieve"):
                rc, out, err = await self._run_exec("dovecot", "reload")
            return True
        except Exception as e:
            logger.error("Error saving sieve filters: %s", e)
            return False

    async def get_script(self, email: str) -> str:
        sieve_path = os.path.join(SIEVE_DIR, email.split("@")[0], "default.sieve")
        if os.path.exists(sieve_path):
            with open(sieve_path) as f:
                return f.read()
        return ""

    def _parse_sieve(self, content: str) -> list[dict]:
        filters = []
        blocks = re.findall(
            r"# filter: (.+?)\n(.*?)(?=\n# filter:|$)",
            content, re.DOTALL,
        )
        for name, block in blocks:
            filter_def: dict[str, Any] = {
                "name": name.strip(),
                "enabled": True,
                "conditions": [],
                "actions": [],
            }
            if "if" in block and "stop" in block:
                cond_match = re.search(r"if (.*?) \{", block, re.DOTALL)
                if cond_match:
                    cond_str = cond_match.group(1).strip()
                    filter_def["conditions"] = self._parse_conditions(cond_str)
                action_match = re.search(r"\{(.*?)\}", block, re.DOTALL)
                if action_match:
                    filter_def["actions"] = self._parse_actions(action_match.group(1))
            filters.append(filter_def)
        return filters

    def _parse_conditions(self, cond_str: str) -> list[dict]:
        conditions = []
        parts = re.findall(r"(?:allof|anyof)\((.*?)\)", cond_str, re.DOTALL)
        if not parts:
            parts = [cond_str]
        for part in parts:
            tests = re.findall(r"(header|exists|address)\s+(:contains|:is|:matches)?\s*\[?(.*?)\]?\s+\[?(.*?)\]?", part, re.DOTALL)
            for test_type, comp, field, value in tests:
                conditions.append({
                    "type": test_type,
                    "comparator": comp or ":contains",
                    "field": field.strip().strip('"').strip("'"),
                    "value": value.strip().strip('"').strip("'"),
                })
        return conditions

    def _parse_actions(self, action_block: str) -> list[dict]:
        actions = []
        for line in action_block.split(";"):
            line = line.strip()
            if not line:
                continue
            fileinto = re.match(r"fileinto\s+\"(.*?)\"", line)
            if fileinto:
                actions.append({"type": "fileinto", "mailbox": fileinto.group(1)})
                continue
            redirect = re.match(r"redirect\s+\"(.*?)\"", line)
            if redirect:
                actions.append({"type": "redirect", "address": redirect.group(1)})
                continue
            if "reject" in line:
                actions.append({"type": "reject"})
                continue
            if "discard" in line:
                actions.append({"type": "discard"})
                continue
            if "forward" in line:
                actions.append({"type": "forward"})
                continue
        return actions

    def _build_sieve(self, filters: list[dict]) -> str:
        lines = ['require ["fileinto", "redirect", "reject", "vacation", "imap4flags"];']
        if filters:
            lines.append("")
            for f in filters:
                if not f.get("enabled", True):
                    continue
                lines.append(f'# filter: {f.get("name", "Unnamed")}')
                conds = f.get("conditions", [])
                actions = f.get("actions", [])
                if conds and actions:
                    cond_exprs = []
                    for c in conds:
                        values = c.get("value", "").split(",") if isinstance(c.get("value"), str) else [c.get("value", "")]
                        cond_expr = f'{c.get("type", "header")} {c.get("comparator", ":contains")} ["{c.get("field", "")}"] ["{values[0]}"]'
                        cond_exprs.append(cond_expr)
                    if len(cond_exprs) > 1:
                        cond_str = "allof(" + ", ".join(cond_exprs) + ")"
                    else:
                        cond_str = cond_exprs[0] if cond_exprs else "true"
                    lines.append(f"if {cond_str} {{")
                    for act in actions:
                        if act.get("type") == "fileinto":
                            lines.append(f'    fileinto "{act.get("mailbox", "INBOX")}";')
                        elif act.get("type") == "redirect":
                            lines.append(f'    redirect "{act.get("address", "")}";')
                        elif act.get("type") == "reject":
                            lines.append(f'    reject "Rejected by filter";')
                        elif act.get("type") == "discard":
                            lines.append("    discard;")
                        elif act.get("type") == "forward":
                            lines.append(f'    redirect "{act.get("address", "")}";')
                    lines.append("    stop;")
                    lines.append("}")
        lines.append("")
        return "\n".join(lines)
