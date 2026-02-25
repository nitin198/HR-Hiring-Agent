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


def _normalize_source_key(source_key: str | None) -> str:
    return (source_key or "").strip().lower()


class JobDescriptionSyncState:
    """In-memory sync state for status endpoint and UI."""

    _last_idsil_sync: dict[str, Any] = {
        "source": "idsil",
        "status": "idle",
        "message": "Sync has not run yet.",
        "last_run_at": None,
        "created": 0,
        "updated": 0,
        "unchanged": 0,
        "duplicates_skipped": 0,
        "invalid_skipped": 0,
        "processed": 0,
        "total_received": 0,
        "llm_enriched": 0,
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
                "updated": 0,
                "unchanged": 0,
                "duplicates_skipped": 0,
                "invalid_skipped": 0,
                "processed": 0,
                "total_received": 0,
                "llm_enriched": 0,
                "trigger": trigger,
            }
            JobDescriptionSyncState.set_idsil_status(failed)
            raise

        existing_rows = await db.execute(select(JobDescription))
        existing_jds = existing_rows.scalars().all()

        existing_by_source_key: dict[str, JobDescription] = {}
        existing_by_title_key: dict[str, list[JobDescription]] = {}

        for jd in existing_jds:
            title_key = _normalize_title_key(jd.title)
            if title_key:
                existing_by_title_key.setdefault(title_key, []).append(jd)
            source_key = _normalize_source_key(jd.source_key)
            if source_key and jd.source_system and jd.source_system.strip().lower() == self.SOURCE_SYSTEM:
                existing_by_source_key[source_key] = jd

        created = 0
        updated = 0
        unchanged = 0
        duplicates_skipped = 0
        invalid_skipped = 0
        processed = 0
        llm_enriched = 0

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
            source_key = _normalize_source_key(normalized.source_key)
            existing: JobDescription | None = None

            if source_key and source_key in existing_by_source_key:
                existing = existing_by_source_key[source_key]
            elif title_key:
                title_matches = existing_by_title_key.get(title_key, [])
                existing_idsil = next(
                    (
                        jd
                        for jd in title_matches
                        if (jd.source_system or "").strip().lower() == self.SOURCE_SYSTEM
                    ),
                    None,
                )
                if existing_idsil is not None:
                    existing = existing_idsil
                elif title_matches:
                    # Preserve manual/non-IDSIL JDs with same title; don't overwrite them.
                    duplicates_skipped += 1
                    continue

            before_skills = list(normalized.required_skills)
            before_domain = normalized.domain
            normalized = await openings_service.enrich_opening_with_llm(normalized)
            if normalized.required_skills != before_skills or normalized.domain != before_domain:
                llm_enriched += 1

            if existing is not None:
                changed = False
                updates = {
                    "title": normalized.title,
                    "description": normalized.description,
                    "required_skills": normalized.required_skills,
                    "min_experience_years": normalized.min_experience_years,
                    "domain": normalized.domain,
                    "source_system": self.SOURCE_SYSTEM,
                    "source_key": normalized.source_key,
                }
                for field, value in updates.items():
                    if getattr(existing, field) != value:
                        setattr(existing, field, value)
                        changed = True
                if changed:
                    updated += 1
                else:
                    unchanged += 1
            else:
                created_jd = JobDescription(
                    title=normalized.title,
                    description=normalized.description,
                    required_skills=normalized.required_skills,
                    min_experience_years=normalized.min_experience_years,
                    domain=normalized.domain,
                    source_system=self.SOURCE_SYSTEM,
                    source_key=normalized.source_key,
                )
                db.add(created_jd)
                created += 1

            if title_key:
                if existing is not None:
                    existing_by_title_key[title_key] = [
                        jd for jd in existing_by_title_key.get(title_key, []) if jd.id != existing.id
                    ] + [existing]
                else:
                    existing_by_title_key.setdefault(title_key, []).append(created_jd)
            if source_key:
                if existing is not None:
                    existing_by_source_key[source_key] = existing
                else:
                    existing_by_source_key[source_key] = created_jd

        await db.commit()

        result = {
            "source": self.SOURCE_SYSTEM,
            "status": "success",
            "message": "IDSIL openings sync completed.",
            "last_run_at": _utc_now_iso(),
            "started_at": started_at,
            "finished_at": _utc_now_iso(),
            "created": created,
            "updated": updated,
            "unchanged": unchanged,
            "duplicates_skipped": duplicates_skipped,
            "invalid_skipped": invalid_skipped,
            "processed": processed,
            "total_received": len(raw_openings),
            "llm_enriched": llm_enriched,
            "trigger": trigger,
        }
        JobDescriptionSyncState.set_idsil_status(result)
        return result
