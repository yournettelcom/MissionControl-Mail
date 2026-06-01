# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, desc

from app.core.database import get_db
from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.models.audit import AuditLog

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/audit", tags=["Audit"])


@router.get("/logs")
async def get_audit_logs(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    user_id: Optional[int] = None,
    since: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    query = select(AuditLog).order_by(desc(AuditLog.created_at)).offset(offset).limit(limit)
    count_query = select(func.count(AuditLog.id))

    if action:
        query = query.where(AuditLog.action == action)
        count_query = count_query.where(AuditLog.action == action)
    if resource_type:
        query = query.where(AuditLog.resource_type == resource_type)
        count_query = count_query.where(AuditLog.resource_type == resource_type)
    if user_id:
        query = query.where(AuditLog.user_id == user_id)
        count_query = count_query.where(AuditLog.user_id == user_id)
    if since:
        try:
            since_dt = datetime.fromisoformat(since)
            query = query.where(AuditLog.created_at >= since_dt)
            count_query = count_query.where(AuditLog.created_at >= since_dt)
        except ValueError:
            pass

    result = await db.execute(query)
    logs = result.scalars().all()
    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    return {
        "logs": [
            {
                "id": log.id,
                "user_id": log.user_id,
                "action": log.action,
                "resource_type": log.resource_type,
                "resource_id": log.resource_id,
                "details": log.details,
                "ip_address": log.ip_address,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log in logs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
