# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional
import hashlib
import hmac
import base64
import struct
import time

from jose import jwt, JWTError
import bcrypt
from cryptography.fernet import Fernet

from app.core.config import settings



def _get_fernet() -> Fernet:
    key = base64.urlsafe_b64encode(settings.SECRET_KEY.encode("utf-8").ljust(32)[:32])
    return Fernet(key)


def encrypt_password(plain_password: str) -> str:
    return _get_fernet().encrypt(plain_password.encode("utf-8")).decode("utf-8")


def decrypt_password(encrypted_password: str) -> str:
    return _get_fernet().decrypt(encrypted_password.encode("utf-8")).decode("utf-8")


def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    to_encode.update({"exp": expire, "type": "access"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_refresh_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def verify_token(token: str) -> Optional[Dict[str, Any]]:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        return payload
    except JWTError:
        return None


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def generate_totp_secret() -> str:
    return base64.b32encode(os.urandom(20)).decode("utf-8")


def verify_totp(secret: str, code: str, drift: int = 1) -> bool:
    if not secret or not code:
        return False
    try:
        code_int = int(code)
    except (ValueError, TypeError):
        return False
    secret_bytes = base64.b32decode(secret.encode("utf-8"), casefold=True)
    for offset in range(-drift, drift + 1):
        expected = _generate_totp(secret_bytes, time.time() + offset * 30)
        if hmac.compare_digest(str(expected), str(code_int)):
            return True
    return False


def _generate_totp(key: bytes, timestamp: float, digits: int = 6) -> int:
    counter = int(timestamp / 30)
    counter_bytes = struct.pack(">Q", counter)
    h = hmac.new(key, counter_bytes, hashlib.sha1).digest()
    offset = h[19] & 0x0F
    code = (
        (h[offset] & 0x7F) << 24
        | (h[offset + 1] & 0xFF) << 16
        | (h[offset + 2] & 0xFF) << 8
        | (h[offset + 3] & 0xFF)
    ) % (10 ** digits)
    return code
