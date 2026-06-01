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
import os
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import psutil
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from app.core.database import get_db
from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.models.audit import AuditLog
from app.models.mailbox import Mailbox

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/metrics", tags=["Metrics"])


@router.get("/system")
async def system_metrics(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    cpu_percent = psutil.cpu_percent(interval=None)
    cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    load_avg = [round(x, 2) for x in psutil.getloadavg()]
    return {
        "cpu_percent": cpu_percent,
        "memory_percent": mem.percent,
        "memory_used_gb": round(mem.used / (1024**3), 2),
        "memory_total_gb": round(mem.total / (1024**3), 2),
        "disk_percent": disk.percent,
        "network_sent_gb": round(net.bytes_sent / (1024**3), 2),
        "network_recv_gb": round(net.bytes_recv / (1024**3), 2),
        "cpu": {
            "percent": cpu_percent,
            "per_core": cpu_per_core,
            "count": psutil.cpu_count(),
            "load_avg": load_avg,
        },
        "memory": {
            "total_gb": round(mem.total / (1024**3), 2),
            "used_gb": round(mem.used / (1024**3), 2),
            "free_gb": round(mem.free / (1024**3), 2),
            "percent": mem.percent,
        },
        "disk": {
            "total_gb": round(disk.total / (1024**3), 2),
            "used_gb": round(disk.used / (1024**3), 2),
            "free_gb": round(disk.free / (1024**3), 2),
            "percent": disk.percent,
        },
        "network": {
            "bytes_sent_mb": round(net.bytes_sent / (1024**2), 2),
            "bytes_recv_mb": round(net.bytes_recv / (1024**2), 2),
            "packets_sent": net.packets_sent,
            "packets_recv": net.packets_recv,
        },
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/system/history")
async def system_history(
    hours: int = Query(24, ge=1, le=720),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    since = datetime.now() - timedelta(hours=hours)
    result = await db.execute(
        select(AuditLog)
        .where(AuditLog.created_at >= since)
        .where(AuditLog.action.in_(["system_metric"]))
        .order_by(AuditLog.created_at.asc())
    )
    logs = result.scalars().all()
    timestamps = []
    cpu_vals = []
    memory_vals = []
    disk_vals = []
    for log in logs:
        details = log.details or {}
        timestamps.append(log.created_at.isoformat() if hasattr(log.created_at, 'isoformat') else str(log.created_at))
        cpu_vals.append(details.get("cpu_percent", details.get("cpu", {}).get("percent", 0)))
        memory_vals.append(details.get("memory_percent", details.get("memory", {}).get("percent", 0)))
        disk_vals.append(details.get("disk_percent", details.get("disk", {}).get("percent", 0)))
    return {
        "period_hours": hours,
        "data_points": len(logs),
        "metrics": [log.details for log in logs if log.details],
        "timestamps": timestamps,
        "cpu": cpu_vals,
        "memory": memory_vals,
        "disk": disk_vals,
    }


@router.get("/mail/traffic")
async def mail_traffic(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    from app.models.domain import Domain
    total_mailboxes = await db.scalar(select(func.count(Mailbox.id)))
    active_mailboxes = await db.scalar(
        select(func.count(Mailbox.id)).where(Mailbox.is_active == True)
    )
    total_quota = await db.scalar(select(func.sum(Mailbox.quota_limit_mb)))
    total_used = await db.scalar(select(func.sum(Mailbox.quota_used_mb)))
    total_q = total_quota or 0
    total_u = total_used or 0
    domains_count = await db.scalar(select(func.count(Domain.id)))
    return {
        "total_mailboxes": total_mailboxes or 0,
        "active_mailboxes": active_mailboxes or 0,
        "total_quota_mb": total_q,
        "total_used_mb": total_u,
        "total_quota_limit_gb": round(total_q / 1024, 2),
        "total_quota_used_gb": round(total_u / 1024, 2),
        "domains_count": domains_count or 0,
        "timestamp": datetime.now().isoformat(),
    }


@router.get("/mail/queue-size")
async def mail_queue_size(
    current_user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    import subprocess, re
    try:
        result = await asyncio.to_thread(lambda: subprocess.run(
            ["postqueue", "-p"],
            capture_output=True,
            text=True,
            timeout=5,
        ))
        lines = result.stdout.strip().split("\n")
        size_match = next((l for l in lines if "requests" in l or "Kbytes" in l), "")
        queue_count = 0
        size_m = re.search(r"(\d+)\s+request", size_match)
        if size_m:
            queue_count = int(size_m.group(1))
        return {
            "queue_size": queue_count,
            "raw_lines": lines[:10],
            "timestamp": datetime.now().isoformat(),
        }
    except Exception as e:
        return {"queue_size": -1, "error": str(e), "timestamp": datetime.now().isoformat()}
