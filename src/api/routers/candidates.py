"""Router for candidate endpoints."""

import base64
from io import BytesIO
import re
import os
from datetime import datetime
from typing import Annotated
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
        try:
            llm_profile = await ollama.extract_candidate_profile(resume_text)
            profile_data.update(
                {
                    "current_role": llm_profile.get("current_role"),
                    "headline": llm_profile.get("headline"),
                    "total_experience_years": llm_profile.get("total_experience_years") or 0.0,
                    "primary_skills": llm_profile.get("primary_skills") or [],
                    "secondary_skills": llm_profile.get("secondary_skills") or [],
                    "education": llm_profile.get("education"),
                    "certifications": llm_profile.get("certifications") or [],
                    "summary": llm_profile.get("summary"),
                    "location": llm_profile.get("location"),
                    "linkedin_url": llm_profile.get("linkedin_url"),
                    "portfolio_url": llm_profile.get("portfolio_url"),
                }
            )
        except Exception:
            pass

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
    max_links: int = 3,
) -> list[CandidateJobLink]:
    jd_result = await db.execute(select(JobDescription))
    jds = list(jd_result.scalars().all())
    if not jds:
        return []

    resume_lower = (resume_text or "").lower()
    scored: list[tuple[JobDescription, float]] = []
    for jd in jds:
        required_skills = [skill.lower() for skill in (jd.required_skills or [])]
        skill_matches = sum(1 for skill in required_skills if skill and skill in resume_lower)
        title_hit = 1 if jd.title and jd.title.lower() in resume_lower else 0
        domain_hit = 1 if jd.domain and jd.domain.lower() in resume_lower else 0
        score = skill_matches * 2 + title_hit + domain_hit
        if score > 0:
            scored.append((jd, float(score)))

    scored.sort(key=lambda item: item[1], reverse=True)
    if not scored:
        return []

    best_score = scored[0][1]
    selected = [item for item in scored if item[1] >= best_score - 1][:max_links]

    links: list[CandidateJobLink] = []
    for jd, score in selected:
        link = CandidateJobLink(
            candidate_id=candidate_id,
            job_description_id=jd.id,
            confidence=score,
            linked_by="ai",
        )
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

    await _build_profile(candidate.id, resume_text, llm, invalid_resume, db)
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
        await _auto_link_candidate_to_jds(db, candidate.id, resume_text)

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
        await _build_profile(candidate.id, resume_text, ollama, invalid_resume, db)
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
            await _auto_link_candidate_to_jds(db, candidate.id, resume_text)
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
