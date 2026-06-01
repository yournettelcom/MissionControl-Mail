# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import logging
from typing import Dict, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.api.deps import get_current_user, require_admin
from app.models.user import User
from app.services.health_service import HealthService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/health", tags=["Health"])


@router.get("/check")
async def health_check(
    current_user: User = Depends(get_current_user),
):
    svc = HealthService()
    return await svc.full_health_check()


@router.post("/repair")
async def auto_repair(
    current_user: User = Depends(require_admin),
):
    svc = HealthService()
    return await svc.auto_repair()


@router.get("/diagnose-delivery")
async def diagnose_delivery(
    target_email: str = Query(..., description="Email to diagnose delivery to"),
    current_user: User = Depends(require_admin),
):
    svc = HealthService()
    return await svc.diagnose_delivery(target_email)
