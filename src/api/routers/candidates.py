"""Router for candidate endpoints."""

import base64
from io import BytesIO
import re
import os
import logging
from datetime import datetime
from typing import Annotated, Any
from zipfile import ZIP_DEFLATED, ZipFile

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form
from fastapi.responses import StreamingResponse
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.hiring_agent import HiringAgent
from src.api.schemas import (
    CandidateCreate,
    CandidateCreateFromFile,
    CandidateResponse,
    CandidateDetailResponse,
    CandidateWithAnalysisResponse,
    ErrorResponse,
)
from src.database.connection import get_db
from src.database.models import (
    Candidate,
    CandidateAnalysis,
    CandidateAnalysisRun,
    CandidateJobLink,
    CandidateProfile,
    JobDescription,
)
from src.llm.ollama_service import OllamaService
from src.parsers.resume_parser import ResumeParser
from src.services.pdf_report import build_candidate_analysis_pdf

router = APIRouter(prefix="/candidates", tags=["Candidates"])

RESUME_DIR = os.path.join("data", "resumes")
os.makedirs(RESUME_DIR, exist_ok=True)


def _safe_filename(value: str) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", value.strip())
    return name.strip("_") or "candidate"


def _extract_email(text: str) -> str | None:
    match = re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", text)
    return match.group(0) if match else None


def _extract_phone(text: str) -> str | None:
    match = re.search(r"(\+?\d[\d\s\-\(\)]{8,}\d)", text)
    return match.group(0) if match else None


def _normalize_name(value: str) -> str:
    cleaned = re.sub(r"[\|/\\\\]+", " ", value or "")
    cleaned = re.sub(r"[^A-Za-z\s\.\-']", " ", cleaned).strip()
    return re.sub(r"\s{2,}", " ", cleaned).strip()


def _is_valid_name(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    if lowered in {"cv", "resume", "curriculum vitae"}:
        return False
    if any(keyword in lowered for keyword in ("profile", "summary", "experience", "education", "skills")):
        return False
    parts = value.split()
    if len(parts) < 2 or len(parts) > 5:
        return False
    if len(value) > 80:
        return False
    return True


def _extract_name(text: str) -> str | None:
    if not text:
        return None
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return None

    # Prefer explicit name labels.
    for line in lines[:30]:
        if re.match(r"^name\s*[:\-]", line, flags=re.IGNORECASE):
            candidate = _normalize_name(re.sub(r"^name\s*[:\-]\s*", "", line, flags=re.IGNORECASE))
            candidate = candidate.split(" - ")[0].split(" – ")[0].split("|")[0].strip()
            if _is_valid_name(candidate):
                return candidate

    # Heuristic: first clean line without emails/urls/section headers.
    for line in lines[:30]:
        lowered = line.lower()
        if "@" in line or "http" in lowered:
            continue
        if any(keyword in lowered for keyword in ("resume", "curriculum", "cv")):
            continue
        candidate = line
        if "|" in candidate or " - " in candidate or " – " in candidate:
            candidate = candidate.split(" - ")[0].split(" – ")[0].split("|")[0].strip()
        for marker in ("personal profile", "profile", "summary"):
            idx = candidate.lower().find(marker)
            if idx > 0:
                candidate = candidate[:idx].strip()
                break
        candidate = _normalize_name(candidate)
        if _is_valid_name(candidate):
            return candidate
    return None


def _is_likely_resume(text: str) -> bool:
    if not text or len(text) < 200:
        return False
    keywords = ["experience", "education", "skills", "project", "responsibilities", "summary"]
    found = sum(1 for keyword in keywords if keyword in text.lower())
    return found >= 2


_COMMON_SKILL_PATTERNS: list[tuple[str, str]] = [
    (r"\bpython\b", "Python"),
    (r"\bjava\b", "Java"),
    (r"\bjavascript\b", "JavaScript"),
    (r"\btypescript\b", "TypeScript"),
    (r"\bc#\b|\bcsharp\b", "C#"),
    (r"\bc\+\+\b", "C++"),
    (r"\bgolang\b|\bgo\b", "Go"),
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
    (r"\bmongodb\b", "MongoDB"),
    (r"\bazure\b", "Azure"),
    (r"\baws\b|amazon web services", "AWS"),
    (r"\bgcp\b|google cloud", "GCP"),
    (r"\bdocker\b", "Docker"),
    (r"\bkubernetes\b|\bk8s\b", "Kubernetes"),
    (r"\bhtml5?\b", "HTML"),
    (r"\bcss3?\b", "CSS"),
    (r"\bbootstrap\b", "Bootstrap"),
    (r"\bgit(?:hub|lab)?\b", "Git"),
    (r"\bjira\b", "Jira"),
]


def _dedupe_values(values: list[str], *, max_items: int | None = None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        normalized = re.sub(r"\s+", " ", value.strip())
        if not normalized:
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(normalized)
        if max_items is not None and len(deduped) >= max_items:
            break
    return deduped


def _extract_experience_years_from_text(text: str) -> float:
    matches = re.findall(
        r"(?i)\b(\d{1,2}(?:\.\d+)?)\s*\+?\s*(?:years?|yrs?)\b|\b(\d{1,2})\+\s*(?:years?|yrs?)\b",
        text or "",
    )
    values: list[float] = []
    for left, right in matches:
        token = left or right
        try:
            parsed = float(token)
            if 0 <= parsed <= 50:
                values.append(parsed)
        except (TypeError, ValueError):
            continue
    return max(values) if values else 0.0


def _extract_role_from_lines(lines: list[str]) -> str | None:
    role_pattern = re.compile(
        r"(?i)\b((?:sr\.?|senior|jr\.?|junior|lead|principal)?\s*"
        r"(?:software|full stack|frontend|front end|backend|back end|data|qa|devops|cloud)?\s*"
        r"(?:engineer|developer|architect|analyst|manager|consultant))\b"
    )
    for line in lines[:40]:
        if len(line) > 100:
            continue
        if "@" in line:
            continue
        match = role_pattern.search(line)
        if match:
            return re.sub(r"\s{2,}", " ", match.group(1)).strip().title()
    return None


def _extract_education_from_lines(lines: list[str]) -> str | None:
    education_pattern = re.compile(
        r"(?i)\b(b\.?tech|m\.?tech|bachelor|master|b\.?e\.?|m\.?e\.?|bca|mca|mba|phd|doctorate|diploma)\b"
    )
    for line in lines:
        if education_pattern.search(line):
            return line.strip()[:255]
    return None


def _extract_certifications_from_lines(lines: list[str]) -> list[str]:
    certifications: list[str] = []
    for line in lines:
        if re.search(r"(?i)\b(certified|certification|certificate)\b", line):
            certifications.append(line.strip())
    return _dedupe_values(certifications, max_items=8)


def _extract_profile_from_resume_text(resume_text: str) -> dict[str, Any]:
    text = resume_text or ""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    experience_years = _extract_experience_years_from_text(text)
    role = _extract_role_from_lines(lines)

    skills_with_position: list[tuple[int, str]] = []
    for pattern, label in _COMMON_SKILL_PATTERNS:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            skills_with_position.append((match.start(), label))
    skills_with_position.sort(key=lambda item: item[0])
    ordered_skills = [label for _, label in skills_with_position]
    ordered_skills = _dedupe_values(ordered_skills, max_items=16)
    primary_skills = ordered_skills[:8]
    secondary_skills = ordered_skills[8:16]

    linkedin_url = None
    portfolio_url = None
    urls = re.findall(r"https?://[^\s)>\"]+", text)
    for url in urls:
        lowered = url.lower()
        if "linkedin.com" in lowered and linkedin_url is None:
            linkedin_url = url
        elif portfolio_url is None and any(
            token in lowered for token in ("github.com", "gitlab.com", "portfolio", "behance.net", "dribbble.com")
        ):
            portfolio_url = url

    summary_lines: list[str] = []
    for line in lines[:30]:
        lowered = line.lower()
        if "@" in line or lowered.startswith(("name:", "email:", "phone:", "mobile:", "address:")):
            continue
        summary_lines.append(line)
        if len(" ".join(summary_lines)) >= 280 or len(summary_lines) >= 3:
            break
    summary = " ".join(summary_lines)[:320] if summary_lines else None

    return {
        "current_role": role,
        "headline": role,
        "total_experience_years": experience_years,
        "primary_skills": primary_skills,
        "secondary_skills": secondary_skills,
        "education": _extract_education_from_lines(lines),
        "certifications": _extract_certifications_from_lines(lines),
        "summary": summary,
        "location": None,
        "linkedin_url": linkedin_url,
        "portfolio_url": portfolio_url,
    }


def _apply_candidate_filters(
    query,
    *,
    job_description_id: int | None = None,
    name: str | None = None,
    skills: str | None = None,
    min_experience: float | None = None,
    max_experience: float | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
):
    if job_description_id is not None:
        query = query.outerjoin(CandidateJobLink, Candidate.id == CandidateJobLink.candidate_id)
        query = query.where(CandidateJobLink.job_description_id == job_description_id)
    if name:
        query = query.where(Candidate.name.ilike(f"%{name}%"))
    if min_experience is not None:
        query = query.where(CandidateProfile.total_experience_years >= min_experience)
    if max_experience is not None:
        query = query.where(CandidateProfile.total_experience_years <= max_experience)
    if skills:
        skill_terms = [term.strip().lower() for term in skills.split(",") if term.strip()]
        for term in skill_terms:
            query = query.where(
                or_(
                    CandidateProfile.primary_skills.like(f"%{term}%"),
                    CandidateProfile.secondary_skills.like(f"%{term}%"),
                    Candidate.resume_text.ilike(f"%{term}%"),
                )
            )
    if created_from:
        query = query.where(Candidate.created_at >= created_from)
    if created_to:
        query = query.where(Candidate.created_at <= created_to)
    return query


def _encode_candidate_cursor(created_at: datetime, candidate_id: int) -> str:
    payload = f"{created_at.isoformat()}|{candidate_id}"
    return base64.urlsafe_b64encode(payload.encode("utf-8")).decode("ascii")


def _decode_candidate_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        raw = base64.urlsafe_b64decode(cursor.encode("ascii")).decode("utf-8")
        timestamp, candidate_id = raw.rsplit("|", 1)
        return datetime.fromisoformat(timestamp), int(candidate_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid cursor") from exc


async def _build_candidate_summary_items(rows: list[tuple], db: AsyncSession) -> list[dict]:
    candidate_ids = [candidate.id for candidate, _ in rows]
    link_map: dict[int, list[dict]] = {}
    latest_analysis_map: dict[int, dict] = {}

    if candidate_ids:
        links_result = await db.execute(
            select(CandidateJobLink, JobDescription)
            .join(JobDescription, CandidateJobLink.job_description_id == JobDescription.id)
            .where(CandidateJobLink.candidate_id.in_(candidate_ids))
        )
        for link, jd in links_result.all():
            link_map.setdefault(link.candidate_id, []).append(
                {
                    "job_description_id": jd.id,
                    "title": jd.title,
                    "confidence": link.confidence,
                }
            )

        runs_result = await db.execute(
            select(CandidateAnalysisRun, JobDescription)
            .join(JobDescription, CandidateAnalysisRun.job_description_id == JobDescription.id)
            .where(CandidateAnalysisRun.candidate_id.in_(candidate_ids))
            .order_by(
                CandidateAnalysisRun.candidate_id,
                CandidateAnalysisRun.analysis_timestamp.desc(),
                CandidateAnalysisRun.id.desc(),
            )
        )
        for run, jd in runs_result.all():
            if run.candidate_id in latest_analysis_map:
                continue
            payload = run.to_dict()
            payload["job_description_title"] = jd.title
            latest_analysis_map[run.candidate_id] = payload

    return [
        {
            "candidate": candidate.to_dict(),
            "profile": profile.to_dict() if profile else None,
            "job_links": link_map.get(candidate.id, []),
            "latest_analysis": latest_analysis_map.get(candidate.id),
        }
        for candidate, profile in rows
    ]


async def _build_profile(
    candidate_id: int,
    resume_text: str,
    ollama: OllamaService,
    invalid_resume: bool,
    db: AsyncSession,
) -> CandidateProfile:
    logger = logging.getLogger(__name__)
    profile_data = {
        "current_role": None,
        "headline": None,
        "total_experience_years": 0.0,
        "primary_skills": [],
        "secondary_skills": [],
        "education": None,
        "certifications": [],
        "summary": None,
        "location": None,
        "linkedin_url": None,
        "portfolio_url": None,
        "invalid_resume": invalid_resume,
    }
    if resume_text:
        profile_data.update(_extract_profile_from_resume_text(resume_text))

    if resume_text:
        try:
            # Keep payload bounded for network stability with cloud-backed models.
            llm_profile = await ollama.extract_candidate_profile((resume_text or "")[:12000])

            current_role = (llm_profile.get("current_role") or "").strip()
            if current_role:
                profile_data["current_role"] = current_role

            headline = (llm_profile.get("headline") or "").strip()
            if headline:
                profile_data["headline"] = headline

            try:
                llm_experience = float(llm_profile.get("total_experience_years") or 0.0)
            except (TypeError, ValueError):
                llm_experience = 0.0
            if llm_experience > 0:
                profile_data["total_experience_years"] = llm_experience

            primary_skills = _dedupe_values(llm_profile.get("primary_skills") or [], max_items=8)
            if primary_skills:
                profile_data["primary_skills"] = primary_skills

            secondary_skills = _dedupe_values(llm_profile.get("secondary_skills") or [], max_items=8)
            if secondary_skills:
                profile_data["secondary_skills"] = secondary_skills

            education = (llm_profile.get("education") or "").strip()
            if education:
                profile_data["education"] = education

            certifications = _dedupe_values(llm_profile.get("certifications") or [], max_items=8)
            if certifications:
                profile_data["certifications"] = certifications

            summary = (llm_profile.get("summary") or "").strip()
            if summary:
                profile_data["summary"] = summary

            location = (llm_profile.get("location") or "").strip()
            if location:
                profile_data["location"] = location

            linkedin_url = (llm_profile.get("linkedin_url") or "").strip()
            if linkedin_url:
                profile_data["linkedin_url"] = linkedin_url

            portfolio_url = (llm_profile.get("portfolio_url") or "").strip()
            if portfolio_url:
                profile_data["portfolio_url"] = portfolio_url
        except Exception as exc:
            logger.warning(
                "LLM profile extraction failed for candidate_id=%s, using heuristic fallback: %s",
                candidate_id,
                exc,
            )

    if not profile_data.get("headline"):
        headline = profile_data.get("current_role")
        if not headline:
            primary_skills = profile_data.get("primary_skills") or []
            experience = profile_data.get("total_experience_years") or 0
            level = "Senior" if experience >= 7 else "Mid-level" if experience >= 3 else "Junior"
            headline = f"{level} {primary_skills[0]} Developer" if primary_skills else f"{level} Developer"
        profile_data["headline"] = headline

    profile = CandidateProfile(candidate_id=candidate_id, **profile_data)
    db.add(profile)
    return profile


def _save_resume_file(filename: str, content: bytes, candidate_name: str) -> str:
    safe_name = _safe_filename(candidate_name)
    ext = os.path.splitext(filename or "")[1] or ".txt"
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    stored_name = f"{safe_name}_{timestamp}{ext}"
    path = os.path.join(RESUME_DIR, stored_name)
    with open(path, "wb") as f:
        f.write(content)
    return path


async def _auto_link_candidate_to_jds(
    db: AsyncSession,
    candidate_id: int,
    resume_text: str,
    *,
    candidate_profile: CandidateProfile | None = None,
    ollama: OllamaService | None = None,
) -> list[CandidateJobLink]:
    """
    Auto-link candidate to exactly one best-matching JD.

    Strategy:
    1. Rule-based score across all JDs (skills/title/domain/experience).
    2. If ambiguous or weak confidence, ask LLM to pick one JD from top candidates.
    3. Persist only one AI link and set candidate.job_description_id accordingly.
    """
    def normalize_text(value: str) -> str:
        return re.sub(r"\s+", " ", (value or "").strip().lower())

    def tokenize(value: str) -> set[str]:
        return {
            token
            for token in re.split(r"[^a-z0-9+#\.]+", normalize_text(value))
            if token and len(token) > 1
        }

    def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
        return max(minimum, min(maximum, value))

    def parse_confidence(value: Any) -> float:
        try:
            parsed = float(value)
        except (TypeError, ValueError):
            return 0.0
        if parsed > 1.0:
            parsed = parsed / 100.0
        return clamp(parsed)

    async def llm_pick_best_jd(
        llm: OllamaService,
        *,
        resume_excerpt: str,
        profile_payload: dict[str, Any],
        ranked_options: list[dict[str, Any]],
    ) -> tuple[int | None, float]:
        option_payload = [
            {
                "id": item["jd"].id,
                "title": item["jd"].title,
                "domain": item["jd"].domain,
                "required_skills": item["jd"].required_skills or [],
                "min_experience_years": item["jd"].min_experience_years or 0,
                "rule_score": round(item["score"], 4),
            }
            for item in ranked_options
        ]

        system_prompt = (
            "You are a strict hiring matcher. "
            "Choose exactly one best job description for the candidate from provided options."
        )
        user_prompt = f"""Select the best matching job description from the options.

Candidate profile:
{profile_payload}

Resume excerpt:
{resume_excerpt}

Job options:
{option_payload}

Return JSON only in this format:
{{
  "job_description_id": <one id from options>,
  "confidence": <0 to 1>,
  "reason": "<short reason>"
}}

Rules:
- Must choose one id from the options.
- Prefer stronger skill overlap and role/domain alignment.
- Confidence must be between 0 and 1.
"""
        try:
            llm_result = await llm.invoke_with_json(
                [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ]
            )
        except Exception:
            return None, 0.0

        picked_id = llm_result.get("job_description_id")
        try:
            picked_id = int(picked_id)
        except (TypeError, ValueError):
            return None, 0.0

        valid_ids = {item["jd"].id for item in ranked_options}
        if picked_id not in valid_ids:
            return None, 0.0

        return picked_id, parse_confidence(llm_result.get("confidence"))

    jd_result = await db.execute(select(JobDescription))
    jds = list(jd_result.scalars().all())
    if not jds:
        return []

    candidate_result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = candidate_result.scalar_one_or_none()
    if not candidate:
        return []

    if candidate_profile is None:
        profile_result = await db.execute(
            select(CandidateProfile).where(CandidateProfile.candidate_id == candidate_id)
        )
        candidate_profile = profile_result.scalar_one_or_none()

    resume_lower = normalize_text(resume_text or "")
    resume_tokens = tokenize(resume_text or "")
    profile_primary = candidate_profile.primary_skills if candidate_profile else []
    profile_secondary = candidate_profile.secondary_skills if candidate_profile else []
    profile_skills = [normalize_text(skill) for skill in ((profile_primary or []) + (profile_secondary or []))]
    profile_tokens = tokenize(" ".join(profile_skills))
    combined_tokens = resume_tokens.union(profile_tokens)
    profile_experience = float(candidate_profile.total_experience_years or 0.0) if candidate_profile else 0.0

    scored: list[dict[str, Any]] = []
    for jd in jds:
        required_skills = [normalize_text(skill) for skill in (jd.required_skills or []) if normalize_text(skill)]
        required_total = len(required_skills)

        matched_required = 0
        for skill in required_skills:
            if skill in resume_lower:
                matched_required += 1
                continue
            skill_tokens = tokenize(skill)
            if skill_tokens and skill_tokens.issubset(combined_tokens):
                matched_required += 1
                continue
            if any(skill in prof_skill or prof_skill in skill for prof_skill in profile_skills if prof_skill):
                matched_required += 1

        skill_score = (matched_required / required_total) if required_total > 0 else 0.0

        title_tokens = tokenize(jd.title or "")
        title_hits = sum(1 for token in title_tokens if token in combined_tokens)
        title_score = (title_hits / len(title_tokens)) if title_tokens else 0.0

        domain_tokens = tokenize(jd.domain or "")
        domain_score = 1.0 if domain_tokens and domain_tokens.intersection(combined_tokens) else 0.0

        min_exp = float(jd.min_experience_years or 0.0)
        if min_exp <= 0:
            experience_score = 1.0
        elif profile_experience >= min_exp:
            experience_score = 1.0
        else:
            experience_score = clamp(profile_experience / min_exp)

        overall = (
            (0.65 * skill_score)
            + (0.20 * title_score)
            + (0.10 * domain_score)
            + (0.05 * experience_score)
        )
        scored.append(
            {
                "jd": jd,
                "score": clamp(overall),
                "skill_score": skill_score,
                "matched_required": matched_required,
                "required_total": required_total,
                "title_score": title_score,
                "domain_score": domain_score,
                "experience_score": experience_score,
            }
        )

    scored.sort(
        key=lambda item: (
            -item["score"],
            -item["skill_score"],
            -item["matched_required"],
            (item["jd"].title or "").lower(),
            item["jd"].id,
        )
    )
    if not scored:
        return []

    top = scored[0]
    selected_jd = top["jd"]
    confidence = top["score"]
    linked_by = "ai_rule"

    should_use_llm = False
    if len(scored) > 1:
        margin = top["score"] - scored[1]["score"]
        should_use_llm = top["score"] < 0.45 or margin < 0.12
    else:
        should_use_llm = top["score"] < 0.35

    if should_use_llm:
        llm = ollama or OllamaService()
        resume_excerpt = (resume_text or "")[:7000]
        profile_payload = {
            "headline": candidate_profile.headline if candidate_profile else None,
            "current_role": candidate_profile.current_role if candidate_profile else None,
            "total_experience_years": profile_experience,
            "primary_skills": profile_primary or [],
            "secondary_skills": profile_secondary or [],
        }
        shortlisted = scored[: min(5, len(scored))]
        picked_id, llm_confidence = await llm_pick_best_jd(
            llm,
            resume_excerpt=resume_excerpt,
            profile_payload=profile_payload,
            ranked_options=shortlisted,
        )
        if picked_id is not None:
            picked = next((item for item in shortlisted if item["jd"].id == picked_id), None)
            if picked is not None:
                selected_jd = picked["jd"]
                confidence = max(picked["score"], llm_confidence)
                linked_by = "ai_llm"

    existing_links_result = await db.execute(
        select(CandidateJobLink).where(CandidateJobLink.candidate_id == candidate_id)
    )
    existing_links = existing_links_result.scalars().all()
    for existing_link in existing_links:
        if (existing_link.linked_by or "").lower() in {"ai", "ai_rule", "ai_llm"}:
            await db.delete(existing_link)

    links: list[CandidateJobLink] = []
    link = CandidateJobLink(
        candidate_id=candidate_id,
        job_description_id=selected_jd.id,
        confidence=round(confidence, 4),
        linked_by=linked_by,
    )
    candidate.job_description_id = selected_jd.id
    db.add(link)
    links.append(link)

    return links


async def _find_duplicate_candidate(
    db: AsyncSession,
    name: str,
    email: str | None,
) -> Candidate | None:
    if not name:
        return None
    query = select(Candidate).where(Candidate.name.ilike(name))
    if email:
        query = query.where(Candidate.email.ilike(email))
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def create_candidate_from_resume_bytes(
    db: AsyncSession,
    filename: str,
    content: bytes,
    *,
    name: str | None = None,
    email: str | None = None,
    phone: str | None = None,
    job_description_id: int | None = None,
    ollama: OllamaService | None = None,
) -> Candidate | None:
    """
    Create a candidate from raw resume bytes using the same logic as upload flow.

    Returns None when a duplicate candidate is detected.
    Raises ValueError for unsupported/invalid resume files.
    """
    if job_description_id is not None:
        jd_result = await db.execute(
            select(JobDescription).where(JobDescription.id == job_description_id)
        )
        if not jd_result.scalar_one_or_none():
            raise ValueError("Job description not found")

    parser = ResumeParser()
    resume_text = parser.parse_and_clean(filename, content)
    invalid_resume = not _is_likely_resume(resume_text)
    extracted_name = _extract_name(resume_text)
    resolved_name = (name or "").strip() or extracted_name

    llm = ollama or OllamaService()
    if resume_text and (not resolved_name or not _is_valid_name(resolved_name)):
        try:
            first_lines = "\n".join(
                [line for line in (resume_text or "").splitlines() if line.strip()][:20]
            )
            llm_name = await llm.extract_candidate_name(first_lines or resume_text)
            resolved_name = _normalize_name((llm_name or {}).get("name"))
            if not _is_valid_name(resolved_name):
                resolved_name = None
        except Exception:
            resolved_name = None

    if not resolved_name or not _is_valid_name(resolved_name):
        resolved_name = _normalize_name(os.path.splitext(filename or "")[0])
    if not resolved_name or not _is_valid_name(resolved_name):
        resolved_name = "Candidate"

    stored_path = _save_resume_file(filename, content, resolved_name)
    resolved_email = email or _extract_email(resume_text)
    resolved_phone = phone or _extract_phone(resume_text)

    duplicate = await _find_duplicate_candidate(db, resolved_name, resolved_email)
    if duplicate:
        return None

    candidate = Candidate(
        name=resolved_name,
        email=resolved_email,
        phone=resolved_phone,
        resume_text=resume_text,
        resume_file_path=stored_path,
        job_description_id=job_description_id,
    )
    db.add(candidate)
    await db.flush()

    profile = await _build_profile(candidate.id, resume_text, llm, invalid_resume, db)
    if job_description_id is not None:
        db.add(
            CandidateJobLink(
                candidate_id=candidate.id,
                job_description_id=job_description_id,
                confidence=1.0,
                linked_by="manual",
            )
        )
    else:
        await _auto_link_candidate_to_jds(
            db,
            candidate.id,
            resume_text,
            candidate_profile=profile,
            ollama=llm,
        )

    await db.commit()
    await db.refresh(candidate)
    return candidate


@router.post("", response_model=CandidateResponse, status_code=201)
async def create_candidate(
    candidate_data: CandidateCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Candidate:
    """
    Create a new candidate from resume text.

    Args:
        candidate_data: Candidate data
        db: Database session

    Returns:
        Created candidate

    Raises:
        HTTPException: If job description not found
    """
    # Verify job description if provided
    if candidate_data.job_description_id is not None:
        jd_result = await db.execute(
            select(JobDescription).where(JobDescription.id == candidate_data.job_description_id)
        )
        if not jd_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Job description not found")

    duplicate = await _find_duplicate_candidate(db, candidate_data.name, candidate_data.email)
    if duplicate:
        raise HTTPException(status_code=409, detail="Candidate already exists with same name and email")

    candidate = Candidate(
        name=candidate_data.name,
        email=candidate_data.email,
        phone=candidate_data.phone,
        resume_text=candidate_data.resume_text,
        job_description_id=candidate_data.job_description_id,
    )
    db.add(candidate)
    await db.flush()
    invalid_resume = not _is_likely_resume(candidate_data.resume_text)
    ollama = OllamaService()
    await _build_profile(candidate.id, candidate_data.resume_text, ollama, invalid_resume, db)
    if candidate_data.job_description_id is not None:
        db.add(
            CandidateJobLink(
                candidate_id=candidate.id,
                job_description_id=candidate_data.job_description_id,
                confidence=1.0,
                linked_by="manual",
            )
        )
    await db.commit()
    await db.refresh(candidate)
    return candidate.to_dict()


@router.post("/upload", response_model=CandidateResponse, status_code=201)
async def upload_candidate_resume(
    db: Annotated[AsyncSession, Depends(get_db)],
    name: Annotated[str | None, Form()] = None,
    job_description_id: Annotated[int | None, Form()] = None,
    email: Annotated[str | None, Form()] = None,
    phone: Annotated[str | None, Form()] = None,
    file: UploadFile = File(...),
) -> Candidate:
    """
    Create a new candidate by uploading a resume file.

    Args:
        name: Candidate name
        job_description_id: ID of the job description
        email: Candidate email
        phone: Candidate phone
        file: Uploaded resume file
        db: Database session

    Returns:
        Created candidate

    Raises:
        HTTPException: If job description not found or file format not supported
    """
    content = await file.read()
    try:
        candidate = await create_candidate_from_resume_bytes(
            db=db,
            filename=file.filename or "resume.txt",
            content=content,
            name=name,
            email=email,
            phone=phone,
            job_description_id=job_description_id,
            ollama=OllamaService(),
        )
    except ValueError as e:
        detail = str(e)
        if detail == "Job description not found":
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)

    if candidate is None:
        raise HTTPException(status_code=409, detail="Candidate already exists with same name and email")

    return candidate.to_dict()


@router.get("", response_model=list[CandidateResponse])
async def list_candidates(
    db: Annotated[AsyncSession, Depends(get_db)],
    job_description_id: int | None = None,
    name: str | None = None,
    skills: str | None = None,
    min_experience: float | None = None,
    max_experience: float | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    skip: Annotated[int, Query] = 0,
    limit: Annotated[int, Query] = 100,
) -> list[Candidate]:
    """
    List candidates, optionally filtered by job description.

    Args:
        job_description_id: Optional filter by job description
        skip: Number of records to skip
        limit: Maximum number of records to return
        db: Database session

    Returns:
        List of candidates
    """
    query = (
        select(Candidate)
        .outerjoin(CandidateProfile, Candidate.id == CandidateProfile.candidate_id)
        .order_by(Candidate.created_at.desc())
    )
    query = _apply_candidate_filters(
        query,
        job_description_id=job_description_id,
        name=name,
        skills=skills,
        min_experience=min_experience,
        max_experience=max_experience,
        created_from=created_from,
        created_to=created_to,
    )

    query = query.offset(skip).limit(limit)

    result = await db.execute(query)
    candidates = list(result.scalars().all())
    return [candidate.to_dict() for candidate in candidates]


@router.get("/summary")
async def list_candidates_summary(
    db: Annotated[AsyncSession, Depends(get_db)],
    job_description_id: int | None = None,
    name: str | None = None,
    skills: str | None = None,
    min_experience: float | None = None,
    max_experience: float | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    skip: Annotated[int, Query] = 0,
    limit: Annotated[int, Query] = 100,
) -> list[dict]:
    """List candidates with profile summary for management screens."""
    query = (
        select(Candidate, CandidateProfile)
        .outerjoin(CandidateProfile, Candidate.id == CandidateProfile.candidate_id)
        .order_by(Candidate.created_at.desc(), Candidate.id.desc())
    )
    query = _apply_candidate_filters(
        query,
        job_description_id=job_description_id,
        name=name,
        skills=skills,
        min_experience=min_experience,
        max_experience=max_experience,
        created_from=created_from,
        created_to=created_to,
    )

    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    rows = result.all()
    return await _build_candidate_summary_items(rows, db)


@router.get("/summary/paged")
async def list_candidates_summary_paged(
    db: Annotated[AsyncSession, Depends(get_db)],
    job_description_id: int | None = None,
    name: str | None = None,
    skills: str | None = None,
    min_experience: float | None = None,
    max_experience: float | None = None,
    created_from: str | None = None,
    created_to: str | None = None,
    limit: Annotated[int, Query] = 20,
    cursor: str | None = None,
) -> dict:
    """Cursor-paged candidate summary for high-volume management screens."""
    page_limit = max(1, min(limit, 100))
    query = (
        select(Candidate, CandidateProfile)
        .outerjoin(CandidateProfile, Candidate.id == CandidateProfile.candidate_id)
        .order_by(Candidate.created_at.desc(), Candidate.id.desc())
    )
    query = _apply_candidate_filters(
        query,
        job_description_id=job_description_id,
        name=name,
        skills=skills,
        min_experience=min_experience,
        max_experience=max_experience,
        created_from=created_from,
        created_to=created_to,
    )

    if cursor:
        cursor_ts, cursor_id = _decode_candidate_cursor(cursor)
        query = query.where(
            or_(
                Candidate.created_at < cursor_ts,
                and_(Candidate.created_at == cursor_ts, Candidate.id < cursor_id),
            )
        )

    result = await db.execute(query.limit(page_limit + 1))
    rows = result.all()
    has_more = len(rows) > page_limit
    page_rows = rows[:page_limit]
    items = await _build_candidate_summary_items(page_rows, db)

    next_cursor = None
    if has_more and page_rows:
        last_candidate = page_rows[-1][0]
        next_cursor = _encode_candidate_cursor(last_candidate.created_at, last_candidate.id)

    count_query = (
        select(func.count(func.distinct(Candidate.id)))
        .select_from(Candidate)
        .outerjoin(CandidateProfile, Candidate.id == CandidateProfile.candidate_id)
    )
    count_query = _apply_candidate_filters(
        count_query,
        job_description_id=job_description_id,
        name=name,
        skills=skills,
        min_experience=min_experience,
        max_experience=max_experience,
        created_from=created_from,
        created_to=created_to,
    )
    total_count = (await db.execute(count_query)).scalar_one() or 0

    return {
        "items": items,
        "next_cursor": next_cursor,
        "has_more": has_more,
        "limit": page_limit,
        "total_count": int(total_count),
    }


@router.get("/{candidate_id}/detail", response_model=CandidateDetailResponse)
async def get_candidate_detail(
    candidate_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Get candidate with profile and analysis history."""
    result = await db.execute(
        select(Candidate, CandidateProfile, CandidateAnalysis)
        .outerjoin(CandidateProfile, Candidate.id == CandidateProfile.candidate_id)
        .outerjoin(CandidateAnalysis, Candidate.id == CandidateAnalysis.candidate_id)
        .where(Candidate.id == candidate_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    candidate, profile, analysis = row
    history_result = await db.execute(
        select(CandidateAnalysisRun, JobDescription)
        .join(JobDescription, CandidateAnalysisRun.job_description_id == JobDescription.id)
        .where(CandidateAnalysisRun.candidate_id == candidate_id)
        .order_by(CandidateAnalysisRun.analysis_timestamp.desc())
    )
    history_rows = history_result.all()
    history = []
    for run, jd in history_rows:
        payload = run.to_dict()
        payload["job_description_title"] = jd.title
        history.append(payload)
    return {
        "candidate": candidate.to_dict(),
        "profile": profile.to_dict() if profile else None,
        "analysis": analysis.to_dict() if analysis else None,
        "analysis_history": history,
    }


@router.get("/analysis-runs/{run_id}")
async def get_analysis_run(
    run_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Get full analysis run details."""
    result = await db.execute(
        select(CandidateAnalysisRun, JobDescription)
        .join(JobDescription, CandidateAnalysisRun.job_description_id == JobDescription.id)
        .where(CandidateAnalysisRun.id == run_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Analysis run not found")

    run, jd = row
    payload = run.to_dict()
    payload["job_description_title"] = jd.title
    return payload


@router.get("/analysis-runs/{run_id}/pdf")
async def download_analysis_run_pdf(
    run_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Download a single analysis-run report as PDF."""
    result = await db.execute(
        select(CandidateAnalysisRun, Candidate, JobDescription)
        .join(Candidate, Candidate.id == CandidateAnalysisRun.candidate_id)
        .join(JobDescription, JobDescription.id == CandidateAnalysisRun.job_description_id)
        .where(CandidateAnalysisRun.id == run_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Analysis run not found")

    run, candidate, jd = row
    pdf_bytes = build_candidate_analysis_pdf(
        candidate.to_dict(),
        run.to_dict(),
        jd.to_dict(),
    )
    safe_name = _safe_filename(candidate.name or f"candidate_{candidate.id}")
    filename = f"{safe_name}_{candidate.id}_analysis_run_{run.id}.pdf"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)


@router.put("/{candidate_id}", response_model=CandidateResponse)
async def update_candidate(
    candidate_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    name: Annotated[str | None, Form()] = None,
    email: Annotated[str | None, Form()] = None,
    phone: Annotated[str | None, Form()] = None,
) -> Candidate:
    """Update basic candidate details."""
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    if name:
        candidate.name = name
    if email is not None:
        candidate.email = email
    if phone is not None:
        candidate.phone = phone

    await db.commit()
    await db.refresh(candidate)
    return candidate.to_dict()


@router.get("/{candidate_id}/resume")
async def download_candidate_resume(
    candidate_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """Download stored resume."""
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate or not candidate.resume_file_path:
        raise HTTPException(status_code=404, detail="Resume not found")

    if not os.path.exists(candidate.resume_file_path):
        raise HTTPException(status_code=404, detail="Resume file missing on disk")

    filename = os.path.basename(candidate.resume_file_path)
    with open(candidate.resume_file_path, "rb") as f:
        data = f.read()
    return StreamingResponse(
        BytesIO(data),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/bulk-upload", response_model=list[CandidateResponse], status_code=201)
async def bulk_upload_candidates(
    db: Annotated[AsyncSession, Depends(get_db)],
    job_description_id: Annotated[int | None, Form()] = None,
    files: list[UploadFile] = File(...),
) -> list[Candidate]:
    """Bulk upload resumes from a folder."""
    if job_description_id is not None:
        jd_result = await db.execute(
            select(JobDescription).where(JobDescription.id == job_description_id)
        )
        if not jd_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="Job description not found")

    parser = ResumeParser()
    ollama = OllamaService()
    created: list[Candidate] = []

    for file in files:
        ext = os.path.splitext(file.filename or "")[1].lower()
        if ext not in {".pdf", ".doc", ".docx", ".txt"}:
            continue
        content = await file.read()
        try:
            resume_text = parser.parse_and_clean(file.filename, content)
        except ValueError:
            resume_text = ""
        invalid_resume = not _is_likely_resume(resume_text)
        base_name = os.path.basename(file.filename or "")
        name_guess = os.path.splitext(base_name)[0].replace("_", " ").strip() or "Candidate"
        duplicate = await _find_duplicate_candidate(db, name_guess, _extract_email(resume_text))
        if duplicate:
            continue
        stored_path = _save_resume_file(file.filename, content, name_guess)
        email_guess = _extract_email(resume_text)
        phone_guess = _extract_phone(resume_text)

        candidate = Candidate(
            name=name_guess,
            email=email_guess,
            phone=phone_guess,
            resume_text=resume_text or " ",
            resume_file_path=stored_path,
            job_description_id=job_description_id,
        )
        db.add(candidate)
        await db.flush()
        profile = await _build_profile(candidate.id, resume_text, ollama, invalid_resume, db)
        if job_description_id is not None:
            db.add(
                CandidateJobLink(
                    candidate_id=candidate.id,
                    job_description_id=job_description_id,
                    confidence=1.0,
                    linked_by="manual",
                )
            )
        else:
            await _auto_link_candidate_to_jds(
                db,
                candidate.id,
                resume_text,
                candidate_profile=profile,
                ollama=ollama,
            )
        created.append(candidate)

    await db.commit()
    return [candidate.to_dict() for candidate in created]


@router.get("/analysis/pdf")
async def download_candidates_pdf(
    candidate_ids: Annotated[list[int], Query(alias="candidate_ids")],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """
    Download candidate analyses as separate PDFs bundled in a zip file.
    """
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="candidate_ids query parameter is required")

    result = await db.execute(
        select(Candidate, CandidateAnalysis, JobDescription)
        .join(CandidateAnalysis, Candidate.id == CandidateAnalysis.candidate_id)
        .join(JobDescription, Candidate.job_description_id == JobDescription.id)
        .where(Candidate.id.in_(candidate_ids))
    )
    rows = result.all()
    if not rows:
        raise HTTPException(status_code=404, detail="Candidates not found or analyses missing")

    zip_buffer = BytesIO()
    with ZipFile(zip_buffer, "w", ZIP_DEFLATED) as zip_file:
        for candidate, analysis, jd in rows:
            pdf_bytes = build_candidate_analysis_pdf(
                candidate.to_dict(), analysis.to_dict(), jd.to_dict()
            )
            safe_name = _safe_filename(candidate.name or f"candidate_{candidate.id}")
            filename = f"{safe_name}_{candidate.id}_analysis.pdf"
            zip_file.writestr(filename, pdf_bytes)

    zip_buffer.seek(0)
    headers = {"Content-Disposition": "attachment; filename=candidate_analyses.zip"}
    return StreamingResponse(zip_buffer, media_type="application/zip", headers=headers)


@router.get("/{candidate_id}/analysis/pdf")
async def download_candidate_pdf(
    candidate_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> StreamingResponse:
    """
    Download a single candidate analysis as a PDF file.
    """
    result = await db.execute(
        select(Candidate, CandidateAnalysis, JobDescription)
        .join(CandidateAnalysis, Candidate.id == CandidateAnalysis.candidate_id)
        .join(JobDescription, Candidate.job_description_id == JobDescription.id)
        .where(Candidate.id == candidate_id)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found or analysis missing")

    candidate, analysis, jd = row
    pdf_bytes = build_candidate_analysis_pdf(
        candidate.to_dict(), analysis.to_dict(), jd.to_dict()
    )
    safe_name = _safe_filename(candidate.name or f"candidate_{candidate.id}")
    filename = f"{safe_name}_{candidate.id}_analysis.pdf"
    headers = {"Content-Disposition": f"attachment; filename={filename}"}
    return StreamingResponse(BytesIO(pdf_bytes), media_type="application/pdf", headers=headers)


@router.get("/{candidate_id}", response_model=CandidateWithAnalysisResponse)
async def get_candidate(
    candidate_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Get a specific candidate with their analysis.

    Args:
        candidate_id: Candidate ID
        db: Database session

    Returns:
        Candidate with analysis

    Raises:
        HTTPException: If candidate not found
    """
    result = await db.execute(
        select(Candidate, CandidateAnalysis)
        .outerjoin(CandidateAnalysis, Candidate.id == CandidateAnalysis.candidate_id)
        .where(Candidate.id == candidate_id)
    )

    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Candidate not found")

    candidate, analysis = row

    return {
        "candidate": candidate.to_dict(),
        "analysis": analysis.to_dict() if analysis else None,
    }


@router.post("/{candidate_id}/analyze", response_model=CandidateWithAnalysisResponse)
async def analyze_candidate(
    candidate_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    job_description_id: int | None = None,
) -> dict:
    """
    Analyze a candidate and generate hiring recommendation.

    Args:
        candidate_id: Candidate ID
        db: Database session

    Returns:
        Candidate with analysis

    Raises:
        HTTPException: If candidate not found
    """
    # Verify candidate exists
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    # Run analysis
    agent = HiringAgent()
    analysis = await agent.analyze_candidate(candidate_id, job_description_id, db)

    # Return candidate with analysis
    result = await db.execute(
        select(Candidate, CandidateAnalysis)
        .where(Candidate.id == candidate_id)
        .where(CandidateAnalysis.candidate_id == candidate_id)
    )

    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail="Analysis failed")

    candidate, analysis = row

    return {
        "candidate": candidate.to_dict(),
        "analysis": analysis.to_dict() if analysis else None,
    }


@router.delete("/{candidate_id}", status_code=200)
async def delete_candidate(
    candidate_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """
    Delete a candidate.

    Args:
        candidate_id: Candidate ID
        db: Database session

    Raises:
        HTTPException: If candidate not found
    """
    result = await db.execute(select(Candidate).where(Candidate.id == candidate_id))
    candidate = result.scalar_one_or_none()

    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    resume_path = candidate.resume_file_path
    await db.delete(candidate)
    await db.commit()
    if resume_path and os.path.exists(resume_path):
        try:
            os.remove(resume_path)
        except OSError:
            pass
    return {"status": "deleted", "candidate_id": candidate_id}


async def _resolve_bulk_candidate_ids(payload: dict | list[int], db: AsyncSession) -> list[int]:
    if isinstance(payload, list):
        return [int(candidate_id) for candidate_id in payload]

    candidate_ids = payload.get("candidate_ids") or []
    if candidate_ids:
        return [int(candidate_id) for candidate_id in candidate_ids]

    if not payload.get("all_matching"):
        return []

    filters = payload.get("filters") or {}
    try:
        job_description_id = int(filters.get("job_description_id")) if filters.get("job_description_id") not in (None, "") else None
    except (TypeError, ValueError):
        job_description_id = None
    try:
        min_experience = float(filters.get("min_experience")) if filters.get("min_experience") not in (None, "") else None
    except (TypeError, ValueError):
        min_experience = None
    try:
        max_experience = float(filters.get("max_experience")) if filters.get("max_experience") not in (None, "") else None
    except (TypeError, ValueError):
        max_experience = None
    excluded_ids = [int(candidate_id) for candidate_id in (payload.get("excluded_ids") or [])]

    query = select(Candidate.id).outerjoin(CandidateProfile, Candidate.id == CandidateProfile.candidate_id)
    query = _apply_candidate_filters(
        query,
        job_description_id=job_description_id,
        name=filters.get("name"),
        skills=filters.get("skills"),
        min_experience=min_experience,
        max_experience=max_experience,
        created_from=filters.get("created_from"),
        created_to=filters.get("created_to"),
    )
    if excluded_ids:
        query = query.where(~Candidate.id.in_(excluded_ids))

    result = await db.execute(query)
    return [int(candidate_id) for candidate_id in result.scalars().all()]


@router.post("/bulk-delete")
async def bulk_delete_candidates(
    payload: dict | list[int],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Bulk delete candidates and their resumes."""
    candidate_ids = await _resolve_bulk_candidate_ids(payload, db)
    if not candidate_ids:
        raise HTTPException(status_code=400, detail="candidate_ids required")

    result = await db.execute(select(Candidate).where(Candidate.id.in_(candidate_ids)))
    candidates = list(result.scalars().all())
    resume_paths = [c.resume_file_path for c in candidates if c.resume_file_path]

    for candidate in candidates:
        await db.delete(candidate)
    await db.commit()

    removed_files = 0
    for path in resume_paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                removed_files += 1
            except OSError:
                pass

    return {
        "status": "deleted",
        "deleted_candidates": len(candidates),
        "deleted_files": removed_files,
    }


@router.post("/link-jd")
async def bulk_link_candidates_to_jd(
    payload: dict,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Link candidates to a job description."""
    candidate_ids = await _resolve_bulk_candidate_ids(payload, db)
    job_description_id = payload.get("job_description_id")
    if not candidate_ids or not job_description_id:
        raise HTTPException(status_code=400, detail="candidate_ids and job_description_id required")

    jd_result = await db.execute(
        select(JobDescription).where(JobDescription.id == job_description_id)
    )
    if not jd_result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Job description not found")

    created = 0
    for candidate_id in candidate_ids:
        db.add(
            CandidateJobLink(
                candidate_id=candidate_id,
                job_description_id=job_description_id,
                confidence=1.0,
                linked_by="manual",
            )
        )
        created += 1

    await db.commit()
    return {"status": "linked", "links_created": created}


@router.post("/clear-all")
async def clear_all_candidates(
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Delete all candidates and their resumes."""
    result = await db.execute(select(Candidate))
    candidates = list(result.scalars().all())
    resume_paths = [c.resume_file_path for c in candidates if c.resume_file_path]

    for candidate in candidates:
        await db.delete(candidate)
    await db.commit()

    removed_files = 0
    for path in resume_paths:
        if path and os.path.exists(path):
            try:
                os.remove(path)
                removed_files += 1
            except OSError:
                pass

    return {
        "status": "cleared",
        "deleted_candidates": len(candidates),
        "deleted_files": removed_files,
    }
