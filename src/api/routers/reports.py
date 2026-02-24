"""Router for reports and analytics endpoints."""

from collections import defaultdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.hiring_agent import HiringAgent
from src.api.schemas import (
    HiringReportResponse,
    InterviewStrategyResponse,
)
from src.database.connection import get_db
from src.database.models import (
    Candidate,
    CandidateAnalysisRun,
    CandidateJobLink,
    CandidateProfile,
    JobDescription,
)

router = APIRouter(prefix="/reports", tags=["Reports"])


def _normalize_skill(skill: str) -> str:
    return " ".join((skill or "").strip().lower().split())


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _candidate_public(candidate: Candidate) -> dict[str, Any]:
    return {
        "id": candidate.id,
        "name": candidate.name,
        "email": candidate.email,
        "phone": candidate.phone,
        "resume_file_path": candidate.resume_file_path,
        "created_at": candidate.created_at.isoformat() if candidate.created_at else None,
    }


def _profile_public(profile: CandidateProfile | None) -> dict[str, Any] | None:
    if not profile:
        return None
    return {
        "current_role": profile.current_role,
        "headline": profile.headline,
        "total_experience_years": profile.total_experience_years,
        "primary_skills": profile.primary_skills or [],
        "secondary_skills": profile.secondary_skills or [],
        "summary": profile.summary,
        "location": profile.location,
        "invalid_resume": profile.invalid_resume,
    }


def _collect_candidate_skills(
    profile: CandidateProfile | None,
    analysis: dict[str, Any] | None,
) -> list[str]:
    raw_skills: list[str] = []
    if profile:
        raw_skills.extend(profile.primary_skills or [])
        raw_skills.extend(profile.secondary_skills or [])
    if not raw_skills and analysis:
        raw_skills.extend(analysis.get("skills") or [])
        raw_skills.extend(analysis.get("tech_stack") or [])

    deduped: list[str] = []
    seen: set[str] = set()
    for skill in raw_skills:
        cleaned = " ".join(str(skill or "").strip().split())
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


def _compute_skill_match(
    required_skills: list[str],
    candidate_skills: list[str],
) -> tuple[float, list[str]]:
    required_set = {_normalize_skill(skill) for skill in (required_skills or []) if _normalize_skill(skill)}
    if not required_set:
        return 0.0, []

    candidate_map: dict[str, str] = {}
    for skill in candidate_skills:
        normalized = _normalize_skill(skill)
        if not normalized:
            continue
        candidate_map[normalized] = skill

    matched_keys = sorted(required_set.intersection(set(candidate_map.keys())))
    matched_skills = [candidate_map[key] for key in matched_keys]
    score = (len(matched_keys) / len(required_set)) * 100.0
    return round(score, 2), matched_skills


def _build_rank_entry(
    *,
    candidate: Candidate,
    profile: CandidateProfile | None,
    analysis: dict[str, Any] | None,
    required_skills: list[str],
) -> dict[str, Any]:
    experience_from_profile = profile.total_experience_years if profile else None
    experience_from_analysis = analysis.get("experience_years") if analysis else None
    experience_years = _safe_float(
        experience_from_profile if experience_from_profile is not None else experience_from_analysis,
        default=0.0,
    )
    is_fresher = abs(experience_years) < 1e-9

    candidate_skills = _collect_candidate_skills(profile, analysis)
    skill_match_score, matched_skills = _compute_skill_match(required_skills, candidate_skills)
    ranking_score = _safe_float(analysis.get("final_score") if analysis else None, default=0.0)

    return {
        "candidate": _candidate_public(candidate),
        "profile": _profile_public(profile),
        "analysis": analysis,
        "experience_years": experience_years,
        "is_fresher": is_fresher,
        "ranking_score": round(ranking_score, 2),
        "skill_match_score": skill_match_score,
        "candidate_skills": candidate_skills,
        "matched_skills": matched_skills,
    }


@router.get("/hiring/{job_description_id}", response_model=HiringReportResponse)
async def get_hiring_report(
    job_description_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Generate a comprehensive hiring report for a job description.

    Args:
        job_description_id: Job description ID
        db: Database session

    Returns:
        Hiring report with statistics and recommendations

    Raises:
        HTTPException: If job description not found
    """
    agent = HiringAgent()
    report = await agent.generate_hiring_report(job_description_id)
    return report


@router.get("/interview-strategy/{candidate_id}", response_model=InterviewStrategyResponse)
async def get_interview_strategy(
    candidate_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Get interview strategy for a specific candidate.

    Args:
        candidate_id: Candidate ID
        db: Database session

    Returns:
        Interview strategy with questions and focus areas

    Raises:
        HTTPException: If candidate not found
    """
    agent = HiringAgent()
    strategy = await agent.get_interview_strategy(candidate_id)
    return strategy


@router.get("/ranking/{job_description_id}")
async def get_candidate_ranking(
    job_description_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    limit: Annotated[int, Query] = 10,
) -> dict:
    """
    Get ranked candidates for a job description.

    Args:
        job_description_id: Job description ID
        limit: Maximum number of candidates to return
        db: Database session

    Returns:
        Ranked list of candidates
    """
    agent = HiringAgent()
    ranked = await agent.rank_candidates(job_description_id, limit)
    return {
        "job_description_id": job_description_id,
        "candidates": ranked,
    }


@router.get("/ranking-grouped")
async def get_grouped_candidate_ranking(
    db: Annotated[AsyncSession, Depends(get_db)],
    job_description_id: Annotated[int | None, Query()] = None,
    q: Annotated[str | None, Query(description="Candidate name/email search")] = None,
    decision: Annotated[
        str | None,
        Query(description="Comma-separated decisions (e.g. strong_hire,borderline)"),
    ] = None,
    include_unassigned: Annotated[bool, Query()] = True,
    limit_per_group: Annotated[int, Query(ge=1, le=500)] = 100,
) -> dict[str, Any]:
    """
    Grouped candidate ranking for HR search:
    - grouped by job description
    - experienced ranked by analysis score
    - freshers (experience == 0) sorted by skill match
    - optional unassigned bucket (no JD link)
    """
    query_text = (q or "").strip().lower()
    decision_filter = {
        item.strip().lower()
        for item in (decision or "").split(",")
        if item and item.strip()
    }

    jd_query = select(JobDescription).order_by(JobDescription.title.asc())
    if job_description_id is not None:
        jd_query = jd_query.where(JobDescription.id == job_description_id)
    jd_rows = await db.execute(jd_query)
    jds = jd_rows.scalars().all()
    if job_description_id is not None and not jds:
        raise HTTPException(status_code=404, detail="Job description not found")

    jd_map: dict[int, JobDescription] = {jd.id: jd for jd in jds}
    if not jd_map:
        return {
            "filters": {
                "job_description_id": job_description_id,
                "q": q,
                "decision": sorted(decision_filter),
                "include_unassigned": include_unassigned,
                "limit_per_group": limit_per_group,
                "fresher_rule": "experience_years == 0",
            },
            "groups": [],
            "unassigned": {"experienced": [], "freshers": []},
            "summary": {"group_count": 0, "total_candidates": 0},
        }

    candidate_rows = await db.execute(
        select(Candidate, CandidateProfile)
        .outerjoin(CandidateProfile, CandidateProfile.candidate_id == Candidate.id)
        .order_by(Candidate.created_at.desc())
    )

    candidate_map: dict[int, tuple[Candidate, CandidateProfile | None]] = {}
    for candidate, profile in candidate_rows.all():
        if query_text:
            haystack = f"{candidate.name or ''} {candidate.email or ''}".lower()
            if query_text not in haystack:
                continue
        candidate_map[candidate.id] = (candidate, profile)

    if not candidate_map:
        return {
            "filters": {
                "job_description_id": job_description_id,
                "q": q,
                "decision": sorted(decision_filter),
                "include_unassigned": include_unassigned,
                "limit_per_group": limit_per_group,
                "fresher_rule": "experience_years == 0",
            },
            "groups": [],
            "unassigned": {"experienced": [], "freshers": []},
            "summary": {"group_count": 0, "total_candidates": 0},
        }

    link_rows = await db.execute(
        select(CandidateJobLink.candidate_id, CandidateJobLink.job_description_id)
    )
    all_links = link_rows.all()
    assigned_candidate_ids = {candidate_id for candidate_id, _ in all_links}

    filtered_links = []
    for candidate_id, jd_id in all_links:
        if candidate_id not in candidate_map:
            continue
        if jd_id not in jd_map:
            continue
        filtered_links.append((candidate_id, jd_id))

    latest_pair_subq = (
        select(
            CandidateAnalysisRun.candidate_id.label("candidate_id"),
            CandidateAnalysisRun.job_description_id.label("job_description_id"),
            func.max(CandidateAnalysisRun.id).label("latest_id"),
        )
        .group_by(CandidateAnalysisRun.candidate_id, CandidateAnalysisRun.job_description_id)
    )
    if job_description_id is not None:
        latest_pair_subq = latest_pair_subq.where(CandidateAnalysisRun.job_description_id == job_description_id)
    latest_pair_subq = latest_pair_subq.subquery()

    analysis_rows = await db.execute(
        select(CandidateAnalysisRun)
        .join(latest_pair_subq, CandidateAnalysisRun.id == latest_pair_subq.c.latest_id)
    )
    analysis_by_pair: dict[tuple[int, int], dict[str, Any]] = {}
    for run in analysis_rows.scalars().all():
        analysis_by_pair[(run.candidate_id, run.job_description_id)] = run.to_dict()

    latest_overall_subq = (
        select(
            CandidateAnalysisRun.candidate_id.label("candidate_id"),
            func.max(CandidateAnalysisRun.id).label("latest_id"),
        )
        .group_by(CandidateAnalysisRun.candidate_id)
        .subquery()
    )
    latest_overall_rows = await db.execute(
        select(CandidateAnalysisRun)
        .join(latest_overall_subq, CandidateAnalysisRun.id == latest_overall_subq.c.latest_id)
    )
    latest_analysis_by_candidate: dict[int, dict[str, Any]] = {}
    for run in latest_overall_rows.scalars().all():
        latest_analysis_by_candidate[run.candidate_id] = run.to_dict()

    grouped: dict[int, dict[str, list[dict[str, Any]]]] = defaultdict(
        lambda: {"experienced": [], "freshers": []}
    )

    for candidate_id, jd_id in filtered_links:
        candidate, profile = candidate_map[candidate_id]
        jd = jd_map[jd_id]
        analysis = analysis_by_pair.get((candidate_id, jd_id))

        if decision_filter:
            decision_value = (analysis or {}).get("decision")
            if not decision_value or decision_value.lower() not in decision_filter:
                continue

        entry = _build_rank_entry(
            candidate=candidate,
            profile=profile,
            analysis=analysis,
            required_skills=jd.required_skills or [],
        )
        if entry["is_fresher"]:
            grouped[jd_id]["freshers"].append(entry)
        else:
            grouped[jd_id]["experienced"].append(entry)

    groups_payload: list[dict[str, Any]] = []
    total_candidates = 0

    for jd in sorted(jds, key=lambda item: (item.title or "").lower()):
        bucket = grouped.get(jd.id)
        if not bucket:
            continue

        experienced_sorted = sorted(
            bucket["experienced"],
            key=lambda item: (
                -_safe_float(item.get("ranking_score"), default=0.0),
                -_safe_float(item.get("skill_match_score"), default=0.0),
                (item.get("candidate", {}).get("name") or "").lower(),
            ),
        )
        freshers_sorted = sorted(
            bucket["freshers"],
            key=lambda item: (
                -_safe_float(item.get("skill_match_score"), default=0.0),
                -_safe_float(item.get("ranking_score"), default=0.0),
                (item.get("candidate", {}).get("name") or "").lower(),
            ),
        )

        for idx, row in enumerate(experienced_sorted, start=1):
            row["rank"] = idx
        for idx, row in enumerate(freshers_sorted, start=1):
            row["skill_rank"] = idx

        experienced_limited = experienced_sorted[:limit_per_group]
        freshers_limited = freshers_sorted[:limit_per_group]
        total_candidates += len(experienced_limited) + len(freshers_limited)

        groups_payload.append(
            {
                "job_description": {
                    "id": jd.id,
                    "title": jd.title,
                    "domain": jd.domain,
                    "required_skills": jd.required_skills or [],
                    "min_experience_years": jd.min_experience_years,
                },
                "counts": {
                    "experienced": len(experienced_sorted),
                    "freshers": len(freshers_sorted),
                    "total": len(experienced_sorted) + len(freshers_sorted),
                },
                "experienced": experienced_limited,
                "freshers": freshers_limited,
            }
        )

    unassigned = {"experienced": [], "freshers": []}
    if include_unassigned:
        for candidate_id, (candidate, profile) in candidate_map.items():
            if candidate_id in assigned_candidate_ids:
                continue
            analysis = latest_analysis_by_candidate.get(candidate_id)

            if decision_filter:
                decision_value = (analysis or {}).get("decision")
                if not decision_value or decision_value.lower() not in decision_filter:
                    continue

            entry = _build_rank_entry(
                candidate=candidate,
                profile=profile,
                analysis=analysis,
                required_skills=[],
            )
            if entry["is_fresher"]:
                unassigned["freshers"].append(entry)
            else:
                unassigned["experienced"].append(entry)

        unassigned["experienced"] = sorted(
            unassigned["experienced"],
            key=lambda item: (
                -_safe_float(item.get("ranking_score"), default=0.0),
                (item.get("candidate", {}).get("name") or "").lower(),
            ),
        )[:limit_per_group]
        unassigned["freshers"] = sorted(
            unassigned["freshers"],
            key=lambda item: (
                -_safe_float(item.get("skill_match_score"), default=0.0),
                -len(item.get("candidate_skills") or []),
                (item.get("candidate", {}).get("name") or "").lower(),
            ),
        )[:limit_per_group]

        for idx, row in enumerate(unassigned["experienced"], start=1):
            row["rank"] = idx
        for idx, row in enumerate(unassigned["freshers"], start=1):
            row["skill_rank"] = idx

        total_candidates += len(unassigned["experienced"]) + len(unassigned["freshers"])

    return {
        "filters": {
            "job_description_id": job_description_id,
            "q": q,
            "decision": sorted(decision_filter),
            "include_unassigned": include_unassigned,
            "limit_per_group": limit_per_group,
            "fresher_rule": "experience_years == 0",
        },
        "groups": groups_payload,
        "unassigned": unassigned,
        "summary": {
            "group_count": len(groups_payload),
            "total_candidates": total_candidates,
        },
    }
