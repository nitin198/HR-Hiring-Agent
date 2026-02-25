"""Service for fetching and normalizing IDSIL job openings."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
import re
from typing import Any

import httpx

from src.config.settings import get_settings
from src.llm.ollama_service import OllamaService


@dataclass
class NormalizedOpening:
    """Normalized job opening payload used by the JD upsert flow."""

    source_key: str | None
    title: str
    description: str
    required_skills: list[str]
    min_experience_years: int
    domain: str | None
    job_type: str | None = None
    work_mode: str | None = None
    experience_text: str | None = None
    job_summary: str | None = None
    key_responsibilities: str | None = None
    requirements: str | None = None
    preferred_qualifications: str | None = None


class IDSilOpeningsService:
    """Fetches openings from IDSIL API and normalizes fields."""

    _SKILL_PATTERNS: list[tuple[str, str]] = [
        (r"\bpython\b", "Python"),
        (r"\bjava\b", "Java"),
        (r"\bjavascript\b", "JavaScript"),
        (r"\btypescript\b", "TypeScript"),
        (r"\bc#\b|\bcsharp\b", "C#"),
        (r"\bc\+\+\b", "C++"),
        (r"\bgolang\b|\bgo\b", "Go"),
        (r"\bphp\b", "PHP"),
        (r"\breact(?:\.js)?\b", "React"),
        (r"\bangular\b", "Angular"),
        (r"\bvue(?:\.js)?\b", "Vue.js"),
        (r"\bnode(?:\.js|js)?\b", "Node.js"),
        (r"\bfastapi\b", "FastAPI"),
        (r"\bdjango\b", "Django"),
        (r"\bflask\b", "Flask"),
        (r"\bspring(?:\s*boot)?\b", "Spring Boot"),
        (r"\basp\.?net\b|\b\.net(?:\s*core)?\b|\bdot\s*net\b", ".NET"),
        (r"\brest(?:ful)?\s*api(?:s)?\b", "REST APIs"),
        (r"\bmicroservices?\b", "Microservices"),
        (r"\bsql\s*server\b", "SQL Server"),
        (r"\bpostgres(?:ql)?\b", "PostgreSQL"),
        (r"\bmysql\b", "MySQL"),
        (r"\boracle\b", "Oracle"),
        (r"\bmongodb\b", "MongoDB"),
        (r"\bredis\b", "Redis"),
        (r"\belasticsearch\b", "Elasticsearch"),
        (r"\bazure\b", "Azure"),
        (r"\baws\b|amazon web services", "AWS"),
        (r"\bgcp\b|google cloud", "GCP"),
        (r"\bdocker\b", "Docker"),
        (r"\bkubernetes\b|\bk8s\b", "Kubernetes"),
        (r"\bterraform\b", "Terraform"),
        (r"\bjenkins\b", "Jenkins"),
        (r"\bgit(?:hub|lab)?\b", "Git"),
        (r"\bhtml5?\b", "HTML"),
        (r"\bcss3?\b", "CSS"),
        (r"\bbootstrap\b", "Bootstrap"),
        (r"\bpower bi\b", "Power BI"),
        (r"\btableau\b", "Tableau"),
        (r"\bspark\b", "Spark"),
        (r"\bhadoop\b", "Hadoop"),
        (r"\bairflow\b", "Airflow"),
    ]

    _DOMAIN_RULES: list[tuple[str, list[str]]] = [
        ("Backend Engineering", ["backend", "api", "microservice", "spring", "django", "flask", "fastapi"]),
        ("Frontend Engineering", ["frontend", "front end", "react", "angular", "vue", "ui", "ux"]),
        ("Full Stack Engineering", ["full stack", "fullstack", "frontend and backend", "end-to-end web"]),
        ("Data Engineering", ["data pipeline", "etl", "spark", "hadoop", "warehouse", "airflow"]),
        ("Data Science / ML", ["machine learning", "ml", "ai", "model training", "nlp", "llm"]),
        ("Cloud / DevOps", ["devops", "cloud", "kubernetes", "docker", "terraform", "ci/cd", "sre"]),
        ("QA / Testing", ["qa", "test automation", "selenium", "quality assurance", "manual testing"]),
        ("Mobile Development", ["android", "ios", "react native", "flutter", "mobile app"]),
        ("ERP / Enterprise Apps", ["sap", "oracle", "erp", "dynamics", "enterprise system"]),
        ("Security", ["security", "cyber", "iam", "siem", "soc", "penetration testing"]),
    ]

    def __init__(self) -> None:
        get_settings.cache_clear()
        self._settings = get_settings()
        self._logger = logging.getLogger(__name__)
        self._llm: OllamaService | None = None

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

        job_type = self._pick_text(
            payload,
            [
                "type",
                "job_type",
                "jobType",
                "employment_type",
                "employmentType",
                "position_type",
                "positionType",
            ],
        )
        work_mode = self._pick_text(
            payload,
            [
                "work_mode",
                "workMode",
                "mode_of_work",
                "modeOfWork",
                "work_arrangement",
                "workArrangement",
                "location_type",
                "locationType",
            ],
        )
        experience_text = self._pick_text(
            payload,
            [
                "experience",
                "experience_required",
                "experienceRequired",
                "experience_range",
                "experienceRange",
                "min_experience",
                "minExperience",
                "min_experience_years",
                "minExperienceYears",
            ],
        )
        job_summary = self._pick_text(
            payload,
            [
                "job_summary",
                "jobSummary",
                "summary",
                "overview",
                "short_description",
                "shortDescription",
            ],
        )
        description_text = self._pick_text(
            payload,
            [
                "description",
                "job_description",
                "jobDescription",
                "details",
                "content",
                "about_role",
                "aboutRole",
            ],
        )
        key_responsibilities = self._pick_text(
            payload,
            [
                "key_responsibilities",
                "keyResponsibilities",
                "responsibilities",
                "key_tasks",
                "keyTasks",
            ],
        )
        requirements = self._pick_text(
            payload,
            [
                "requirements",
                "requirement",
                "mandatory_requirements",
                "mandatoryRequirements",
                "qualifications",
                "qualification",
                "must_have",
                "mustHave",
            ],
        )
        preferred_qualifications = self._pick_text(
            payload,
            [
                "preferred_qualifications",
                "preferredQualifications",
                "preferred_skills",
                "preferredSkills",
                "nice_to_have",
                "niceToHave",
                "good_to_have",
                "goodToHave",
            ],
        )

        min_experience_years = self._extract_min_experience(payload)
        if min_experience_years <= 0:
            parsed_from_text = self._parse_years(experience_text)
            if parsed_from_text is not None:
                min_experience_years = parsed_from_text

        description = self._compose_description(
            job_type=job_type,
            work_mode=work_mode,
            experience=experience_text or (f"{min_experience_years}+ years" if min_experience_years > 0 else None),
            description=description_text,
            job_summary=job_summary,
            key_responsibilities=key_responsibilities,
            requirements=requirements,
            preferred_qualifications=preferred_qualifications,
        )

        required_skills = self._extract_skills(payload, assembled_text=description)
        domain = self._pick_text(
            payload,
            [
                "domain",
                "department",
                "practice",
                "category",
                "function",
                "team",
                "business_unit",
                "businessUnit",
            ],
        ) or self._infer_domain(f"{title}\n{description}")

        return NormalizedOpening(
            source_key=source_key,
            title=title,
            description=description,
            required_skills=required_skills,
            min_experience_years=min_experience_years,
            domain=domain,
            job_type=job_type,
            work_mode=work_mode,
            experience_text=experience_text,
            job_summary=job_summary,
            key_responsibilities=key_responsibilities,
            requirements=requirements,
            preferred_qualifications=preferred_qualifications,
        )

    async def enrich_opening_with_llm(self, opening: NormalizedOpening) -> NormalizedOpening:
        """
        Enrich normalized opening using LLM when internal extraction is weak.

        LLM is only used when skill/domain extraction confidence is low.
        """
        should_enrich = len(opening.required_skills) < 5 or not opening.domain
        if not should_enrich:
            return opening

        try:
            if self._llm is None:
                self._llm = OllamaService()
            llm_data = await self._llm.extract_jd_info((opening.description or "")[:12000])
        except Exception as exc:
            self._logger.warning(
                "IDSIL JD LLM enrichment failed for title=%s: %s",
                opening.title,
                exc,
            )
            return opening

        llm_skills = self._to_skills(llm_data.get("required_skills"))
        if llm_skills:
            opening.required_skills = self._dedupe_items(opening.required_skills + llm_skills, max_items=30)

        if not opening.domain:
            inferred_domain = self._to_text(llm_data.get("domain"))
            if inferred_domain:
                opening.domain = inferred_domain

        if opening.min_experience_years <= 0:
            parsed_experience = self._parse_years(llm_data.get("min_experience_years"))
            if parsed_experience is not None:
                opening.min_experience_years = parsed_experience

        if not opening.domain:
            opening.domain = self._infer_domain(f"{opening.title}\n{opening.description}")

        return opening

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

    @classmethod
    def _extract_skills(cls, payload: dict[str, Any], *, assembled_text: str) -> list[str]:
        extracted: list[str] = []

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
            "preferred_skills",
            "preferredSkills",
        ):
            if key not in payload:
                continue
            extracted.extend(cls._to_skills(payload.get(key)))

        extracted.extend(cls._extract_skills_from_text(assembled_text))
        return cls._dedupe_items(extracted, max_items=30)

    @staticmethod
    def _to_skills(value: Any) -> list[str]:
        if value is None:
            return []
        raw_items: list[str] = []
        if isinstance(value, str):
            raw_items = re.split(r"[,|\n;]+|\s/\s", value)
        elif isinstance(value, list):
            for item in value:
                text = IDSilOpeningsService._to_text(item)
                if text:
                    raw_items.append(text)
        elif isinstance(value, dict):
            for key in ("items", "values", "skills"):
                if key in value:
                    return IDSilOpeningsService._to_skills(value.get(key))

        return IDSilOpeningsService._dedupe_items(raw_items, max_items=30)

    @classmethod
    def _extract_skills_from_text(cls, text: str) -> list[str]:
        hits: list[str] = []
        content = text or ""
        for pattern, skill in cls._SKILL_PATTERNS:
            if re.search(pattern, content, flags=re.IGNORECASE):
                hits.append(skill)
        return cls._dedupe_items(hits, max_items=30)

    @classmethod
    def _infer_domain(cls, text: str) -> str | None:
        content = (text or "").lower()
        if not content:
            return None

        if re.search(r"\bfull[\s-]?stack\b", content):
            return "Full Stack Engineering"
        if ("frontend" in content or "front end" in content) and ("backend" in content or "back end" in content):
            return "Full Stack Engineering"

        best_domain = None
        best_score = 0
        for domain, keywords in cls._DOMAIN_RULES:
            score = sum(1 for keyword in keywords if keyword in content)
            if score > best_score:
                best_score = score
                best_domain = domain

        return best_domain if best_score > 0 else None

    @staticmethod
    def _dedupe_items(values: list[str], *, max_items: int) -> list[str]:
        deduped: list[str] = []
        seen: set[str] = set()
        for item in values:
            normalized = re.sub(r"\s+", " ", (item or "").strip())
            normalized = re.sub(r"(?i)^[-*•]+\s*", "", normalized)
            normalized = re.sub(r"(?i)^(strong|good|excellent)\s+", "", normalized)
            normalized = re.sub(r"(?i)^experience with\s+", "", normalized)
            if not normalized:
                continue
            if len(normalized) > 80:
                continue
            key = normalized.lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(normalized)
            if len(deduped) >= max_items:
                break
        return deduped

    @staticmethod
    def _compose_description(
        *,
        job_type: str | None,
        work_mode: str | None,
        experience: str | None,
        description: str | None,
        job_summary: str | None,
        key_responsibilities: str | None,
        requirements: str | None,
        preferred_qualifications: str | None,
    ) -> str:
        sections: list[tuple[str, str | None]] = [
            ("Type", job_type),
            ("Work Mode", work_mode),
            ("Experience", experience),
            ("Job Summary", job_summary),
            ("Description", description),
            ("Key Responsibilities", key_responsibilities),
            ("Requirements", requirements),
            ("Preferred Qualifications", preferred_qualifications),
        ]

        rendered: list[str] = []
        for heading, value in sections:
            text = (value or "").strip() or "Not specified by source API."
            rendered.append(f"{heading}:")
            rendered.append(text)
            rendered.append("")

        return "\n".join(rendered).strip()
