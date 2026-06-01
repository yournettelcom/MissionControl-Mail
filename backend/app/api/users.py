# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import hash_password
from app.api.deps import get_current_user, require_admin
from app.models.user import User, Role, user_roles
from app.schemas.user import UserCreate, UserUpdate, UserResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/users", tags=["Users"])


@router.get("/", response_model=List[UserResponse])
async def list_users(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).offset(skip).limit(limit).options(selectinload(User.roles)))
    users = result.scalars().all()
    responses = []
    for u in users:
        role_names = [r.name for r in u.roles]
        responses.append(UserResponse(
            id=u.id,
            username=u.username,
            email=u.email,
            full_name=u.full_name,
            is_active=u.is_active,
            is_superadmin=u.is_superadmin,
            totp_enabled=bool(u.totp_secret),
            roles=role_names,
            created_at=u.created_at,
            updated_at=u.updated_at,
        ))
    return responses


@router.post("/", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def create_user(
    data: UserCreate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    existing = await db.execute(
        select(User).where((User.username == data.username) | (User.email == data.email))
    )
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username or email already exists")

    user = User(
        username=data.username,
        email=data.email,
        hashed_password=hash_password(data.password),
        full_name=data.full_name,
        is_active=True if data.is_active is None else data.is_active,
        is_superadmin=data.is_superadmin or False,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(user)
    await db.flush()

    if data.role_ids:
        result = await db.execute(select(Role).where(Role.id.in_(data.role_ids)))
        roles = result.scalars().all()
        user.roles = roles
        await db.flush()
        role_names = [r.name for r in roles]
    else:
        role_names = []
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superadmin=user.is_superadmin,
        totp_enabled=False,
        roles=role_names,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.get("/{user_id}", response_model=UserResponse)
async def get_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.id != user_id and not current_user.is_superadmin:
        raise HTTPException(status_code=403, detail="Not authorized")
    result = await db.execute(select(User).where(User.id == user_id).options(selectinload(User.roles)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    role_names = [r.name for r in user.roles]
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superadmin=user.is_superadmin,
        totp_enabled=bool(user.totp_secret),
        roles=role_names,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.put("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: int,
    data: UserUpdate,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.id == user_id).options(selectinload(User.roles)))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")

    update_data = data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        if field == "role_ids" and value is not None:
            r_result = await db.execute(select(Role).where(Role.id.in_(value)))
            user.roles = r_result.scalars().all()
        elif field != "role_ids":
            setattr(user, field, value)
    user.updated_at = datetime.now(timezone.utc)
    db.add(user)
    await db.flush()

    role_names = [r.name for r in user.roles]
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        full_name=user.full_name,
        is_active=user.is_active,
        is_superadmin=user.is_superadmin,
        totp_enabled=bool(user.totp_secret),
        roles=role_names,
        created_at=user.created_at,
        updated_at=user.updated_at,
    )


@router.delete("/{user_id}")
async def delete_user(
    user_id: int,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if user.is_superadmin:
        raise HTTPException(status_code=400, detail="Cannot delete superadmin")
    await db.delete(user)
    await db.flush()
    return {"message": "User deleted successfully"}
