"""IMAP-based Outlook resume ingestion service."""

from __future__ import annotations

import asyncio
import email
from email.header import decode_header, make_header
from email.message import Message
from email.utils import parseaddr
import imaplib
import logging
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.config.settings import get_settings
from src.database.models import OutlookCandidate
from src.llm.resume_classifier import ResumeClassifier
from src.parsers.resume_parser import ResumeParser

logger = logging.getLogger(__name__)

EMAIL_REGEX = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


@dataclass
class ImapIngestionResult:
    """Summary of IMAP ingestion results."""

    processed_messages: int
    processed_attachments: int
    created_candidates: int
    skipped_candidates: int
    errors: list[str]


class ImapIngestionService:
    """Service to ingest resumes from Outlook via IMAP."""

    def __init__(self) -> None:
        get_settings.cache_clear()
        self._settings = get_settings()
        self._classifier = ResumeClassifier()

    async def ingest_unread(self, db: AsyncSession) -> ImapIngestionResult:
        """Ingest unread IMAP emails with resume attachments."""
        if not self._settings.outlook_imap_enabled:
            raise ValueError("IMAP ingestion is disabled. Set OUTLOOK_IMAP_ENABLED=true to enable.")

        host = self._settings.outlook_imap_host
        user = self._settings.outlook_imap_user
        password = self._settings.outlook_imap_password
        folder = self._settings.outlook_imap_folder
        use_ssl = self._settings.outlook_imap_use_ssl
        sender = self._settings.outlook_sender_filter
        allowed_ext = self._settings.outlook_allowed_extensions

        if not host or not user or not password:
            raise ValueError("IMAP credentials are not configured.")

        logger.info(
            "IMAP ingest starting: host=%s port=%s user=%s folder=%s ssl=%s sender_filter=%s",
            host,
            self._settings.outlook_imap_port,
            user,
            folder,
            use_ssl,
            sender or "None",
        )

        messages = await asyncio.to_thread(
            self._fetch_unread_messages,
            host=host,
            user=user,
            password=password,
            folder=folder,
            use_ssl=use_ssl,
            sender=sender,
        )

        errors: list[str] = []
        processed_messages = 0
        processed_attachments = 0
        created_candidates = 0
        skipped_candidates = 0

        for message in messages:
            processed_messages += 1
            uid = message["uid"]
            subject = message["subject"]
            sender_email = message["sender_email"]
            received_at = message["received_at"]
            attachments = message["attachments"]

            if not attachments:
                continue

            successful = 0
            for index, attachment in enumerate(attachments, start=1):
                processed_attachments += 1
                filename = attachment["filename"]
                if not self._is_allowed_attachment(filename, allowed_ext):
                    continue
                try:
                    created = await self._process_attachment(
                        db=db,
                        message_uid=uid,
                        attachment_id=f"{uid}:{index}",
                        subject=subject,
                        sender_email=sender_email,
                        received_at=received_at,
                        attachment_name=filename,
                        content=attachment["content"],
                    )
                    if created:
                        created_candidates += 1
                    else:
                        skipped_candidates += 1
                    successful += 1
                except Exception as exc:
                    logger.exception("Failed to process IMAP attachment: %s", exc)
                    errors.append(str(exc))

            if successful > 0:
                await asyncio.to_thread(
                    self._mark_message_read,
                    host=host,
                    user=user,
                    password=password,
                    folder=folder,
                    use_ssl=use_ssl,
                    uid=uid,
                )

        return ImapIngestionResult(
            processed_messages=processed_messages,
            processed_attachments=processed_attachments,
            created_candidates=created_candidates,
            skipped_candidates=skipped_candidates,
            errors=errors,
        )

    def _fetch_unread_messages(
        self,
        host: str,
        user: str,
        password: str,
        folder: str,
        use_ssl: bool,
        sender: str | None,
    ) -> list[dict[str, Any]]:
        imap = self._connect(host, user, password, use_ssl)
        try:
            imap.select(folder)
            criteria = ["UNSEEN"]
            if sender:
                criteria += ["FROM", f"\"{sender}\""]

            status, data = imap.search(None, *criteria)
            if status != "OK":
                logger.warning("IMAP search failed: status=%s criteria=%s", status, " ".join(criteria))
                return []

            uids = data[0].split()
            messages: list[dict[str, Any]] = []

            for uid in uids:
                status, msg_data = imap.fetch(uid, "(RFC822)")
                if status != "OK" or not msg_data:
                    continue
                raw = msg_data[0][1]
                msg = email.message_from_bytes(raw)

                subject = self._decode_header_value(msg.get("Subject"))
                sender_email = parseaddr(msg.get("From"))[1]
                received_at = self._decode_header_value(msg.get("Date"))

                attachments = self._extract_attachments(msg)

                messages.append(
                    {
                        "uid": uid.decode() if isinstance(uid, bytes) else str(uid),
                        "subject": subject or "",
                        "sender_email": sender_email or "",
                        "received_at": received_at,
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
        try:
            imap = imaplib.IMAP4_SSL(host) if use_ssl else imaplib.IMAP4(host)
            imap.login(user, password)
            return imap
        except imaplib.IMAP4.error as exc:
            logger.error("IMAP login failed for user=%s host=%s: %s", user, host, exc)
            raise

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
            filename = ImapIngestionService._decode_header_value(filename) or "attachment"
            content = part.get_payload(decode=True)
            if not content:
                continue
            attachments.append({"filename": filename, "content": content})
        return attachments

    @staticmethod
    def _is_allowed_attachment(filename: str, allowed_ext: set[str]) -> bool:
        name = filename.lower()
        return any(name.endswith(ext) for ext in allowed_ext)

    async def _process_attachment(
        self,
        db: AsyncSession,
        message_uid: str,
        attachment_id: str,
        subject: str,
        sender_email: str,
        received_at: str | None,
        attachment_name: str,
        content: bytes,
    ) -> bool:
        existing = await db.execute(
            select(OutlookCandidate)
            .where(OutlookCandidate.source_message_id == message_uid)
            .where(OutlookCandidate.source_attachment_id == attachment_id)
        )
        if existing.scalar_one_or_none():
            logger.info("Skipping already ingested IMAP attachment %s", attachment_id)
            return False

        resume_text = ResumeParser.parse_and_clean(attachment_name, content)
        if not resume_text.strip():
            raise ValueError(f"Empty resume text for attachment {attachment_name}")

        classification = await self._classifier.classify_resume(resume_text)
        candidate_name = classification.get("candidate_name") or self._guess_name(resume_text)
        candidate_email = classification.get("candidate_email") or self._guess_email(resume_text)

        storage_path = self._store_attachment(attachment_name, message_uid, attachment_id, content)

        outlook_candidate = OutlookCandidate(
            source_message_id=message_uid,
            source_attachment_id=attachment_id,
            sender_email=sender_email,
            email_subject=subject,
            received_at=received_at,
            candidate_name=candidate_name,
            candidate_email=candidate_email,
            tech_stack=classification.get("tech_stack", []),
            job_category=classification.get("job_category"),
            seniority=classification.get("seniority"),
            resume_text=resume_text,
            resume_file_path=str(storage_path),
        )

        db.add(outlook_candidate)
        await db.commit()
        await db.refresh(outlook_candidate)
        logger.info("Stored IMAP Outlook candidate %s", outlook_candidate.id)
        return True

    def _store_attachment(self, filename: str, message_uid: str, attachment_id: str, content: bytes) -> Path:
        target_dir = Path(self._settings.outlook_attachment_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
        prefix = f"{message_uid[:8]}_{attachment_id[:8]}_"
        full_path = target_dir / safe_name
        if not full_path.name.startswith(prefix):
            full_path = target_dir / f"{prefix}{safe_name}"
        full_path.write_bytes(content)
        return full_path

    @staticmethod
    def _guess_email(resume_text: str) -> str | None:
        match = EMAIL_REGEX.search(resume_text)
        return match.group(0) if match else None

    @staticmethod
    def _guess_name(resume_text: str) -> str | None:
        lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
        return lines[0] if lines else None
