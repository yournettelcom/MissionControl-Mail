# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import logging
import os
import re
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException

from app.core.config import settings
from app.api.deps import get_current_user, require_admin
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/roundcube", tags=["Roundcube"])


def _read_roundcube_config() -> str:
    config_path = os.path.join(settings.ROUNDCUBE_CONFIG_DIR, "config.inc.php")
    try:
        with open(config_path, "r") as f:
            return f.read()
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="Roundcube config not found")
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")


def _write_roundcube_config(content: str) -> None:
    config_path = os.path.join(settings.ROUNDCUBE_CONFIG_DIR, "config.inc.php")
    try:
        with open(config_path, "w") as f:
            f.write(content)
    except PermissionError:
        raise HTTPException(status_code=403, detail="Permission denied")


def _parse_roundcube_config(content: str) -> Dict[str, str]:
    config = {}
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("$config["):
            match = re.match(r"\$config\['([^']+)'\]\s*=\s*'([^']*)'", line)
            if match:
                config[match.group(1)] = match.group(2)
    return config


@router.get("/config")
async def get_config(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    content = _read_roundcube_config()
    parsed = _parse_roundcube_config(content)
    return {"parsed": parsed, "raw": content}


@router.put("/config")
async def update_config(
    key: str,
    value: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    content = _read_roundcube_config()
    pattern = rf"(\$config\['{re.escape(key)}'\]\s*=\s*)[^;]+;"
    replacement = f"$config['{key}'] = '{value}';"
    if re.search(pattern, content):
        new_content = re.sub(pattern, replacement, content)
    else:
        new_content = content.rstrip() + f"\n{replacement}\n"
    _write_roundcube_config(new_content)
    return {"key": key, "value": value, "message": "Roundcube config updated"}


@router.get("/plugins")
async def list_plugins(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    content = _read_roundcube_config()
    match = re.search(r"\$config\['plugins'\]\s*=\s*\[([^\]]*)\]", content, re.DOTALL)
    if match:
        plugin_list = re.findall(r"'([^']+)'", match.group(1))
    else:
        plugin_list = []
    return {"plugins": plugin_list, "count": len(plugin_list)}


@router.post("/plugins/toggle")
async def toggle_plugin(
    plugin_name: str,
    enable: bool,
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    content = _read_roundcube_config()
    plugin_pattern = r"(\$config\['plugins'\]\s*=\s*\[)([^\]]*)(\])"
    match = re.search(plugin_pattern, content, re.DOTALL)
    if match:
        plugins_str = match.group(2)
        plugins = re.findall(r"'([^']+)'", plugins_str)
        if enable:
            if plugin_name not in plugins:
                plugins.append(plugin_name)
        else:
            plugins = [p for p in plugins if p != plugin_name]
        new_plugins_str = ", ".join(f"'{p}'" for p in plugins)
        new_content = content[:match.start(1)] + f"$config['plugins'] = [{new_plugins_str}]" + content[match.end(3):]
        _write_roundcube_config(new_content)
    else:
        if enable:
            new_content = content.rstrip() + f"\n$config['plugins'] = ['{plugin_name}'];\n"
            _write_roundcube_config(new_content)
    return {"plugin": plugin_name, "enabled": enable}


@router.get("/stats")
async def get_stats(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    db_path = "/var/lib/roundcube/roundcube.db"
    stats = {"users": 0, "logins_24h": 0, "messages_sent_24h": 0}
    try:
        import sqlite3
        if os.path.exists(db_path):
            conn = sqlite3.connect(db_path)
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT COUNT(*) FROM users")
                stats["users"] = cursor.fetchone()[0]
            except Exception:
                pass
            conn.close()
    except Exception as e:
        logger.warning(f"Could not read Roundcube stats: {e}")
    return stats
