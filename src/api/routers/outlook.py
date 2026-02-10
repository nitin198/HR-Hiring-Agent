"""Router for Outlook ingestion endpoints."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    CandidateResponse,
    OutlookAttachRequest,
    OutlookCandidateResponse,
    OutlookIngestResponse,
)
from src.config.settings import get_settings
from src.database.connection import get_db
from src.database.models import Candidate, JobDescription, OutlookCandidate
from src.services.graph_client import DeviceCodePendingError, DeviceCodeRequiredError, GraphClient
from src.services.outlook_ingestion_service import OutlookIngestionService
from src.services.imap_ingestion_service import ImapIngestionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/outlook", tags=["Outlook"])


def _validate_outlook_settings() -> None:
    settings = get_settings()
    if not settings.outlook_enabled:
        raise HTTPException(status_code=400, detail="Outlook ingestion is disabled.")
    if not settings.outlook_tenant_id or not settings.outlook_client_id:
        raise HTTPException(status_code=400, detail="Outlook Graph credentials are not configured.")
    if settings.outlook_auth_mode == "client_credentials" and not settings.outlook_client_secret:
        raise HTTPException(status_code=400, detail="OUTLOOK_CLIENT_SECRET is required for client credentials.")


def _validate_imap_settings() -> None:
    settings = get_settings()
    if not settings.outlook_imap_enabled:
        raise HTTPException(status_code=400, detail="IMAP ingestion is disabled.")
    if not settings.outlook_imap_host or not settings.outlook_imap_user or not settings.outlook_imap_password:
        raise HTTPException(status_code=400, detail="IMAP credentials are not configured.")


@router.post("/ingest", response_model=OutlookIngestResponse)
async def ingest_outlook_candidates(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OutlookIngestResponse:
    """Fetch unread Outlook resumes and store as Outlook candidates."""
    _validate_outlook_settings()

    service = OutlookIngestionService()
    try:
        result = await service.ingest_unread(db)
        return OutlookIngestResponse(status="complete", **result.__dict__)
    except DeviceCodeRequiredError:
        settings = get_settings()
        message = await GraphClient.start_device_flow(
            tenant_id=settings.outlook_tenant_id,
            client_id=settings.outlook_client_id,
            scopes=settings.outlook_device_scopes,
        )
        return OutlookIngestResponse(
            status="device_code_required",
            processed_messages=0,
            processed_attachments=0,
            created_candidates=0,
            skipped_candidates=0,
            errors=[],
            device_code_message=message,
        )
    except DeviceCodePendingError:
        return OutlookIngestResponse(
            status="device_code_pending",
            processed_messages=0,
            processed_attachments=0,
            created_candidates=0,
            skipped_candidates=0,
            errors=[],
            device_code_message=GraphClient.get_device_flow_message(),
        )


@router.post("/imap/ingest", response_model=OutlookIngestResponse)
async def ingest_imap_candidates(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> OutlookIngestResponse:
    """Fetch unread IMAP resumes and store as Outlook candidates."""
    _validate_imap_settings()

    service = ImapIngestionService()
    result = await service.ingest_unread(db)
    return OutlookIngestResponse(status="complete", **result.__dict__)


@router.get("/candidates", response_model=list[OutlookCandidateResponse])
async def list_outlook_candidates(
    db: Annotated[AsyncSession, Depends(get_db)],
    include_linked: bool = True,
) -> list[dict]:
    """List Outlook-ingested candidates."""
    query = select(OutlookCandidate).order_by(OutlookCandidate.created_at.desc())
    if not include_linked:
        query = query.where(OutlookCandidate.linked_candidate_id.is_(None))
    result = await db.execute(query)
    candidates = result.scalars().all()
    return [candidate.to_dict() for candidate in candidates]


@router.post("/attach", response_model=list[CandidateResponse])
async def attach_outlook_candidates(
    payload: OutlookAttachRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> list[dict]:
    """Create standard candidates from Outlook entries for a job description."""
    _validate_outlook_settings()

    jd_result = await db.execute(
        select(JobDescription).where(JobDescription.id == payload.job_description_id)
    )
    job_description = jd_result.scalar_one_or_none()
    if not job_description:
        raise HTTPException(status_code=404, detail="Job description not found")

    created_candidates: list[Candidate] = []
    for outlook_id in payload.outlook_candidate_ids:
        result = await db.execute(
            select(OutlookCandidate).where(OutlookCandidate.id == outlook_id)
        )
        outlook_candidate = result.scalar_one_or_none()
        if not outlook_candidate:
            continue

        if outlook_candidate.linked_candidate_id:
            linked_result = await db.execute(
                select(Candidate).where(Candidate.id == outlook_candidate.linked_candidate_id)
            )
            linked_candidate = linked_result.scalar_one_or_none()
            if linked_candidate:
                created_candidates.append(linked_candidate)
            continue

        candidate = Candidate(
            name=outlook_candidate.candidate_name or "Outlook Candidate",
            email=outlook_candidate.candidate_email,
            phone=None,
            resume_text=outlook_candidate.resume_text,
            resume_file_path=outlook_candidate.resume_file_path,
            job_description_id=payload.job_description_id,
        )
        db.add(candidate)
        await db.commit()
        await db.refresh(candidate)

        outlook_candidate.linked_candidate_id = candidate.id
        db.add(outlook_candidate)
        await db.commit()
        await db.refresh(outlook_candidate)

        created_candidates.append(candidate)

    return [candidate.to_dict() for candidate in created_candidates]


@router.get("/candidates/{outlook_id}/resume")
async def download_outlook_resume(
    outlook_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FileResponse:
    """Download a stored Outlook resume attachment."""
    result = await db.execute(select(OutlookCandidate).where(OutlookCandidate.id == outlook_id))
    outlook_candidate = result.scalar_one_or_none()
    if not outlook_candidate or not outlook_candidate.resume_file_path:
        raise HTTPException(status_code=404, detail="Resume not found")

    file_path = Path(outlook_candidate.resume_file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Resume file missing on server")

    return FileResponse(
        path=str(file_path),
        filename=file_path.name,
        media_type="application/octet-stream",
    )
