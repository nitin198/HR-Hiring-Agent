"""Outlook resume ingestion service."""

from __future__ import annotations

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
from src.services.graph_client import GraphClient

logger = logging.getLogger(__name__)


EMAIL_REGEX = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)


@dataclass
class IngestionResult:
    """Summary of ingestion results."""

    processed_messages: int
    processed_attachments: int
    created_candidates: int
    skipped_candidates: int
    errors: list[str]


class OutlookIngestionService:
    """Service to ingest resumes from Outlook."""

    def __init__(self) -> None:
        get_settings.cache_clear()
        self._settings = get_settings()
        self._graph = GraphClient()
        self._classifier = ResumeClassifier()

    async def ingest_unread(self, db: AsyncSession) -> IngestionResult:
        """Ingest unread Outlook emails with resume attachments."""
        if not self._settings.outlook_enabled:
            raise ValueError("Outlook ingestion is disabled. Set OUTLOOK_ENABLED=true to enable.")

        mailbox = self._settings.outlook_user_id
        if self._settings.outlook_auth_mode == "client_credentials" and mailbox == "me":
            raise ValueError("OUTLOOK_USER_ID must be a mailbox UPN/email for client_credentials auth.")
        sender = self._settings.outlook_sender_filter
        max_messages = self._settings.outlook_max_messages
        allowed_ext = self._settings.outlook_allowed_extensions

        errors: list[str] = []
        processed_messages = 0
        processed_attachments = 0
        created_candidates = 0
        skipped_candidates = 0

        filter_query = (
            f"isRead eq false and hasAttachments eq true and from/emailAddress/address eq '{sender}'"
        )
        params = {
            "$filter": filter_query,
            "$top": max_messages,
            "$select": "id,subject,receivedDateTime,from,hasAttachments",
            "$orderby": "receivedDateTime desc",
        }

        logger.info("Fetching unread Outlook messages for sender=%s", sender)
        response = await self._graph.request(
            "GET",
            f"/users/{mailbox}/mailFolders/Inbox/messages",
            params=params,
        )
        messages = response.json().get("value", [])

        for message in messages:
            processed_messages += 1
            message_id = message.get("id")
            subject = message.get("subject") or ""
            received_at = message.get("receivedDateTime")
            sender_email = (
                message.get("from", {})
                .get("emailAddress", {})
                .get("address", "")
            )

            try:
                attachments = await self._fetch_attachments(mailbox, message_id)
                valid_attachments = [
                    att for att in attachments if self._is_allowed_attachment(att, allowed_ext)
                ]

                if not valid_attachments:
                    logger.info("No valid attachments found for message %s", message_id)
                    continue

                successful = 0
                for attachment in valid_attachments:
                    processed_attachments += 1
                    try:
                        created = await self._process_attachment(
                            db,
                            mailbox=mailbox,
                            message_id=message_id,
                            subject=subject,
                            sender_email=sender_email,
                            received_at=received_at,
                            attachment=attachment,
                        )
                        if created:
                            created_candidates += 1
                        else:
                            skipped_candidates += 1
                        successful += 1
                    except Exception as exc:
                        logger.exception("Failed to process attachment: %s", exc)
                        errors.append(str(exc))

                if successful > 0:
                    await self._mark_message_read(mailbox, message_id)

            except Exception as exc:
                logger.exception("Failed to process message %s", message_id)
                errors.append(str(exc))

        return IngestionResult(
            processed_messages=processed_messages,
            processed_attachments=processed_attachments,
            created_candidates=created_candidates,
            skipped_candidates=skipped_candidates,
            errors=errors,
        )

    async def _fetch_attachments(self, mailbox: str, message_id: str) -> list[dict[str, Any]]:
        response = await self._graph.request(
            "GET",
            f"/users/{mailbox}/messages/{message_id}/attachments",
            params={"$select": "id,name,contentType"},
        )
        return response.json().get("value", [])

    async def _mark_message_read(self, mailbox: str, message_id: str) -> None:
        await self._graph.request(
            "PATCH",
            f"/users/{mailbox}/messages/{message_id}",
            json={"isRead": True},
        )
        logger.info("Marked message %s as read", message_id)

    def _is_allowed_attachment(self, attachment: dict[str, Any], allowed_ext: set[str]) -> bool:
        name = (attachment.get("name") or "").lower()
        attachment_type = attachment.get("@odata.type", "")
        if attachment_type and "fileAttachment" not in attachment_type:
            return False
        return any(name.endswith(ext) for ext in allowed_ext)

    async def _process_attachment(
        self,
        db: AsyncSession,
        mailbox: str,
        message_id: str,
        subject: str,
        sender_email: str,
        received_at: str | None,
        attachment: dict[str, Any],
    ) -> bool:
        attachment_id = attachment.get("id")
        attachment_name = attachment.get("name") or "resume"

        existing = await db.execute(
            select(OutlookCandidate)
            .where(OutlookCandidate.source_message_id == message_id)
            .where(OutlookCandidate.source_attachment_id == attachment_id)
        )
        if existing.scalar_one_or_none():
            logger.info("Skipping already ingested attachment %s", attachment_id)
            return False

        content = await self._download_attachment(mailbox, message_id, attachment_id)
        resume_text = ResumeParser.parse_and_clean(attachment_name, content)

        if not resume_text.strip():
            raise ValueError(f"Empty resume text for attachment {attachment_name}")

        classification = await self._classifier.classify_resume(resume_text)
        candidate_name = classification.get("candidate_name") or self._guess_name(resume_text)
        candidate_email = classification.get("candidate_email") or self._guess_email(resume_text)

        storage_path = self._store_attachment(attachment_name, message_id, attachment_id, content)

        outlook_candidate = OutlookCandidate(
            source_message_id=message_id,
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
        logger.info("Stored Outlook candidate %s", outlook_candidate.id)
        return True

    async def _download_attachment(self, mailbox: str, message_id: str, attachment_id: str) -> bytes:
        response = await self._graph.request(
            "GET",
            f"/users/{mailbox}/messages/{message_id}/attachments/{attachment_id}/$value",
        )
        return response.content

    def _store_attachment(self, filename: str, message_id: str, attachment_id: str, content: bytes) -> Path:
        target_dir = Path(self._settings.outlook_attachment_dir)
        target_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", filename)
        prefix = f"{message_id[:8]}_{attachment_id[:8]}_"
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
