"""Service for fetching and normalizing IDSIL job openings."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

import httpx

from src.config.settings import get_settings

@dataclass
class NormalizedOpening:
    """Normalized job opening payload used by the JD upsert flow."""

    source_key: str | None
    title: str
    description: str
    required_skills: list[str]
    min_experience_years: int
    domain: str | None


class IDSilOpeningsService:
    """Fetches openings from IDSIL API and normalizes fields."""

    def __init__(self) -> None:
        get_settings.cache_clear()
        self._settings = get_settings()

    async def fetch_openings(self) -> list[dict[str, Any]]:
        """Fetch raw openings payload from IDSIL API."""
        headers = {"Accept": "application/json"}
        params: dict[str, str] = {}
        api_key = (self._settings.idsil_openings_api_key or "").strip()
        key_header = (self._settings.idsil_openings_api_key_header or "").strip()
        key_query_param = (self._settings.idsil_openings_api_key_query_param or "").strip()

        if api_key and key_header:
            headers[key_header] = api_key
        if api_key and key_query_param:
            params[key_query_param] = api_key

        timeout = max(self._settings.idsil_openings_timeout_seconds, 1)
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=self._settings.idsil_openings_verify_ssl,
            follow_redirects=True,
        ) as client:
            response = await client.get(
                self._settings.idsil_openings_api_url,
                headers=headers,
                params=params or None,
            )
            response.raise_for_status()
            payload = response.json()

        if isinstance(payload, dict) and payload.get("status") is False:
            message = str(payload.get("message") or "IDSIL openings API returned status=false")
            raise ValueError(message)

        openings = self._extract_opening_list(payload)
        if not openings:
            preview = json.dumps(payload)[:500]
            raise ValueError(f"No openings found in IDSIL API response. Payload preview: {preview}")
        return openings

    def normalize_opening(self, payload: dict[str, Any]) -> NormalizedOpening | None:
        """Convert one raw opening object into internal normalized fields."""
        title = self._pick_text(
            payload,
            [
                "title",
                "job_title",
                "jobTitle",
                "name",
                "position",
                "position_name",
                "opening_title",
                "openingTitle",
            ],
        )
        if not title:
            return None

        description = self._pick_text(
            payload,
            [
                "description",
                "job_description",
                "jobDescription",
                "summary",
                "details",
                "content",
                "responsibilities",
                "about_role",
                "aboutRole",
            ],
        )
        if not description:
            description = "No description provided by source API."

        source_key = self._pick_text(
            payload,
            [
                "id",
                "job_id",
                "jobId",
                "opening_id",
                "openingId",
                "requisition_id",
                "requisitionId",
                "req_id",
                "reqId",
                "reference",
                "code",
                "slug",
            ],
        )

        min_experience_years = self._extract_min_experience(payload)
        required_skills = self._extract_skills(payload)
        domain = self._pick_text(
            payload,
            [
                "department",
                "domain",
                "practice",
                "category",
                "function",
                "team",
                "business_unit",
                "businessUnit",
            ],
        )

        return NormalizedOpening(
            source_key=source_key,
            title=title,
            description=description,
            required_skills=required_skills,
            min_experience_years=min_experience_years,
            domain=domain,
        )

    @staticmethod
    def _extract_opening_list(payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []

        for key in ("openings", "jobs", "results", "records", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = IDSilOpeningsService._extract_opening_list(value)
                if nested:
                    return nested

        # Last fallback: dict itself is a single opening
        if "title" in payload or "job_title" in payload or "jobTitle" in payload:
            return [payload]
        return []

    @staticmethod
    def _pick_text(payload: dict[str, Any], keys: list[str]) -> str | None:
        for key in keys:
            if key not in payload:
                continue
            value = payload.get(key)
            text = IDSilOpeningsService._to_text(value)
            if text:
                return text
        return None

    @staticmethod
    def _to_text(value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            text = re.sub(r"<[^>]+>", " ", value)
            text = re.sub(r"\s+", " ", text).strip()
            return text or None
        if isinstance(value, (int, float)):
            return str(value)
        if isinstance(value, list):
            parts = [IDSilOpeningsService._to_text(item) for item in value]
            text = ", ".join(part for part in parts if part)
            return text or None
        if isinstance(value, dict):
            for nested_key in ("name", "title", "label", "value", "text"):
                if nested_key in value:
                    nested = IDSilOpeningsService._to_text(value.get(nested_key))
                    if nested:
                        return nested
            return None
        return str(value).strip() or None

    @staticmethod
    def _extract_min_experience(payload: dict[str, Any]) -> int:
        for key in (
            "min_experience_years",
            "minExperienceYears",
            "min_experience",
            "minExperience",
            "experience_min",
            "experienceMin",
            "experience",
            "experience_required",
            "experienceRequired",
        ):
            if key not in payload:
                continue
            value = payload.get(key)
            parsed = IDSilOpeningsService._parse_years(value)
            if parsed is not None:
                return parsed
        return 0

    @staticmethod
    def _parse_years(value: Any) -> int | None:
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return max(0, int(value))
        if isinstance(value, list):
            for item in value:
                parsed = IDSilOpeningsService._parse_years(item)
                if parsed is not None:
                    return parsed
            return None
        text = IDSilOpeningsService._to_text(value) or ""
        numbers = re.findall(r"\d+(?:\.\d+)?", text)
        if not numbers:
            return None
        return max(0, int(float(numbers[0])))

    @staticmethod
    def _extract_skills(payload: dict[str, Any]) -> list[str]:
        for key in (
            "required_skills",
            "requiredSkills",
            "skills",
            "key_skills",
            "keySkills",
            "must_have_skills",
            "mustHaveSkills",
            "tech_stack",
            "techStack",
        ):
            if key not in payload:
                continue
            skills = IDSilOpeningsService._to_skills(payload.get(key))
            if skills:
                return skills
        return []

    @staticmethod
    def _to_skills(value: Any) -> list[str]:
        if value is None:
            return []
        raw_items: list[str] = []
        if isinstance(value, str):
            raw_items = re.split(r"[,/|\n;]+", value)
        elif isinstance(value, list):
            for item in value:
                text = IDSilOpeningsService._to_text(item)
                if text:
                    raw_items.append(text)
        elif isinstance(value, dict):
            for key in ("items", "values", "skills"):
                if key in value:
                    return IDSilOpeningsService._to_skills(value.get(key))

        deduped: list[str] = []
        seen: set[str] = set()
        for item in raw_items:
            normalized = re.sub(r"\s+", " ", (item or "").strip())
            if not normalized:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
        return deduped
