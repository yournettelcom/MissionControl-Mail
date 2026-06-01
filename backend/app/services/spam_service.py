# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

RSPAMD_CONFIG = "/etc/rspamd/rspamd.conf"
QUARANTINE_DIR = "/var/vmail/quarantine"


class SpamService:
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

    async def get_stats(self) -> dict:
        stats: dict[str, Any] = {
            "total_scanned": 0,
            "spam_found": 0,
            "ham_found": 0,
            "false_positives": 0,
            "false_negatives": 0,
            "spam_percent": 0,
        }
        try:
            rc, out, err = await self._run_cmd([
                "rspamc", "stat", "-j"
            ])
            if rc == 0 and out.strip():
                try:
                    data = json.loads(out)
                    if isinstance(data, dict):
                        scanned = data.get("scanned", data.get("total", {}))
                        if isinstance(scanned, dict):
                            stats["total_scanned"] = scanned.get("count", 0)
                            stats["spam_found"] = scanned.get("spam_count", 0)
                            stats["ham_found"] = scanned.get("ham_count", 0)
                        else:
                            stats["total_scanned"] = int(scanned) if scanned else 0
                except (json.JSONDecodeError, TypeError):
                    pass

            if stats["total_scanned"] > 0:
                stats["spam_percent"] = round(
                    (stats["spam_found"] / stats["total_scanned"]) * 100, 2
                )

            if os.path.exists(QUARANTINE_DIR):
                stats["quarantine_count"] = len([
                    f for f in os.listdir(QUARANTINE_DIR)
                    if os.path.isfile(os.path.join(QUARANTINE_DIR, f))
                ])
        except Exception as e:
            logger.error("Error getting spam stats: %s", e)

        return stats

    async def scan_message(
        self, message_path: str, api_key: str | None = None
    ) -> dict:
        result: dict = {
            "is_spam": False,
            "score": 0.0,
            "details": {},
        }
        try:
            if not os.path.exists(message_path):
                logger.error("Message file not found: %s", message_path)
                return result

            if api_key:
                ai_result = await self._scan_with_ai(message_path, api_key)
                if ai_result:
                    result.update(ai_result)
                    return result

            rc, out, err = await self._run_cmd([
                "rspamc", "-j", message_path
            ])
            if rc == 0 and out.strip():
                try:
                    data = json.loads(out)
                    if isinstance(data, dict):
                        default_score = data.get("score", 0)
                        if isinstance(default_score, dict):
                            result["score"] = float(default_score.get("value", 0))
                        else:
                            result["score"] = float(default_score)
                        result["is_spam"] = result["score"] > 5.0
                        actions = data.get("actions", {})
                        if isinstance(actions, dict):
                            result["action"] = actions.get("reject", actions.get("add_header", ""))
                        symbols = data.get("symbols", {})
                        if isinstance(symbols, dict):
                            result["details"]["symbols"] = {
                                k: v for k, v in list(symbols.items())[:20]
                            }
                        result["details"]["raw"] = data
                except (json.JSONDecodeError, TypeError) as e:
                    logger.error("Failed to parse rspamc output: %s", e)

        except Exception as e:
            logger.error("Error scanning message: %s", e)
        return result

    async def _scan_with_ai(
        self, message_path: str, api_key: str
    ) -> dict | None:
        try:
            with open(message_path) as f:
                content = f.read()

            truncated = content[:8000]
            headers_body = truncated.split("\n\n", 1)
            email_text = (
                f"Subject: {headers_body[0][:500]}\n\n"
                f"{headers_body[1][:3000] if len(headers_body) > 1 else ''}"
            )

            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url="https://api.minimax.chat/v1/text/chatcompletion_v2",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": "minimax-text-01",
                        "messages": [
                            {
                                "role": "system",
                                "content": (
                                    "You are an email spam classifier. Analyze the email and return "
                                    "a JSON object with: is_spam (bool), score (0-10 float), reasons (list of strings)."
                                ),
                            },
                            {"role": "user", "content": f"Classify this email:\n\n{email_text}"},
                        ],
                        "temperature": 0.1,
                    },
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                ai_text = data.get("choices", [{}])[0].get("message", {}).get("content", "")

                json_match = re.search(r"\{.*\}", ai_text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    return {
                        "is_spam": parsed.get("is_spam", False),
                        "score": float(parsed.get("score", 0)),
                        "details": {
                            "ai_analysis": True,
                            "reasons": parsed.get("reasons", []),
                        },
                    }
        except Exception as e:
            logger.error("AI scan failed (falling back to rspamd): %s", e)
        return None

    async def get_quarantine(
        self, page: int = 1, per_page: int = 50
    ) -> dict:
        result: dict = {"items": [], "total": 0, "page": page, "pages": 0}
        try:
            items = []
            if os.path.exists(QUARANTINE_DIR):
                for fname in os.listdir(QUARANTINE_DIR):
                    fpath = os.path.join(QUARANTINE_DIR, fname)
                    if os.path.isfile(fpath):
                        stat = os.stat(fpath)
                        items.append({
                            "id": fname,
                            "path": fpath,
                            "size": stat.st_size,
                            "size_human": self._bytes_to_human(stat.st_size),
                            "modified": datetime.fromtimestamp(
                                stat.st_mtime
                            ).isoformat(),
                            "subject": f"Quarantined: {fname[:50]}",
                        })

            items.sort(key=lambda x: x["modified"], reverse=True)
            result["total"] = len(items)
            result["pages"] = max(1, (len(items) + per_page - 1) // per_page)
            start = (page - 1) * per_page
            end = start + per_page
            result["items"] = items[start:end]

        except Exception as e:
            logger.error("Error listing quarantine: %s", e)
        return result

    async def release_from_quarantine(self, message_id: str) -> bool:
        try:
            msg_path = os.path.join(QUARANTINE_DIR, message_id)
            if not os.path.exists(msg_path):
                logger.error("Message not found in quarantine: %s", message_id)
                return False

            sendmail_path = "/usr/sbin/sendmail"
            if not os.path.exists(sendmail_path):
                sendmail_path = "/usr/sbin/sendmail"

            with open(msg_path) as f:
                content = f.read()

            proc = await asyncio.create_subprocess_exec(
                sendmail_path, "-i", "-t",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate(input=content.encode())

            if proc.returncode == 0:
                os.remove(msg_path)
                return True

            logger.error("Sendmail failed for quarantined message: %s", stderr)
            return False
        except Exception as e:
            logger.error("Error releasing from quarantine: %s", e)
            return False

    async def delete_from_quarantine(self, message_id: str) -> bool:
        try:
            msg_path = os.path.join(QUARANTINE_DIR, message_id)
            if not os.path.exists(msg_path):
                return False
            os.remove(msg_path)
            return True
        except Exception as e:
            logger.error("Error deleting from quarantine: %s", e)
            return False

    async def train_filter(
        self, message_type: str, message_path: str
    ) -> bool:
        try:
            if not os.path.exists(message_path):
                logger.error("Message file not found for training: %s", message_path)
                return False

            if message_type == "spam":
                rc, out, err = await self._run_cmd([
                    "rspamc", "-f", "spam", message_path
                ])
            elif message_type == "ham":
                rc, out, err = await self._run_cmd([
                    "rspamc", "-f", "ham", message_path
                ])
            else:
                logger.error("Invalid message type for training: %s", message_type)
                return False

            if rc != 0:
                logger.error("Rspamc training failed: %s", err)
                return False
            return True
        except Exception as e:
            logger.error("Error training filter: %s", e)
            return False

    async def get_settings(self) -> dict:
        settings: dict = {}
        try:
            if os.path.exists(RSPAMD_CONFIG):
                with open(RSPAMD_CONFIG) as f:
                    content = f.read()

                current_section = "global"
                settings[current_section] = {}
                for line in content.splitlines():
                    stripped = line.strip()
                    if not stripped or stripped.startswith("#"):
                        continue
                    if stripped.startswith(".") and "{" in stripped:
                        current_section = stripped.split("{")[0].strip().lstrip(".")
                        settings[current_section] = {}
                        continue
                    if "=" in stripped:
                        key, _, value = stripped.partition("=")
                        settings[current_section][key.strip()] = value.strip().strip(
                            '";'
                        )

            rc, out, err = await self._run_cmd([
                "rspamc", "get", "actions", "-j"
            ])
            if rc == 0 and out.strip():
                try:
                    settings["actions"] = json.loads(out)
                except json.JSONDecodeError:
                    pass

        except Exception as e:
            logger.error("Error reading spam settings: %s", e)
        return settings

    async def update_settings(self, settings: dict) -> bool:
        try:
            rspamd_override = "/etc/rspamd/rspamd.conf.override"
            os.makedirs(os.path.dirname(rspamd_override), exist_ok=True)
            with open(rspamd_override, "w") as f:
                for section, values in settings.items():
                    if isinstance(values, dict):
                        f.write(f".{section} {{\n")
                        for key, value in values.items():
                            f.write(f"  {key} = {json.dumps(value)};\n")
                        f.write("}\n\n")

            rc, out, err = await self._run_cmd([
                "systemctl", "reload", "rspamd"
            ])
            return rc == 0
        except Exception as e:
            logger.error("Error updating spam settings: %s", e)
            return False

    async def integrate_minimax_api(
        self, api_key: str, model: str = "minimax-text-01"
    ) -> bool:
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    url="https://api.minimax.chat/v1/text/chatcompletion_v2",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": model,
                        "messages": [
                            {"role": "user", "content": "Reply with just the word: OK"}
                        ],
                        "temperature": 0.1,
                        "max_tokens": 10,
                    },
                    timeout=15,
                )
                response.raise_for_status()
                data = response.json()

            api_config = {
                "ai_spam_filter": {
                    "enabled": "true",
                    "api_key": api_key[:8] + "..." + api_key[-4:],
                    "model": model,
                    "provider": "minimax",
                }
            }

            await self.update_settings(api_config)

            config_file = "/etc/missioncontrol/ai_spam.conf"
            os.makedirs(os.path.dirname(config_file), exist_ok=True)
            with open(config_file, "w") as f:
                json.dump({
                    "api_key": api_key,
                    "model": model,
                    "provider": "minimax",
                    "enabled": True,
                    "integrated_at": datetime.utcnow().isoformat(),
                }, f, indent=2)

            return True
        except Exception as e:
            logger.error("Error integrating MiniMax API: %s", e)
            return False

    def _bytes_to_human(self, bytes_val: int) -> str:
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"
