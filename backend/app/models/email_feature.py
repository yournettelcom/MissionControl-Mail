# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Text, Boolean, DateTime, JSON

from app.core.database import Base


class EmailTemplate(Base):
    __tablename__ = "email_templates"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    name = Column(String(255), nullable=False)
    subject = Column(String(500), nullable=False)
    body = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)


class UndoSend(Base):
    __tablename__ = "undo_send"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    message_id = Column(String(255), nullable=False, unique=True)
    to_addrs = Column(JSON, nullable=True)
    cc_addrs = Column(JSON, nullable=True)
    bcc_addrs = Column(JSON, nullable=True)
    subject = Column(String(500), nullable=True)
    body_text = Column(Text, nullable=True)
    body_html = Column(Text, nullable=True)
    scheduled_at = Column(DateTime, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    status = Column(String(20), default="pending")


class SnoozedMessage(Base):
    __tablename__ = "snoozed_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, nullable=False, index=True)
    message_uid = Column(String(50), nullable=False)
    mailbox = Column(String(255), default="INBOX")
    snooze_until = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc), nullable=False)
