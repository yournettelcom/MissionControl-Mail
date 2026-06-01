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
import subprocess
import re
from datetime import datetime
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.core.config import settings
from app.api.deps import get_current_user, require_admin
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/services", tags=["Service Configs"])


async def _read_file(path: str) -> str:
    try:
        return await asyncio.to_thread(_read_file_sync, path)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"File not found: {path}")
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")


def _read_file_sync(path: str) -> str:
    with open(path, "r") as f:
        return f.read()


async def _write_file(path: str, content: str) -> None:
    try:
        await asyncio.to_thread(_write_file_sync, path, content)
    except PermissionError:
        raise HTTPException(status_code=403, detail=f"Permission denied: {path}")


def _write_file_sync(path: str, content: str) -> None:
    with open(path, "w") as f:
        f.write(content)


async def _run_cmd(cmd: list) -> str:
    try:
        result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=30)
        return result.stdout.strip()
    except Exception as e:
        return str(e)


def _parse_postfix_config(content: str) -> Dict[str, str]:
    config = {}
    for line in content.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, _, value = line.partition("=")
            config[key.strip()] = value.strip()
    return config


# --- Roundcube ---

@router.get("/roundcube/config")
async def get_roundcube_config(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    config_path = os.path.join(settings.ROUNDCUBE_CONFIG_DIR, "config.inc.php")
    content = await _read_file(config_path)
    return {"path": config_path, "content": content}


@router.put("/roundcube/config")
async def update_roundcube_config(
    key: str,
    value: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    config_path = os.path.join(settings.ROUNDCUBE_CONFIG_DIR, "config.inc.php")
    content = await _read_file(config_path)
    pattern = rf"(\$config\['{re.escape(key)}'\]\s*=\s*)[^;]+;"
    replacement = f"$config['{key}'] = '{value}';"
    if re.search(pattern, content):
        new_content = re.sub(pattern, replacement, content)
    else:
        new_content = content.rstrip() + f"\n{replacement}\n"
    await _write_file(config_path, new_content)
    return {"key": key, "value": value, "message": "Roundcube config updated"}


# --- Postfix ---

@router.get("/postfix/config")
async def get_postfix_config(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    config_path = os.path.join(settings.POSTFIX_CONFIG_DIR, "main.cf")
    content = await _read_file(config_path)
    parsed = _parse_postfix_config(content)
    return {"path": config_path, "parsed": parsed, "raw": content}


@router.put("/postfix/config")
async def update_postfix_config(
    updates: Dict[str, str],
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    config_path = os.path.join(settings.POSTFIX_CONFIG_DIR, "main.cf")
    content = await _read_file(config_path)
    for key, value in updates.items():
        if value == '#REMOVED#':
            pattern = rf"^\s*#?\s*{re.escape(key)}\s*=.*$"
            content = re.sub(pattern, f"# {key} = (removed)", content, flags=re.MULTILINE)
        else:
            pattern = rf"^({re.escape(key)}\s*=\s*).*$"
            replacement = f"{key} = {value}"
            if re.search(pattern, content, re.MULTILINE):
                content = re.sub(pattern, replacement, content, flags=re.MULTILINE)
            else:
                content += f"\n{replacement}\n"
    await _write_file(config_path, content)
    await _run_cmd(["postfix", "reload"])
    return {"message": "Postfix config updated and reloaded", "updates": updates}


@router.post("/postfix/reload")
async def reload_postfix(
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    output = await _run_cmd(["postfix", "reload"])
    return {"message": "Postfix reloaded", "output": output}


@router.get("/postfix/queue")
async def mail_queue(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    output = await _run_cmd(["postqueue", "-p"])
    lines = output.split("\n")
    size_match = next((l for l in lines if "-- Kbytes in" in l or "requests" in l), "")
    import re
    total = 0
    size_m = re.search(r"(\d+)\s+request", size_match)
    if size_m:
        total = int(size_m.group(1))
    active = deferred = hold = 0
    for line in lines:
        low = line.lower()
        if "deferred" in low:
            deferred += 1
        elif "active" in low:
            active += 1
        elif "hold" in low:
            hold += 1
    return {
        "queue_size": total,
        "total": total,
        "active": active,
        "deferred": deferred,
        "hold": hold,
        "raw": lines,
    }


@router.post("/postfix/flush-queue")
async def flush_queue(
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    output = await _run_cmd(["postfix", "flush"])
    return {"message": "Queue flush initiated", "output": output}


# --- Service Logs ---

SERVICE_LOG_MAP = {
    "postfix": "postfix",
    "dovecot": "dovecot",
    "rspamd": "rspamd",
    "mariadb": "mariadb",
    "fail2ban": "fail2ban",
    "mail": "postfix",
    "system": "systemd-journald",
}


@router.delete("/{service_name}/logs/clear")
async def clear_service_logs(
    service_name: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    unit = SERVICE_LOG_MAP.get(service_name)
    if not unit:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    output = await _run_cmd(["journalctl", "--rotate", "-u", f"{unit}.service"])
    output2 = await _run_cmd(["journalctl", "--vacuum-size=1M", "-u", f"{unit}.service"])
    return {"service": service_name, "message": "Logs cleared", "output": output + "\n" + output2}


# --- Dovecot ---

@router.get("/dovecot/config")
async def get_dovecot_config(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    config_path = os.path.join(settings.DOVECOT_CONFIG_DIR, "dovecot.conf")
    content = await _read_file(config_path)
    parsed = {}
    import re
    depth = 0
    for line in content.splitlines():
        stripped = line.strip()
        depth += stripped.count('{') - stripped.count('}')
        if depth > 0:
            continue
        if '{' in stripped or '}' in stripped:
            continue
        match = re.match(r'^\s*(\w+)\s*=\s*(.+?)\s*$', stripped)
        if match:
            parsed[match.group(1)] = match.group(2).strip()
    return {"path": config_path, "content": content, "parsed": parsed}


@router.put("/dovecot/config")
async def update_dovecot_config(
    updates: Dict[str, str],
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    config_path = os.path.join(settings.DOVECOT_CONFIG_DIR, "dovecot.conf")
    content = await _read_file(config_path)
    for key, value in updates.items():
        import re
        if re.search(rf"^\s*#?\s*{re.escape(key)}\s*=", content, re.MULTILINE):
            content = re.sub(
                rf"^\s*#?\s*{re.escape(key)}\s*=.*$",
                f"{key} = {value}",
                content,
                count=1,
                flags=re.MULTILINE,
            )
        else:
            content += f"\n{key} = {value}"
    with open(config_path, "w") as f:
        f.write(content)
    return {"path": config_path, "message": "Dovecot config updated"}


GENERAL_SETTINGS_PATH = "/opt/missioncontrol/general_settings.json"


def _load_general_settings() -> dict:
    if os.path.exists(GENERAL_SETTINGS_PATH):
        with open(GENERAL_SETTINGS_PATH) as f:
            return json.load(f)
    return {
        "serverName": "MissionControl Server",
        "adminEmail": "admin@mail.example.com",
        "language": "en",
        "timezone": "UTC",
        "refreshInterval": "30",
    }


def _save_general_settings(data: dict):
    os.makedirs(os.path.dirname(GENERAL_SETTINGS_PATH), exist_ok=True)
    with open(GENERAL_SETTINGS_PATH, "w") as f:
        json.dump(data, f, indent=2)


@router.get("/general")
async def get_general_settings(
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    return _load_general_settings()


@router.put("/general")
async def update_general_settings(
    data: Dict[str, Any],
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    current = _load_general_settings()
    current.update(data)
    _save_general_settings(current)
    return {"message": "General settings updated", "settings": current}


API_KEYS_PATH = "/opt/missioncontrol/api_keys.json"


@router.get("/api-keys")
async def list_api_keys(
    current_user: User = Depends(require_admin),
) -> List[Dict[str, Any]]:
    if os.path.exists(API_KEYS_PATH):
        with open(API_KEYS_PATH) as f:
            return json.load(f)
    return []


@router.post("/api-keys")
async def create_api_key(
    data: Dict[str, Any],
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    keys = []
    if os.path.exists(API_KEYS_PATH):
        with open(API_KEYS_PATH) as f:
            keys = json.load(f)
    import secrets
    max_id = max((k["id"] for k in keys), default=0)
    new_key = {
        "id": max_id + 1,
        "name": data.get("name", "Untitled Key"),
        "key": f"mc_{secrets.token_hex(16)}",
        "status": "active",
        "created": datetime.now().strftime("%Y-%m-%d"),
    }
    keys.append(new_key)
    os.makedirs(os.path.dirname(API_KEYS_PATH), exist_ok=True)
    with open(API_KEYS_PATH, "w") as f:
        json.dump(keys, f, indent=2)
    return new_key


@router.delete("/api-keys/{key_id}")
async def delete_api_key(
    key_id: int,
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    if not os.path.exists(API_KEYS_PATH):
        raise HTTPException(status_code=404, detail="No API keys found")
    with open(API_KEYS_PATH) as f:
        keys = json.load(f)
    keys = [k for k in keys if k["id"] != key_id]
    with open(API_KEYS_PATH, "w") as f:
        json.dump(keys, f, indent=2)
    return {"message": "API key deleted"}
