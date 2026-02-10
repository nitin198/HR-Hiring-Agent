"""Router for job description endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    JobDescriptionCreate,
    JobDescriptionUpdate,
)
from src.database.connection import get_db
from src.database.models import JobDescription

router = APIRouter(prefix="/job-descriptions", tags=["Job Descriptions"])


@router.post("", response_model=dict, status_code=201)
async def create_job_description(
    jd_data: JobDescriptionCreate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Create a new job description.

    Args:
        jd_data: Job description data
        db: Database session

    Returns:
        Created job description
    """
    jd = JobDescription(
        title=jd_data.title,
        description=jd_data.description,
        required_skills=jd_data.required_skills,
        min_experience_years=jd_data.min_experience_years,
        domain=jd_data.domain,
    )
    db.add(jd)
    await db.commit()
    await db.refresh(jd)
    return jd.to_dict()


@router.get("")
async def list_job_descriptions(
    db: Annotated[AsyncSession, Depends(get_db)],
    skip: Annotated[int, Query] = 0,
    limit: Annotated[int, Query] = 100,
) -> list[dict]:
    """
    List all job descriptions.

    Args:
        skip: Number of records to skip
        limit: Maximum number of records to return
        db: Database session

    Returns:
        List of job descriptions
    """
    result = await db.execute(
        select(JobDescription)
        .order_by(JobDescription.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return [jd.to_dict() for jd in result.scalars().all()]


@router.get("/{jd_id}")
async def get_job_description(
    jd_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Get a specific job description by ID.

    Args:
        jd_id: Job description ID
        db: Database session

    Returns:
        Job description

    Raises:
        HTTPException: If job description not found
    """
    result = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = result.scalar_one_or_none()

    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")

    return jd.to_dict()


@router.put("/{jd_id}", response_model=dict)
async def update_job_description(
    jd_id: int,
    jd_data: JobDescriptionUpdate,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """
    Update an existing job description.

    Args:
        jd_id: Job description ID
        jd_data: Updated job description data
        db: Database session

    Returns:
        Updated job description

    Raises:
        HTTPException: If job description not found
    """
    result = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = result.scalar_one_or_none()

    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")

    # Update fields if provided
    if jd_data.title is not None:
        jd.title = jd_data.title
    if jd_data.description is not None:
        jd.description = jd_data.description
    if jd_data.required_skills is not None:
        jd.required_skills = jd_data.required_skills
    if jd_data.min_experience_years is not None:
        jd.min_experience_years = jd_data.min_experience_years
    if jd_data.domain is not None:
        jd.domain = jd_data.domain

    await db.commit()
    await db.refresh(jd)
    return jd.to_dict()


@router.delete("/{jd_id}", status_code=204)
async def delete_job_description(
    jd_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """
    Delete a job description.

    Args:
        jd_id: Job description ID
        db: Database session

    Raises:
        HTTPException: If job description not found
    """
    result = await db.execute(select(JobDescription).where(JobDescription.id == jd_id))
    jd = result.scalar_one_or_none()

    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")

    await db.delete(jd)
    await db.commit()