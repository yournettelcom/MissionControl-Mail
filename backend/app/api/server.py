# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import logging
import subprocess
import platform
import os
from datetime import datetime
from typing import Dict, Any

import psutil

from fastapi import APIRouter, Depends, HTTPException, status

from app.api.deps import get_current_user, require_admin
from app.models.user import User

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/server", tags=["Server Management"])

SERVICES = ["postfix", "dovecot", "rspamd", "mariadb", "fail2ban", "mail", "system"]


async def _run_cmd(cmd: list) -> str:
    try:
        result = await asyncio.to_thread(subprocess.run, cmd, capture_output=True, text=True, timeout=10)
        return result.stdout.strip()
    except Exception as e:
        return str(e)


async def _service_status(name: str) -> str:
    result = await _run_cmd(["systemctl", "is-active", name])
    if "active" in result.lower():
        return "running"
    if "inactive" in result.lower():
        return "stopped"
    if "not-found" in result.lower() or "could not" in result.lower():
        return "not_found"
    return "unknown"


@router.get("/status")
async def server_status(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    results = await asyncio.gather(*[_service_status(svc) for svc in SERVICES])
    return {"services": dict(zip(SERVICES, results)), "timestamp": datetime.now().isoformat()}


@router.post("/service/{service_name}/start")
async def start_service(
    service_name: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    if service_name not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    result = await _run_cmd(["systemctl", "start", service_name])
    new_status = await _service_status(service_name)
    return {"service": service_name, "action": "start", "status": new_status, "output": result}


@router.post("/service/{service_name}/stop")
async def stop_service(
    service_name: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    if service_name not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    result = await _run_cmd(["systemctl", "stop", service_name])
    new_status = await _service_status(service_name)
    return {"service": service_name, "action": "stop", "status": new_status, "output": result}


@router.post("/service/{service_name}/restart")
async def restart_service(
    service_name: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, str]:
    if service_name not in SERVICES:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    result = await _run_cmd(["systemctl", "restart", service_name])
    new_status = await _service_status(service_name)
    return {"service": service_name, "action": "restart", "status": new_status, "output": result}


SERVICE_LOG_FILE = {
    "postfix": "/var/log/mail.log",
    "dovecot": "/var/log/syslog",
    "rspamd": "/var/log/syslog",
    "mariadb": "/var/log/syslog",
    "fail2ban": "/var/log/syslog",
    "mail": "/var/log/mail.log",
    "system": "/var/log/syslog",
}

SERVICE_LOG_GREP = {
    "dovecot": "dovecot",
    "rspamd": "rspamd",
    "mariadb": "mariadb",
    "fail2ban": "fail2ban",
}

@router.get("/logs/{service_name}")
async def service_logs(
    service_name: str,
    lines: int = 50,
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    logfile = SERVICE_LOG_FILE.get(service_name)
    if not logfile:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    grep_pat = SERVICE_LOG_GREP.get(service_name)
    buffer = lines * 5
    output = await _run_cmd(["tail", "-n", str(buffer), logfile])
    raw_lines = output.split("\n")
    if grep_pat:
        raw_lines = [l for l in raw_lines if grep_pat in l.lower()]
    lines_list = [l for l in raw_lines if l.strip()]
    return {"service": service_name, "lines": lines_list[-lines:]}


@router.delete("/logs/{service_name}/clear")
async def clear_service_logs(
    service_name: str,
    current_user: User = Depends(require_admin),
) -> Dict[str, Any]:
    logfile = SERVICE_LOG_FILE.get(service_name)
    if not logfile:
        raise HTTPException(status_code=400, detail=f"Unknown service: {service_name}")
    await _run_cmd(["sudo", "truncate", "-s", "0", logfile])
    return {"service": service_name, "status": "cleared"}


@router.get("/info")
async def system_info(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    uname = platform.uname()
    boot_time = datetime.fromtimestamp(psutil.boot_time()).isoformat()
    uptime_seconds = int(datetime.now().timestamp() - psutil.boot_time())
    load = psutil.getloadavg()
    return {
        "hostname": uname.node,
        "os": f"{uname.system} {uname.release}",
        "kernel": uname.version,
        "architecture": uname.machine,
        "uptime_seconds": uptime_seconds,
        "boot_time": boot_time,
        "cpu_count": psutil.cpu_count(),
        "cpu_usage_percent": psutil.cpu_percent(interval=None),
        "memory_total_gb": round(psutil.virtual_memory().total / (1024**3), 2),
        "memory_used_gb": round(psutil.virtual_memory().used / (1024**3), 2),
        "memory_percent": psutil.virtual_memory().percent,
        "load_1min": round(load[0], 2),
        "load_5min": round(load[1], 2),
        "load_15min": round(load[2], 2),
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/disk")
async def disk_usage(current_user: User = Depends(get_current_user)) -> Dict[str, Any]:
    partitions = []
    for part in psutil.disk_partitions():
        try:
            usage = psutil.disk_usage(part.mountpoint)
            partitions.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_gb": round(usage.total / (1024**3), 2),
                "used_gb": round(usage.used / (1024**3), 2),
                "free_gb": round(usage.free / (1024**3), 2),
                "percent": usage.percent,
            })
        except PermissionError:
            continue
    return {
        "partitions": partitions,
        "vmail_dir": await _get_dir_size("/opt/missioncontrol/vmail"),
    }


async def _get_dir_size(path: str) -> Dict[str, Any]:
    try:
        exists = await asyncio.to_thread(os.path.exists, path)
        if not exists:
            return {"path": path, "exists": False}
        result = await _run_cmd(["du", "-sb", path])
        parts = result.split("\t")
        total_bytes = int(parts[0]) if parts else 0
        return {
            "path": path,
            "exists": True,
            "total_gb": round(total_bytes / (1024**3), 2),
            "total_mb": round(total_bytes / (1024**2), 2),
        }
    except Exception as e:
        return {"path": path, "error": str(e)}


@router.get("/disk/domains")
async def domain_disk_usage(current_user: User = Depends(require_admin)) -> Dict[str, Any]:
    vmail = "/opt/missioncontrol/vmail"
    domains_map = {}
    if await asyncio.to_thread(os.path.exists, vmail):
        entries = await asyncio.to_thread(os.listdir, vmail)
        for entry in entries:
            domain_path = os.path.join(vmail, entry)
            if await asyncio.to_thread(os.path.isdir, domain_path):
                domains_map[entry] = await _get_dir_size(domain_path)
    domains_array = [
        {"domain": name, **details}
        for name, details in domains_map.items()
    ]
    return {"vmail_dir": vmail, "domains": domains_map, "domains_array": domains_array}
