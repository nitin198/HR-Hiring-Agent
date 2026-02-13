"""Orchestrates Gmail sync, candidate auto-analysis, and activity logs."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.hiring_agent import HiringAgent
from src.database.models import Candidate, CandidateJobLink
from src.services.gmail_activity_log import GmailActivityLog
from src.services.gmail_ingestion_service import GmailIngestionService

logger = logging.getLogger(__name__)


@dataclass
class GmailSyncResult:
    """Summary of sync + analysis execution."""

    status: str
    trigger: str
    processed_messages: int
    processed_attachments: int
    created_candidates: int
    skipped_candidates: int
    analyzed_candidates: int
    no_jd_match_candidates: int
    analysis_errors: int
    errors: list[str]
    imported_candidates: list[dict[str, Any]]


class GmailSyncService:
    """Runs Gmail ingestion and immediate analysis workflow."""

    _sync_lock = asyncio.Lock()

    async def sync(self, db: AsyncSession, *, trigger: str = "manual") -> GmailSyncResult:
        async with self._sync_lock:
            GmailActivityLog.add(
                level="info",
                action="sync_started",
                message=f"Gmail sync started ({trigger}).",
                details={"trigger": trigger},
            )

            ingestion = await GmailIngestionService().ingest_unread(db)

            analyzed_candidates = 0
            no_jd_match_candidates = 0
            analysis_errors = 0
            errors = list(ingestion.errors)
            agent = HiringAgent()

            for candidate_payload in ingestion.imported_candidates:
                candidate_id = candidate_payload.get("id")
                if not candidate_id:
                    continue

                link_result = await db.execute(
                    select(CandidateJobLink)
                    .where(CandidateJobLink.candidate_id == candidate_id)
                    .order_by(CandidateJobLink.confidence.desc(), CandidateJobLink.id.asc())
                )
                best_link = link_result.scalars().first()

                if not best_link:
                    no_jd_match_candidates += 1
                    candidate_result = await db.execute(
                        select(Candidate).where(Candidate.id == candidate_id)
                    )
                    candidate = candidate_result.scalar_one_or_none()
                    candidate_name = candidate.name if candidate else "Unknown"
                    GmailActivityLog.add(
                        level="warning",
                        action="candidate_no_jd_match",
                        message=(
                            f"Candidate {candidate_name} (ID {candidate_id}) added but no JD match found. "
                            "Analysis skipped."
                        ),
                        details={"candidate_id": candidate_id, "candidate_name": candidate_name},
                    )
                    continue

                try:
                    analysis = await agent.analyze_candidate(candidate_id, best_link.job_description_id, db)
                    analyzed_candidates += 1

                    candidate_result = await db.execute(
                        select(Candidate).where(Candidate.id == candidate_id)
                    )
                    candidate = candidate_result.scalar_one_or_none()
                    candidate_name = candidate.name if candidate else str(candidate_id)

                    GmailActivityLog.add(
                        level="info",
                        action="candidate_analyzed",
                        message=(
                            f"Candidate {candidate_name} analyzed against JD {best_link.job_description_id} "
                            f"with decision '{analysis.decision}' and score {analysis.final_score:.2f}."
                        ),
                        details={
                            "candidate_id": candidate_id,
                            "job_description_id": best_link.job_description_id,
                            "decision": analysis.decision,
                            "final_score": analysis.final_score,
                        },
                    )
                except Exception as exc:
                    analysis_errors += 1
                    errors.append(str(exc))
                    logger.exception("Failed to auto-analyze Gmail candidate %s", candidate_id)
                    GmailActivityLog.add(
                        level="error",
                        action="analysis_failed",
                        message=f"Auto-analysis failed for candidate {candidate_id}: {exc}",
                        details={"candidate_id": candidate_id},
                    )

            GmailActivityLog.add(
                level="info",
                action="sync_completed",
                message=(
                    "Gmail sync completed: "
                    f"{ingestion.created_candidates} candidates added, "
                    f"{analyzed_candidates} analyzed, "
                    f"{no_jd_match_candidates} without JD match."
                ),
                details={
                    "trigger": trigger,
                    "created_candidates": ingestion.created_candidates,
                    "analyzed_candidates": analyzed_candidates,
                    "no_jd_match_candidates": no_jd_match_candidates,
                    "processed_messages": ingestion.processed_messages,
                    "processed_attachments": ingestion.processed_attachments,
                    "skipped_candidates": ingestion.skipped_candidates,
                    "analysis_errors": analysis_errors,
                },
            )

            return GmailSyncResult(
                status="complete",
                trigger=trigger,
                processed_messages=ingestion.processed_messages,
                processed_attachments=ingestion.processed_attachments,
                created_candidates=ingestion.created_candidates,
                skipped_candidates=ingestion.skipped_candidates,
                analyzed_candidates=analyzed_candidates,
                no_jd_match_candidates=no_jd_match_candidates,
                analysis_errors=analysis_errors,
                errors=errors,
                imported_candidates=ingestion.imported_candidates,
            )
