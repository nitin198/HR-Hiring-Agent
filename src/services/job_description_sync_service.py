"""Job description sync service for external sources."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.database.models import JobDescription
from src.services.idsil_openings_service import IDSilOpeningsService


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_title_key(title: str | None) -> str:
    return " ".join((title or "").strip().lower().split())


class JobDescriptionSyncState:
    """In-memory sync state for status endpoint and UI."""

    _last_idsil_sync: dict[str, Any] = {
        "source": "idsil",
        "status": "idle",
        "message": "Sync has not run yet.",
        "last_run_at": None,
        "created": 0,
        "duplicates_skipped": 0,
        "invalid_skipped": 0,
        "processed": 0,
        "total_received": 0,
        "trigger": None,
    }

    @classmethod
    def set_idsil_status(cls, payload: dict[str, Any]) -> None:
        cls._last_idsil_sync = payload

    @classmethod
    def get_idsil_status(cls) -> dict[str, Any]:
        return dict(cls._last_idsil_sync)


class JobDescriptionSyncService:
    """Sync service for job descriptions."""

    SOURCE_SYSTEM = "idsil"

    async def sync_idsil_openings(
        self,
        db: AsyncSession,
        *,
        limit: int = 200,
        trigger: str = "manual",
    ) -> dict[str, Any]:
        started_at = _utc_now_iso()
        limit = max(1, min(limit, 500))

        openings_service = IDSilOpeningsService()
        try:
            raw_openings = await openings_service.fetch_openings()
        except Exception as exc:
            failed = {
                "source": self.SOURCE_SYSTEM,
                "status": "failed",
                "message": f"Failed to fetch openings: {exc}",
                "last_run_at": _utc_now_iso(),
                "started_at": started_at,
                "finished_at": _utc_now_iso(),
                "created": 0,
                "duplicates_skipped": 0,
                "invalid_skipped": 0,
                "processed": 0,
                "total_received": 0,
                "trigger": trigger,
            }
            JobDescriptionSyncState.set_idsil_status(failed)
            raise

        existing_rows = await db.execute(select(JobDescription))
        existing_jds = existing_rows.scalars().all()

        existing_source_keys: set[str] = set()
        existing_title_keys: set[str] = set()

        for jd in existing_jds:
            title_key = _normalize_title_key(jd.title)
            if title_key:
                existing_title_keys.add(title_key)
            if jd.source_system and jd.source_key and jd.source_system.strip().lower() == self.SOURCE_SYSTEM:
                existing_source_keys.add(jd.source_key.strip().lower())

        created = 0
        duplicates_skipped = 0
        invalid_skipped = 0
        processed = 0

        for raw in raw_openings[:limit]:
            processed += 1
            if not isinstance(raw, dict):
                invalid_skipped += 1
                continue

            normalized = openings_service.normalize_opening(raw)
            if normalized is None:
                invalid_skipped += 1
                continue

            title_key = _normalize_title_key(normalized.title)
            source_key = (normalized.source_key or "").strip().lower()

            is_duplicate = False
            if source_key and source_key in existing_source_keys:
                is_duplicate = True
            elif title_key in existing_title_keys:
                is_duplicate = True

            if is_duplicate:
                duplicates_skipped += 1
                continue

            db.add(
                JobDescription(
                    title=normalized.title,
                    description=normalized.description,
                    required_skills=normalized.required_skills,
                    min_experience_years=normalized.min_experience_years,
                    domain=normalized.domain,
                    source_system=self.SOURCE_SYSTEM,
                    source_key=normalized.source_key,
                )
            )
            created += 1

            if title_key:
                existing_title_keys.add(title_key)
            if source_key:
                existing_source_keys.add(source_key)

        await db.commit()

        result = {
            "source": self.SOURCE_SYSTEM,
            "status": "success",
            "message": "IDSIL openings sync completed.",
            "last_run_at": _utc_now_iso(),
            "started_at": started_at,
            "finished_at": _utc_now_iso(),
            "created": created,
            "duplicates_skipped": duplicates_skipped,
            "invalid_skipped": invalid_skipped,
            "processed": processed,
            "total_received": len(raw_openings),
            "trigger": trigger,
        }
        JobDescriptionSyncState.set_idsil_status(result)
        return result
