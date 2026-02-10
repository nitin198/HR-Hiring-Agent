"""Router for reports and analytics endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from src.agent.hiring_agent import HiringAgent
from src.api.schemas import (
    HiringReportResponse,
    InterviewStrategyResponse,
)
from src.database.connection import get_db

router = APIRouter(prefix="/reports", tags=["Reports"])


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