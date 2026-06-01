# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import hashlib
import logging
import os
import re
from typing import Any, Optional

logger = logging.getLogger(__name__)

ROUNDCUBE_CONFIG = "/etc/roundcube/config.inc.php"
ROUNDCUBE_DB_DSN = os.environ.get("ROUNDCUBE_DB_DSN", "mysql://roundcube:roundcube@localhost/roundcube")


class RoundcubeService:
    CONFIG_FILE = ROUNDCUBE_CONFIG

    def __init__(self, db_dsn: str = ROUNDCUBE_DB_DSN):
        self.db_dsn = db_dsn

    async def _run_cmd(self, cmd: list[str]) -> tuple[int, str, str]:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return proc.returncode or 0, stdout.decode(), stderr.decode()

    async def get_config(self) -> dict:
        config: dict[str, Any] = {}
        try:
            if not os.path.exists(self.CONFIG_FILE):
                logger.warning("Roundcube config not found at %s", self.CONFIG_FILE)
                return config
            with open(self.CONFIG_FILE) as f:
                content = f.read()

            pattern = r"\$config\['([^']+)'\]\s*=\s*(.+?);"
            for match in re.finditer(pattern, content, re.DOTALL):
                key = match.group(1)
                raw = match.group(2).strip()
                config[key] = self._parse_php_value(raw)
        except Exception as e:
            logger.error("Error reading roundcube config: %s", e)
        return config

    def _parse_php_value(self, raw: str) -> Any:
        raw = raw.strip()
        if raw == "true":
            return True
        if raw == "false":
            return False
        if raw == "null":
            return None
        if raw.startswith("'") and raw.endswith("'"):
            return raw[1:-1]
        if raw.startswith('"') and raw.endswith('"'):
            return raw[1:-1]
        if raw.startswith("array(") or raw.startswith("["):
            return self._parse_php_array(raw)
        if raw.isdigit():
            return int(raw)
        if re.match(r"^\d+\.\d+$", raw):
            return float(raw)
        return raw

    def _parse_php_array(self, raw: str) -> list:
        raw = raw.strip()
        if raw.startswith("array("):
            inner = raw[6:-1]
        elif raw.startswith("["):
            inner = raw[1:-1]
        else:
            return []
        items = []
        depth = 0
        current = ""
        in_string = False
        string_char = None
        for ch in inner:
            if in_string:
                current += ch
                if ch == string_char and (len(current) < 2 or current[-2] != "\\"):
                    in_string = False
            elif ch in ("'", '"'):
                in_string = True
                string_char = ch
                current += ch
            elif ch in ("(", "["):
                depth += 1
                current += ch
            elif ch in (")", "]"):
                depth -= 1
                current += ch
            elif ch == "," and depth == 0:
                items.append(current.strip())
                current = ""
            else:
                current += ch
        if current.strip():
            items.append(current.strip())
        return [self._parse_php_value(item) for item in items]

    async def update_config(self, key: str, value: Any) -> bool:
        try:
            if not os.path.exists(self.CONFIG_FILE):
                logger.error("Config file not found: %s", self.CONFIG_FILE)
                return False
            with open(self.CONFIG_FILE) as f:
                content = f.read()

            php_value = self._to_php_string(value)
            pattern = rf"(\$config\['{re.escape(key)}'\]\s*=\s*).*?;"
            replacement = rf"\1{php_value};"
            if re.search(pattern, content, re.DOTALL):
                content = re.sub(pattern, replacement, content, count=1)
            else:
                content += f"\n$config['{key}'] = {php_value};\n"

            with open(self.CONFIG_FILE, "w") as f:
                f.write(content)
            return True
        except Exception as e:
            logger.error("Error updating roundcube config: %s", e)
            return False

    def _to_php_string(self, value: Any) -> str:
        if isinstance(value, bool):
            return "true" if value else "false"
        if value is None:
            return "null"
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, (list, tuple)):
            items = ", ".join(self._to_php_string(v) for v in value)
            return f"array({items})"
        escaped = str(value).replace("\\", "\\\\").replace("'", "\\'")
        return f"'{escaped}'"

    async def get_plugins(self) -> list:
        config = await self.get_config()
        plugins = config.get("plugins", [])
        if isinstance(plugins, list):
            return plugins
        return []

    async def toggle_plugin(self, plugin: str, enable: bool) -> bool:
        try:
            plugins = await self.get_plugins()
            if enable:
                if plugin not in plugins:
                    plugins.append(plugin)
            else:
                plugins = [p for p in plugins if p != plugin]
            return await self.update_config("plugins", plugins)
        except Exception as e:
            logger.error("Error toggling plugin: %s", e)
            return False

    async def get_stats(self) -> dict:
        stats: dict = {"active_users": 0, "total_users": 0}
        try:
            rc, out, err = await self._run_cmd([
                "mysql", "--batch", "--silent",
                "-e",
                "SELECT COUNT(*) FROM roundcube.users",
                "-h", "localhost",
                "-u", "roundcube",
                f"-p{self._get_db_pass()}",
                "roundcube",
            ])
            if rc == 0 and out.strip().isdigit():
                stats["total_users"] = int(out.strip())

            rc, out, err = await self._run_cmd([
                "mysql", "--batch", "--silent",
                "-e",
                "SELECT COUNT(*) FROM roundcube.users WHERE last_login > UNIX_TIMESTAMP(DATE_SUB(NOW(), INTERVAL 30 DAY))",
                "-h", "localhost",
                "-u", "roundcube",
                f"-p{self._get_db_pass()}",
                "roundcube",
            ])
            if rc == 0 and out.strip().isdigit():
                stats["active_users"] = int(out.strip())
        except Exception as e:
            logger.error("Error getting roundcube stats: %s", e)
        return stats

    def _escape_mysql(self, value: str) -> str:
        return value.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"')

    def _get_db_pass(self) -> str:
        try:
            if ":" in self.db_dsn:
                parts = self.db_dsn.split("@")[0].split("//")[-1]
                if ":" in parts:
                    return parts.split(":")[1]
        except Exception:
            pass
        return "roundcube"

    async def create_user(self, email: str, password: str) -> bool:
        try:
            hashed = hashlib.md5(password.encode()).hexdigest()
            safe_email = self._escape_mysql(email)
            rc, out, err = await self._run_cmd([
                "mysql", "--batch", "--silent",
                "-e",
                f"INSERT INTO roundcube.users (username, mail_host, created, last_login, language, password) "
                f"VALUES ('{safe_email}', 'localhost', UNIX_TIMESTAMP(), UNIX_TIMESTAMP(), 'en_US', '{hashed}')",
                "-h", "localhost",
                "-u", "roundcube",
                f"-p{self._get_db_pass()}",
                "roundcube",
            ])
            return rc == 0
        except Exception as e:
            logger.error("Error creating roundcube user: %s", e)
            return False

    async def delete_user(self, email: str) -> bool:
        try:
            safe_email = self._escape_mysql(email)
            rc, out, err = await self._run_cmd([
                "mysql", "--batch", "--silent",
                "-e",
                f"DELETE FROM roundcube.users WHERE username = '{safe_email}'",
                "-h", "localhost",
                "-u", "roundcube",
                f"-p{self._get_db_pass()}",
                "roundcube",
            ])
            return rc == 0
        except Exception as e:
            logger.error("Error deleting roundcube user: %s", e)
            return False
