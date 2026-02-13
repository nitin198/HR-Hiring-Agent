"""Router for Gmail ingestion endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import GmailIngestResponse, GmailLogsResponse
from src.config.settings import get_settings
from src.database.connection import get_db
from src.services.gmail_activity_log import GmailActivityLog
from src.services.gmail_sync_service import GmailSyncService

router = APIRouter(prefix="/gmail", tags=["Gmail"])


def _validate_gmail_settings() -> None:
    settings = get_settings()
    if not settings.gmail_enabled:
        raise HTTPException(status_code=400, detail="Gmail ingestion is disabled.")
    if not settings.gmail_imap_user or not settings.gmail_imap_password:
        raise HTTPException(status_code=400, detail="Gmail IMAP credentials are not configured.")


@router.post("/ingest", response_model=GmailIngestResponse)
async def ingest_gmail_candidates(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GmailIngestResponse:
    """Fetch unread Gmail resumes, add candidates, and auto-analyze matched candidates."""
    _validate_gmail_settings()
    result = await GmailSyncService().sync(db, trigger="manual")
    return GmailIngestResponse(**result.__dict__)


@router.get("/logs", response_model=GmailLogsResponse)
async def list_gmail_logs(
    limit: Annotated[int, Query(ge=1, le=600)] = 200,
) -> GmailLogsResponse:
    """Return recent Gmail sync activity logs."""
    return GmailLogsResponse(logs=GmailActivityLog.list(limit=limit))
