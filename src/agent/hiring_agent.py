"""Main hiring agent that orchestrates the entire hiring workflow."""

import asyncio
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from src.agent.scoring_engine import ScoringEngine, ScoringResult
from src.database.connection import get_db_session
from src.database.models import (
    Candidate,
    CandidateAnalysis,
    CandidateAnalysisRun,
    HiringAction,
    JobDescription,
)
from src.llm.ollama_service import OllamaService
from src.parsers.resume_parser import ResumeParser


class HiringAgent:
    """Autonomous AI hiring agent that analyzes candidates and makes hiring decisions."""

    def __init__(self, ollama_service: OllamaService | None = None):
        """
        Initialize hiring agent.

        Args:
            ollama_service: Optional Ollama service instance
        """
        self.ollama = ollama_service or OllamaService()
        self.scoring_engine = ScoringEngine()
        self.resume_parser = ResumeParser()

    async def analyze_candidate(
        self,
        candidate_id: int,
        job_description_id: int | None = None,
        session: AsyncSession | None = None,
    ) -> CandidateAnalysis:
        """
        Analyze a candidate and generate hiring recommendation.

        Args:
            candidate_id: ID of the candidate to analyze
            session: Optional database session

        Returns:
            CandidateAnalysis with complete analysis results
        """
        should_close_session = False

        if session is None:
            session_context = get_db_session()
            session = await session_context.__aenter__()
            should_close_session = True

        try:
            # Fetch candidate with job description
            result = await session.execute(
                select(Candidate)
                .where(Candidate.id == candidate_id)
                .options(selectinload(Candidate.job_description))
            )
            candidate = result.scalar_one_or_none()

            if not candidate:
                raise ValueError(f"Candidate not found: {candidate_id}")

            if job_description_id is not None:
                jd_result = await session.execute(
                    select(JobDescription).where(JobDescription.id == job_description_id)
                )
                jd = jd_result.scalar_one_or_none()
            else:
                jd = candidate.job_description

            if not jd:
                raise ValueError(f"Job description not found for candidate: {candidate_id}")

            # Run LLM analysis
            analysis_data = await self.ollama.analyze_resume(
                resume_text=candidate.resume_text,
                jd_text=jd.description,
            )
            if analysis_data is None:
                raise ValueError("LLM returned no analysis data")

            analysis_data = self._normalize_analysis_data(analysis_data)
            analysis_data = self._ensure_min_interview_questions(analysis_data, candidate, jd)

            # Calculate scores and decision
            scoring_result = self.scoring_engine.score_candidate(analysis_data)

            # Update analysis data with scoring results
            analysis_data.update(
                {
                    "skill_match_score": scoring_result.skill_match_score,
                    "experience_score": scoring_result.experience_score,
                    "domain_score": scoring_result.domain_score,
                    "project_complexity_score": scoring_result.project_complexity_score,
                    "soft_skills_score": scoring_result.soft_skills_score,
                    "final_score": scoring_result.final_score,
                    "decision": scoring_result.decision,
                    "recommendation": scoring_result.recommendation,
                    "analysis_timestamp": datetime.utcnow(),
                    "model_used": self.ollama.model,
                }
            )

            # Create immutable analysis run per JD
            analysis_run = CandidateAnalysisRun(
                candidate_id=candidate_id,
                job_description_id=jd.id,
                **analysis_data,
            )
            session.add(analysis_run)

            # Check if analysis already exists
            existing_analysis = await session.execute(
                select(CandidateAnalysis).where(CandidateAnalysis.candidate_id == candidate_id)
            )
            existing = existing_analysis.scalar_one_or_none()

            if existing:
                # Update existing analysis
                for key, value in analysis_data.items():
                    setattr(existing, key, value)
                analysis = existing
            else:
                # Create new analysis
                analysis = CandidateAnalysis(
                    candidate_id=candidate_id,
                    **analysis_data,
                )
                session.add(analysis)

            for attempt in range(1, 4):
                try:
                    await session.commit()
                    break
                except OperationalError as exc:
                    if "database is locked" not in str(exc).lower():
                        raise
                    if attempt == 3:
                        raise
                    await session.rollback()
                    await asyncio.sleep(0.5 * attempt)
            await session.refresh(analysis)

            # Log action
            await self._log_action(
                session=session,
                candidate_id=candidate_id,
                action_type="analysis_completed",
                description=f"Candidate analyzed with score {scoring_result.final_score}/100",
            )

            return analysis

        finally:
            if should_close_session:
                await session.close()

    @staticmethod
    def _normalize_analysis_data(analysis_data: dict[str, Any]) -> dict[str, Any]:
        """Normalize nullable list fields from the LLM."""
        list_fields = [
            "skills",
            "tech_stack",
            "domain_knowledge",
            "strengths",
            "weaknesses",
            "risks",
            "technical_questions",
            "system_design_questions",
            "behavioral_questions",
            "custom_questions",
            "interview_focus_areas",
        ]
        for field in list_fields:
            value = analysis_data.get(field)
            if not isinstance(value, list):
                analysis_data[field] = []
        return analysis_data

    @staticmethod
    def _ensure_min_interview_questions(
        analysis_data: dict[str, Any],
        candidate: Candidate,
        jd: JobDescription,
    ) -> dict[str, Any]:
        """Ensure at least 5 questions per interview section."""
        skills = analysis_data.get("skills") or analysis_data.get("tech_stack") or []
        primary_skill = skills[0] if skills else "the core technologies"
        role_title = jd.title or "this role"
        domain = jd.domain or "the domain"

        def normalize_list(value: Any) -> list[str]:
            if not isinstance(value, list):
                return []
            cleaned = []
            for item in value:
                if isinstance(item, str):
                    stripped = item.strip()
                    if stripped:
                        cleaned.append(stripped)
            return cleaned

        def ensure_minimum(key: str, fallbacks: list[str]) -> None:
            questions = normalize_list(analysis_data.get(key))
            for fallback in fallbacks:
                if len(questions) >= 5:
                    break
                if fallback not in questions:
                    questions.append(fallback)
            while len(questions) < 5:
                questions.append(f"Additional {key.replace('_', ' ')} question {len(questions) + 1} for {role_title}.")
            analysis_data[key] = questions

        ensure_minimum(
            "technical_questions",
            [
                f"Walk through a recent project where you used {primary_skill}. What were the hardest technical challenges?",
                f"How do you validate correctness and reliability in your {primary_skill} work?",
                "Explain a performance issue you diagnosed and fixed in a system you built.",
                "Describe your approach to testing and code reviews in production systems.",
                "How do you handle backward compatibility and deployment risk in production?",
            ],
        )
        ensure_minimum(
            "system_design_questions",
            [
                f"Design a scalable service relevant to {role_title}. Start with requirements and outline the architecture.",
                f"How would you design data storage and access patterns for {domain} workloads?",
                "Discuss how you would handle failures, retries, and observability in a distributed system.",
                "How would you scale the system as traffic grows 10x?",
                "Describe tradeoffs between consistency and availability for a core feature in this role.",
            ],
        )
        ensure_minimum(
            "behavioral_questions",
            [
                "Tell me about a time you disagreed with a teammate. How did you resolve it?",
                "Describe a situation where you had to learn a new technology quickly.",
                "Give an example of a project you led end-to-end and how you managed stakeholders.",
                "Tell me about a time you received critical feedback and what you changed.",
                "Describe a time you improved a process or team outcome.",
            ],
        )
        ensure_minimum(
            "custom_questions",
            [
                f"What would your 30-60-90 day plan look like for {role_title}?",
                "Which part of the job description are you most excited about and why?",
                "What risks do you see in this role and how would you mitigate them?",
                "How do you decide when to ask for help versus push through on your own?",
                "Tell us about a tradeoff you made in a recent project and why.",
            ],
        )

        return analysis_data

    async def process_resume(
        self,
        resume_text: str,
        job_description_id: int,
        name: str,
        email: str | None = None,
        phone: str | None = None,
        resume_file_path: str | None = None,
    ) -> Candidate:
        """
        Process a new resume and create candidate record.

        Args:
            resume_text: Resume text content
            job_description_id: ID of the job description
            name: Candidate name
            email: Candidate email
            phone: Candidate phone
            resume_file_path: Path to resume file

        Returns:
            Created Candidate record
        """
        async with get_db_session() as session:
            # Verify job description exists
            result = await session.execute(
                select(JobDescription).where(JobDescription.id == job_description_id)
            )
            jd = result.scalar_one_or_none()

            if not jd:
                raise ValueError(f"Job description not found: {job_description_id}")

            # Create candidate
            candidate = Candidate(
                name=name,
                email=email,
                phone=phone,
                resume_text=resume_text,
                resume_file_path=resume_file_path,
                job_description_id=job_description_id,
            )
            session.add(candidate)
            await session.commit()
            await session.refresh(candidate)

            # Log action
            await self._log_action(
                session=session,
                candidate_id=candidate.id,
                action_type="candidate_created",
                description=f"Candidate created from resume",
            )

            return candidate

    async def process_resume_file(
        self,
        file_path: str,
        job_description_id: int,
        name: str,
        email: str | None = None,
        phone: str | None = None,
    ) -> Candidate:
        """
        Process a resume file and create candidate record.

        Args:
            file_path: Path to resume file
            job_description_id: ID of the job description
            name: Candidate name
            email: Candidate email
            phone: Candidate phone

        Returns:
            Created Candidate record
        """
        # Parse resume file
        resume_text = self.resume_parser.parse_and_clean(file_path)

        return await self.process_resume(
            resume_text=resume_text,
            job_description_id=job_description_id,
            name=name,
            email=email,
            phone=phone,
            resume_file_path=file_path,
        )

    async def create_job_description(
        self,
        title: str,
        description: str,
        required_skills: list[str],
        min_experience_years: int = 0,
        domain: str | None = None,
    ) -> JobDescription:
        """
        Create a new job description.

        Args:
            title: Job title
            description: Job description text
            required_skills: List of required skills
            min_experience_years: Minimum years of experience
            domain: Primary domain

        Returns:
            Created JobDescription record
        """
        async with get_db_session() as session:
            jd = JobDescription(
                title=title,
                description=description,
                required_skills=required_skills,
                min_experience_years=min_experience_years,
                domain=domain,
            )
            session.add(jd)
            await session.commit()
            await session.refresh(jd)

            return jd

    async def rank_candidates(
        self,
        job_description_id: int,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        """
        Rank candidates for a job description.

        Args:
            job_description_id: ID of the job description
            limit: Maximum number of candidates to return

        Returns:
            Ranked list of candidates with analysis
        """
        async with get_db_session() as session:
            # Fetch latest analysis run per candidate for this JD
            latest_subq = (
                select(
                    CandidateAnalysisRun.candidate_id.label("candidate_id"),
                    CandidateAnalysisRun.job_description_id.label("job_description_id"),
                    func.max(CandidateAnalysisRun.id).label("latest_id"),
                )
                .where(CandidateAnalysisRun.job_description_id == job_description_id)
                .group_by(CandidateAnalysisRun.candidate_id, CandidateAnalysisRun.job_description_id)
                .subquery()
            )
            result = await session.execute(
                select(Candidate, CandidateAnalysisRun)
                .join(latest_subq, latest_subq.c.candidate_id == Candidate.id)
                .join(CandidateAnalysisRun, CandidateAnalysisRun.id == latest_subq.c.latest_id)
                .where(Candidate.job_description_id == job_description_id)
                .order_by(CandidateAnalysisRun.final_score.desc())
                .limit(limit)
            )

            candidates = []
            for candidate, analysis in result:
                candidates.append(
                    {
                        "candidate": candidate.to_dict(),
                        "analysis": analysis.to_dict(),
                    }
                )

            return candidates

    async def generate_hiring_report(
        self,
        job_description_id: int,
    ) -> dict[str, Any]:
        """
        Generate a comprehensive hiring report.

        Args:
            job_description_id: ID of the job description

        Returns:
            Hiring report with statistics and recommendations
        """
        async with get_db_session() as session:
            # Fetch job description
            jd_result = await session.execute(
                select(JobDescription).where(JobDescription.id == job_description_id)
            )
            jd = jd_result.scalar_one_or_none()

            if not jd:
                raise ValueError(f"Job description not found: {job_description_id}")

            # Fetch latest analysis run per candidate for this JD
            latest_subq = (
                select(
                    CandidateAnalysisRun.candidate_id.label("candidate_id"),
                    CandidateAnalysisRun.job_description_id.label("job_description_id"),
                    func.max(CandidateAnalysisRun.id).label("latest_id"),
                )
                .where(CandidateAnalysisRun.job_description_id == job_description_id)
                .group_by(CandidateAnalysisRun.candidate_id, CandidateAnalysisRun.job_description_id)
                .subquery()
            )
            result = await session.execute(
                select(Candidate, CandidateAnalysisRun)
                .join(latest_subq, latest_subq.c.candidate_id == Candidate.id)
                .join(CandidateAnalysisRun, CandidateAnalysisRun.id == latest_subq.c.latest_id)
                .where(Candidate.job_description_id == job_description_id)
            )

            candidates_data = []
            strong_hires = []
            borderline = []
            rejects = []

            for candidate, analysis in result:
                candidate_data = {
                    "candidate": candidate.to_dict(),
                    "analysis": analysis.to_dict(),
                }
                candidates_data.append(candidate_data)

                if analysis.decision == "strong_hire":
                    strong_hires.append(candidate_data)
                elif analysis.decision == "borderline":
                    borderline.append(candidate_data)
                else:
                    rejects.append(candidate_data)

            # Calculate statistics
            total = len(candidates_data)
            avg_score = sum(c["analysis"]["final_score"] for c in candidates_data) / total if total > 0 else 0

            report = {
                "job_description": jd.to_dict(),
                "summary": {
                    "total_candidates": total,
                    "strong_hires": len(strong_hires),
                    "borderline": len(borderline),
                    "rejects": len(rejects),
                    "average_score": round(avg_score, 2),
                },
                "ranked_candidates": self.scoring_engine.rank_candidates(
                    [c["analysis"] for c in candidates_data]
                ),
                "strong_hires": strong_hires,
                "borderline": borderline,
                "rejects": rejects,
                "generated_at": datetime.utcnow().isoformat(),
            }

            return report

    async def get_interview_strategy(
        self,
        candidate_id: int,
    ) -> dict[str, Any]:
        """
        Get interview strategy for a candidate.

        Args:
            candidate_id: ID of the candidate

        Returns:
            Interview strategy with questions and focus areas
        """
        async with get_db_session() as session:
            # Fetch candidate with analysis and JD
            result = await session.execute(
                select(Candidate, JobDescription)
                .join(JobDescription, Candidate.job_description_id == JobDescription.id)
                .where(Candidate.id == candidate_id)
            )
            row = result.first()
            if not row:
                raise ValueError(f"Candidate not found: {candidate_id}")

            candidate, jd = row

            run_result = await session.execute(
                select(CandidateAnalysisRun)
                .where(
                    CandidateAnalysisRun.candidate_id == candidate_id,
                    CandidateAnalysisRun.job_description_id == jd.id,
                )
                .order_by(CandidateAnalysisRun.id.desc())
            )
            analysis = run_result.scalars().first()
            if not analysis:
                # fallback to latest analysis
                legacy_result = await session.execute(
                    select(CandidateAnalysis).where(CandidateAnalysis.candidate_id == candidate_id)
                )
                analysis = legacy_result.scalar_one_or_none()
            if not analysis:
                raise ValueError(f"Candidate analysis not found: {candidate_id}")

            return {
                "candidate": candidate.to_dict(),
                "analysis": analysis.to_dict(),
                "interview_strategy": {
                    "technical_questions": analysis.technical_questions,
                    "system_design_questions": analysis.system_design_questions,
                    "behavioral_questions": analysis.behavioral_questions,
                    "custom_questions": analysis.custom_questions,
                    "focus_areas": analysis.interview_focus_areas,
                    "risk_level": analysis.risk_level,
                    "risks_to_explore": analysis.risks,
                },
            }

    async def _log_action(
        self,
        session: AsyncSession,
        candidate_id: int,
        action_type: str,
        description: str,
    ) -> None:
        """Log a hiring action."""
        action = HiringAction(
            candidate_id=candidate_id,
            action_type=action_type,
            description=description,
            performed_by="system",
        )
        session.add(action)
