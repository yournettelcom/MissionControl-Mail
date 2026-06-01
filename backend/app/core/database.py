# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from sqlalchemy.exc import OperationalError
from sqlalchemy.pool import NullPool
from typing import AsyncGenerator
import logging
import asyncio

from app.core.config import settings

logger = logging.getLogger(__name__)

connect_args = {}
if "sqlite" in settings.DATABASE_URL:
    connect_args["check_same_thread"] = False

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    connect_args=connect_args,
    poolclass=NullPool,
)
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    for attempt in range(2):
        session = async_session_factory()
        try:
            yield session
            await session.commit()
            return
        except OperationalError as e:
            if attempt == 0 and "closed" in str(e).lower():
                logger.warning("DB connection lost, retrying...")
                engine.dispose()
                await asyncio.sleep(1)
                continue
            raise
        except Exception:
            raise
        finally:
            await session.close()


async def init_db():
    for attempt in range(3):
        try:
            async with engine.begin() as conn:
                from app.models import user, domain, mailbox, audit
                await conn.run_sync(Base.metadata.create_all)
            logger.info(f"Database initialized ({settings.database_name})")
            return
        except OperationalError as e:
            if attempt < 2:
                logger.warning(f"DB init attempt {attempt+1} failed: {e}")
                await asyncio.sleep(2)
                continue
            raise
        except Exception as e:
            logger.warning(f"Database init failed: {e}")
            raise
