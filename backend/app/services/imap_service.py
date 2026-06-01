# =============================================================================
# MissionControl - Mail Server Manager
# Copyright (c) 2026 Your Net Tech
# Developed by Jose Rinaldi
# All rights reserved.
# Unauthorized use, reproduction, or distribution is strictly prohibited
# without written permission from Your Net Tech.
# =============================================================================

import asyncio
import email
import imaplib
import logging
import re
import smtplib
import ssl
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any, Optional

logger = logging.getLogger(__name__)

IMAP_HOST = "127.0.0.1"
IMAP_PORT = 993
SMTP_HOST = "127.0.0.1"
SMTP_PORT = 25
IMAP_TIMEOUT = 30
SMTP_TIMEOUT = 30


class ImapService:
    async def fetch_mailboxes(self, username: str, password: str) -> list[dict]:
        return await asyncio.to_thread(self._sync_fetch_mailboxes, username, password)

    def _sync_fetch_mailboxes(self, username: str, password: str) -> list[dict]:
        mailboxes = []
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx, timeout=IMAP_TIMEOUT)
            conn.login(username, password)
            rc, data = conn.list()
            if rc == "OK":
                for line in data:
                    if isinstance(line, bytes):
                        decoded = line.decode("utf-8", errors="replace")
                        parts = decoded.split(' "/" ')
                        if len(parts) >= 2:
                            mailbox_name = parts[-1].strip('"')
                            attrs = []
                            if "\\Noselect" not in decoded and "\\HasNoChildren" in decoded:
                                pass
                            mailboxes.append({
                                "name": mailbox_name,
                                "delimiter": "/",
                                "flags": attrs,
                            })
            conn.logout()
        except Exception as e:
            logger.error("Error fetching mailboxes: %s", e)
        return mailboxes

    async def fetch_emails(
        self, username: str, password: str, mailbox: str = "INBOX",
        limit: int = 50, offset: int = 0,
    ) -> dict:
        return await asyncio.to_thread(
            self._sync_fetch_emails, username, password, mailbox, limit, offset,
        )

    def _sync_fetch_emails(
        self, username: str, password: str, mailbox: str,
        limit: int, offset: int,
    ) -> dict:
        result: dict[str, Any] = {"messages": [], "total": 0, "page": 0}
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx, timeout=IMAP_TIMEOUT)
            conn.login(username, password)
            rc, data = conn.select(mailbox, readonly=True)
            if rc != "OK":
                conn.logout()
                return result

            result["total"] = int(data[0]) if data and data[0] else 0
            end = result["total"] - offset
            start = max(1, end - limit + 1)
            result["page"] = offset // limit + 1

            if start > end:
                conn.logout()
                return result

            rc, data = conn.fetch(f"{start}:{end}", "(FLAGS BODY.PEEK[HEADER])")
            if rc == "OK":
                for i in range(len(data) - 1, -1, -1):
                    if isinstance(data[i], tuple):
                        raw = data[i][1]
                        if isinstance(raw, bytes):
                            msg = email.message_from_bytes(raw)
                            uid_match = re.search(rb"UID\s+(\d+)", data[i][0] if isinstance(data[i][0], bytes) else b"")
                            uid = uid_match.group(1).decode() if uid_match else str(end - i + 1)
                            result["messages"].append({
                                "uid": uid,
                                "subject": msg.get("Subject", "(Sem assunto)"),
                                "from": msg.get("From", ""),
                                "to": msg.get("To", ""),
                                "date": msg.get("Date", ""),
                                "flags": [],
                            })

            conn.logout()
        except Exception as e:
            logger.error("Error fetching emails: %s", e)
        return result

    async def fetch_email_body(
        self, username: str, password: str, uid: str, mailbox: str = "INBOX",
    ) -> dict:
        return await asyncio.to_thread(
            self._sync_fetch_body, username, password, uid, mailbox,
        )

    def _sync_fetch_body(self, username: str, password: str, uid: str, mailbox: str) -> dict:
        result: dict[str, Any] = {"headers": {}, "body_html": "", "body_text": "", "attachments": []}
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx, timeout=IMAP_TIMEOUT)
            conn.login(username, password)
            conn.select(mailbox, readonly=True)

            rc, data = conn.uid("FETCH", uid, "(BODY[])")
            if rc == "OK" and data and isinstance(data[0], tuple):
                raw_email = data[0][1]
                if isinstance(raw_email, bytes):
                    msg = email.message_from_bytes(raw_email)
                    result["headers"] = {
                        "subject": msg.get("Subject", ""),
                        "from": msg.get("From", ""),
                        "to": msg.get("To", ""),
                        "cc": msg.get("Cc", ""),
                        "date": msg.get("Date", ""),
                        "message_id": msg.get("Message-ID", ""),
                        "in_reply_to": msg.get("In-Reply-To", ""),
                        "references": msg.get("References", ""),
                    }

                    if msg.is_multipart():
                        for part in msg.walk():
                            ctype = part.get_content_type()
                            cdisp = str(part.get("Content-Disposition", ""))
                            if "attachment" in cdisp:
                                filename = part.get_filename() or f"attachment_{len(result['attachments'])}"
                                payload = part.get_payload(decode=True)
                                result["attachments"].append({
                                    "filename": filename,
                                    "size": len(payload) if payload else 0,
                                    "mime": ctype,
                                })
                            elif ctype == "text/plain":
                                payload = part.get_payload(decode=True)
                                if payload:
                                    result["body_text"] = payload.decode("utf-8", errors="replace")
                            elif ctype == "text/html":
                                payload = part.get_payload(decode=True)
                                if payload:
                                    result["body_html"] = payload.decode("utf-8", errors="replace")
                    else:
                        payload = msg.get_payload(decode=True)
                        if payload:
                            ctype = msg.get_content_type()
                            decoded = payload.decode("utf-8", errors="replace")
                            if ctype == "text/html":
                                result["body_html"] = decoded
                            else:
                                result["body_text"] = decoded

            conn.logout()
        except Exception as e:
            logger.error("Error fetching body: %s", e)
        return result

    async def save_draft(
        self, username: str, password: str,
        to_list: list[str], cc_list: list[str], subject: str,
        body_text: str, body_html: Optional[str] = None,
    ) -> bool:
        return await asyncio.to_thread(
            self._sync_save_draft, username, password, to_list, cc_list, subject, body_text, body_html,
        )

    def _sync_save_draft(
        self, username: str, password: str,
        to_list: list[str], cc_list: list[str], subject: str,
        body_text: str, body_html: Optional[str],
    ) -> bool:
        try:
            msg = MIMEMultipart("alternative") if body_html else MIMEText(body_text, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = username
            if to_list:
                msg["To"] = ", ".join(to_list)
            if cc_list:
                msg["Cc"] = ", ".join(cc_list)
            msg["Date"] = email.utils.formatdate(localtime=True)
            msg["X-Draft"] = "true"
            if body_html:
                msg.attach(MIMEText(body_text, "plain", "utf-8"))
                msg.attach(MIMEText(body_html, "html", "utf-8"))
            raw = msg.as_bytes()
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT, ssl_context=ctx, timeout=IMAP_TIMEOUT)
            conn.login(username, password)
            conn.append("Drafts", "\\Draft", datetime.now(), raw)
            conn.logout()
            return True
        except Exception as e:
            logger.error("Error saving draft: %s", e)
            return False

    async def send_email(
        self, username: str, password: str,
        to: list[str], subject: str, body_text: str, body_html: Optional[str] = None,
        cc: Optional[list[str]] = None, bcc: Optional[list[str]] = None,
        in_reply_to: Optional[str] = None, references: Optional[str] = None,
    ) -> bool:
        return await asyncio.to_thread(
            self._sync_send, username, password, to, subject, body_text, body_html,
            cc or [], bcc or [], in_reply_to, references,
        )

    def _sync_send(
        self, username: str, password: str,
        to: list[str], subject: str, body_text: str, body_html: Optional[str],
        cc: list[str], bcc: list[str],
        in_reply_to: Optional[str], references: Optional[str],
    ) -> bool:
        try:
            msg = MIMEMultipart("alternative") if body_html else MIMEText(body_text, "plain", "utf-8")
            msg["Subject"] = subject
            msg["From"] = username
            msg["To"] = ", ".join(to)
            if cc:
                msg["Cc"] = ", ".join(cc)
            msg["Date"] = email.utils.formatdate(localtime=True)
            if in_reply_to:
                msg["In-Reply-To"] = in_reply_to
            if references:
                msg["References"] = references
            msg["Message-ID"] = email.utils.make_msgid(domain=username.split("@")[-1] if "@" in username else "localhost")

            if body_html:
                msg.attach(MIMEText(body_text, "plain", "utf-8"))
                msg.attach(MIMEText(body_html, "html", "utf-8"))

            all_recipients = to + cc + bcc
            conn = smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=SMTP_TIMEOUT)
            if SMTP_HOST in ("127.0.0.1", "localhost"):
                conn.login(username, password)
            else:
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                conn.starttls(context=ctx)
                conn.login(username, password)
            conn.sendmail(username, all_recipients, msg.as_string())
            conn.quit()
            return True
        except Exception as e:
            logger.error("Error sending email: %s", e)
            return False
