# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi (joserinaldi-l)
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.core.database import get_db
from app.core.security import (
    create_access_token,
    create_refresh_token,
    verify_token,
    hash_password,
    verify_password,
    generate_totp_secret,
    verify_totp,
)
from app.api.deps import get_current_user, require_active
from app.models.user import User, user_roles
from app.schemas.user import (
    LoginRequest,
    TokenResponse,
    RefreshTokenRequest,
    ChangePasswordRequest,
    UserResponse,
    UserCreate,
    UserUpdate,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/auth", tags=["Authentication"])


@router.post("/login", response_model=TokenResponse)
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    login_id = request.username or request.email or ""
    result = await db.execute(
        select(User).where(
            (User.username == login_id) | (User.email == login_id)
        ).options(selectinload(User.roles))
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(request.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account is disabled",
        )
    if user.totp_secret:
        if not request.totp_code:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="TOTP code required",
            )
        if not verify_totp(user.totp_secret, request.totp_code):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid TOTP code",
            )
    access_token = create_access_token({"sub": str(user.id), "username": user.username})
    refresh_token = create_refresh_token({"sub": str(user.id), "username": user.username})
    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        user={
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "is_active": user.is_active,
            "is_superadmin": user.is_superadmin,
            "roles": [r.name for r in user.roles],
        },
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    request: RefreshTokenRequest,
    db: AsyncSession = Depends(get_db),
):
    payload = verify_token(request.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
        )
    user_id = payload.get("sub")
    if user_id:
        result = await db.execute(select(User).where(User.id == int(user_id)))
        user = result.scalar_one_or_none()
        if not user:
            raise HTTPException(status_code=401, detail="User no longer exists")
    username = payload.get("username", "")
    access_token = create_access_token({"sub": user_id, "username": username})
    new_refresh_token = create_refresh_token({"sub": user_id, "username": username})
    return TokenResponse(access_token=access_token, refresh_token=new_refresh_token)


@router.post("/logout")
async def logout(current_user: User = Depends(get_current_user)) -> Dict[str, str]:
    return {"message": "Logged out successfully"}


@router.post("/setup-2fa")
async def setup_2fa(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    secret = generate_totp_secret()
    current_user.totp_secret = secret
    db.add(current_user)
    await db.flush()
    return {"secret": secret, "message": "TOTP secret generated. Verify with /verify-2fa."}


@router.post("/verify-2fa")
async def verify_2fa(
    code: str,
    current_user: User = Depends(get_current_user),
) -> Dict[str, str]:
    if not current_user.totp_secret:
        raise HTTPException(status_code=400, detail="TOTP not set up yet")
    if not verify_totp(current_user.totp_secret, code):
        raise HTTPException(status_code=400, detail="Invalid TOTP code")
    return {"message": "TOTP verified successfully"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    role_names = [role.name for role in current_user.roles]
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        is_superadmin=current_user.is_superadmin,
        totp_enabled=bool(current_user.totp_secret),
        roles=role_names,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
    )


@router.put("/me", response_model=UserResponse)
async def update_me(
    update: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if update.username is not None:
        existing = await db.execute(select(User).where(User.username == update.username, User.id != current_user.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Username já está em uso")
        current_user.username = update.username
    if update.email is not None:
        existing = await db.execute(select(User).where(User.email == update.email, User.id != current_user.id))
        if existing.scalar_one_or_none():
            raise HTTPException(status_code=409, detail="Email já está em uso")
        current_user.email = update.email
    if update.full_name is not None:
        current_user.full_name = update.full_name
    current_user.updated_at = datetime.now(timezone.utc)
    db.add(current_user)
    await db.flush()
    role_names = [role.name for role in current_user.roles]
    return UserResponse(
        id=current_user.id,
        username=current_user.username,
        email=current_user.email,
        full_name=current_user.full_name,
        is_active=current_user.is_active,
        is_superadmin=current_user.is_superadmin,
        totp_enabled=bool(current_user.totp_secret),
        roles=role_names,
        created_at=current_user.created_at,
        updated_at=current_user.updated_at,
    )


@router.put("/me/password")
async def change_my_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, str]:
    if not verify_password(request.current_password, current_user.hashed_password):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    current_user.hashed_password = hash_password(request.new_password)
    current_user.updated_at = datetime.now(timezone.utc)
    db.add(current_user)
    await db.flush()
    return {"message": "Password changed successfully"}


@router.post("/setup-admin")
async def setup_admin(
    email: str,
    password: str,
    db: AsyncSession = Depends(get_db),
) -> Dict[str, Any]:
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    from sqlalchemy import func
    count = await db.scalar(select(func.count(User.id)))
    if count and count > 0:
        raise HTTPException(
            status_code=400,
            detail="Admin already exists. Use /login to authenticate.",
        )
    admin = User(
        username="admin",
        email=email,
        hashed_password=hash_password(password),
        full_name="System Administrator",
        is_active=True,
        is_superadmin=True,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    db.add(admin)
    await db.flush()
    access_token = create_access_token({"sub": str(admin.id), "username": admin.username})
    return {
        "message": "Admin user created successfully",
        "email": email,
        "access_token": access_token,
        "warning": "Change this password immediately after first login",
    }
