"""Gmail IMAP resume ingestion service."""

from __future__ import annotations

import asyncio
import email
from email.header import decode_header, make_header
from email.message import Message
import imaplib
import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from src.api.routers.candidates import create_candidate_from_resume_bytes
from src.config.settings import get_settings

logger = logging.getLogger(__name__)


@dataclass
class GmailIngestionResult:
    """Summary of Gmail ingestion results."""

    processed_messages: int
    processed_attachments: int
    created_candidates: int
    skipped_candidates: int
    errors: list[str]
    imported_candidates: list[dict[str, Any]]


class GmailIngestionService:
    """Service to ingest resumes from Gmail via IMAP."""

    def __init__(self) -> None:
        get_settings.cache_clear()
        self._settings = get_settings()

    async def ingest_unread(self, db: AsyncSession) -> GmailIngestionResult:
        """Ingest unread Gmail emails from configured sender with resume attachments."""
        if not self._settings.gmail_enabled:
            raise ValueError("Gmail ingestion is disabled. Set GMAIL_ENABLED=true to enable.")

        host = self._settings.gmail_imap_host
        user = self._settings.gmail_imap_user
        password = self._settings.gmail_imap_password
        folder = self._settings.gmail_imap_folder
        sender = self._settings.gmail_sender_filter
        allowed_ext = self._settings.gmail_allowed_extensions
        max_messages = max(self._settings.gmail_max_messages, 1)

        if not host or not user or not password:
            raise ValueError("Gmail IMAP credentials are not configured.")
        if not sender:
            raise ValueError("Gmail sender filter is not configured.")

        messages = await asyncio.to_thread(
            self._fetch_unread_messages,
            host=host,
            user=user,
            password=password,
            folder=folder,
            use_ssl=self._settings.gmail_imap_use_ssl,
            sender=sender,
            max_messages=max_messages,
        )

        errors: list[str] = []
        imported_candidates: list[dict[str, Any]] = []
        processed_messages = 0
        processed_attachments = 0
        created_candidates = 0
        skipped_candidates = 0

        for message in messages:
            processed_messages += 1
            uid = message["uid"]
            attachments = message["attachments"]
            if not attachments:
                continue

            successful = 0
            for attachment in attachments:
                processed_attachments += 1
                filename = attachment["filename"]
                if not self._is_allowed_attachment(filename, allowed_ext):
                    continue
                try:
                    candidate = await create_candidate_from_resume_bytes(
                        db=db,
                        filename=filename,
                        content=attachment["content"],
                    )
                    if candidate is None:
                        skipped_candidates += 1
                    else:
                        created_candidates += 1
                        imported_candidates.append(candidate.to_dict())
                    successful += 1
                except Exception as exc:
                    logger.exception("Failed to process Gmail attachment: %s", exc)
                    errors.append(str(exc))

            if successful > 0:
                await asyncio.to_thread(
                    self._mark_message_read,
                    host=host,
                    user=user,
                    password=password,
                    folder=folder,
                    use_ssl=self._settings.gmail_imap_use_ssl,
                    uid=uid,
                )

        return GmailIngestionResult(
            processed_messages=processed_messages,
            processed_attachments=processed_attachments,
            created_candidates=created_candidates,
            skipped_candidates=skipped_candidates,
            errors=errors,
            imported_candidates=imported_candidates,
        )

    def _fetch_unread_messages(
        self,
        host: str,
        user: str,
        password: str,
        folder: str,
        use_ssl: bool,
        sender: str,
        max_messages: int,
    ) -> list[dict[str, Any]]:
        imap = self._connect(host, user, password, use_ssl)
        try:
            imap.select(folder)
            status, data = imap.search(None, "UNSEEN", "FROM", f"\"{sender}\"")
            if status != "OK":
                return []

            uids = data[0].split()
            if max_messages > 0:
                uids = uids[-max_messages:]

            messages: list[dict[str, Any]] = []
            for uid in uids:
                status, msg_data = imap.fetch(uid, "(RFC822)")
                if status != "OK" or not msg_data:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)
                attachments = self._extract_attachments(msg)
                messages.append(
                    {
                        "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                        "attachments": attachments,
                    }
                )
            return messages
        finally:
            try:
                imap.close()
            finally:
                imap.logout()

    def _mark_message_read(
        self,
        host: str,
        user: str,
        password: str,
        folder: str,
        use_ssl: bool,
        uid: str,
    ) -> None:
        imap = self._connect(host, user, password, use_ssl)
        try:
            imap.select(folder)
            imap.store(uid, "+FLAGS", "\\Seen")
        finally:
            try:
                imap.close()
            finally:
                imap.logout()

    @staticmethod
    def _connect(host: str, user: str, password: str, use_ssl: bool) -> imaplib.IMAP4:
        imap = imaplib.IMAP4_SSL(host) if use_ssl else imaplib.IMAP4(host)
        imap.login(user, password)
        return imap

    @staticmethod
    def _decode_header_value(value: str | None) -> str | None:
        if not value:
            return None
        try:
            return str(make_header(decode_header(value)))
        except Exception:
            return value

    @staticmethod
    def _extract_attachments(msg: Message) -> list[dict[str, Any]]:
        attachments: list[dict[str, Any]] = []
        for part in msg.walk():
            filename = part.get_filename()
            content_disposition = part.get_content_disposition()
            if not filename and content_disposition != "attachment":
                continue
            decoded_name = GmailIngestionService._decode_header_value(filename) or "attachment"
            content = part.get_payload(decode=True)
            if not content:
                continue
            attachments.append({"filename": decoded_name, "content": content})
        return attachments

    @staticmethod
    def _is_allowed_attachment(filename: str, allowed_ext: set[str]) -> bool:
        lowered = (filename or "").lower()
        return any(lowered.endswith(ext) for ext in allowed_ext)
