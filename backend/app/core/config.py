# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import secrets as _secrets
from pydantic_settings import BaseSettings
from typing import List
import os


class Settings(BaseSettings):
    DATABASE_URL: str = "sqlite+aiosqlite:///./missioncontrol.db"
    SECRET_KEY: str = ""
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    REFRESH_TOKEN_EXPIRE_DAYS: int = 7
    REDIS_URL: str = "redis://localhost:6379/0"
    POSTFIX_CONFIG_DIR: str = "/etc/postfix"
    DOVECOT_CONFIG_DIR: str = "/etc/dovecot"
    ROUNDCUBE_CONFIG_DIR: str = "/etc/roundcube"
    VMAIL_DIR: str = "/var/vmail"
    API_TITLE: str = "MissionControl API"
    API_VERSION: str = "1.0.0"
    CORS_ORIGINS: List[str] = ["http://localhost"]  # Override in .env with explicit origins for production

    model_config = {
        "env_file": (".env", ".secrets.env"),
        "env_file_encoding": "utf-8",
        "case_sensitive": True,
    }

    @property
    def is_mysql(self) -> bool:
        return "mysql" in self.DATABASE_URL

    @property
    def database_name(self) -> str:
        return "mysql" if self.is_mysql else "sqlite"


settings = Settings()

if not settings.SECRET_KEY:
    import logging
    logging.warning("No SECRET_KEY found in environment — authentication tokens will not be persistent")

if settings.CORS_ORIGINS == ["*"]:
    import logging
    logging.warning("CORS_ORIGINS=[\"*\"] allows all origins — restrict in production via .env")
