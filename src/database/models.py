"""Database models for the hiring agent."""

from datetime import datetime
from enum import Enum

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all models."""

    pass


class Decision(str, Enum):
    """Hiring decision types."""

    STRONG_HIRE = "strong_hire"
    BORDERLINE = "borderline"
    REJECT = "reject"
    HOLD = "hold"


class JobDescription(Base):
    """Job description model."""

    __tablename__ = "job_descriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    required_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    min_experience_years: Mapped[int] = mapped_column(Integer, default=0)
    domain: Mapped[str] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    candidates: Mapped[list["Candidate"]] = relationship(back_populates="job_description", cascade="all, delete-orphan")
    candidate_links: Mapped[list["CandidateJobLink"]] = relationship(
        back_populates="job_description",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "title": self.title,
            "description": self.description,
            "required_skills": self.required_skills,
            "min_experience_years": self.min_experience_years,
            "domain": self.domain,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class Candidate(Base):
    """Candidate model."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str] = mapped_column(String(255), nullable=True)
    phone: Mapped[str] = mapped_column(String(50), nullable=True)
    resume_text: Mapped[str] = mapped_column(Text, nullable=False)
    resume_file_path: Mapped[str] = mapped_column(String(500), nullable=True)
    job_description_id: Mapped[int | None] = mapped_column(ForeignKey("job_descriptions.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    job_description: Mapped["JobDescription"] = relationship(back_populates="candidates")
    analysis: Mapped["CandidateAnalysis"] = relationship(back_populates="candidate", uselist=False, cascade="all, delete-orphan")
    interview_sessions: Mapped[list["InterviewSession"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
    )
    profile: Mapped["CandidateProfile"] = relationship(
        back_populates="candidate",
        uselist=False,
        cascade="all, delete-orphan",
    )
    analysis_runs: Mapped[list["CandidateAnalysisRun"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
    )
    job_links: Mapped[list["CandidateJobLink"]] = relationship(
        back_populates="candidate",
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "email": self.email,
            "phone": self.phone,
            "resume_text": self.resume_text,
            "resume_file_path": self.resume_file_path,
            "job_description_id": self.job_description_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class CandidateProfile(Base):
    """Extended candidate profile details."""

    __tablename__ = "candidate_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False, unique=True)

    current_role: Mapped[str | None] = mapped_column(String(255), nullable=True)
    headline: Mapped[str | None] = mapped_column(String(255), nullable=True)
    total_experience_years: Mapped[float | None] = mapped_column(Float, default=0.0)
    primary_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    secondary_skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    education: Mapped[str | None] = mapped_column(Text, nullable=True)
    certifications: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    linkedin_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    portfolio_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    invalid_resume: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    candidate: Mapped["Candidate"] = relationship(back_populates="profile")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "current_role": self.current_role,
            "headline": self.headline,
            "total_experience_years": self.total_experience_years,
            "primary_skills": self.primary_skills or [],
            "secondary_skills": self.secondary_skills or [],
            "education": self.education,
            "certifications": self.certifications or [],
            "summary": self.summary,
            "location": self.location,
            "linkedin_url": self.linkedin_url,
            "portfolio_url": self.portfolio_url,
            "invalid_resume": self.invalid_resume,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class CandidateAnalysis(Base):
    """Candidate analysis results model."""

    __tablename__ = "candidate_analyses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False, unique=True)

    # Extracted information
    skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    experience_years: Mapped[float] = mapped_column(Float, default=0.0)
    tech_stack: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    domain_knowledge: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    seniority: Mapped[str] = mapped_column(String(50), nullable=True)
    strengths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    weaknesses: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Scoring
    skill_match_score: Mapped[float] = mapped_column(Float, default=0.0)
    experience_score: Mapped[float] = mapped_column(Float, default=0.0)
    domain_score: Mapped[float] = mapped_column(Float, default=0.0)
    project_complexity_score: Mapped[float] = mapped_column(Float, default=0.0)
    soft_skills_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Decision
    decision: Mapped[str] = mapped_column(String(50), nullable=True)
    recommendation: Mapped[str] = mapped_column(Text, nullable=True)

    # Risk analysis
    risks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=True)

    # Interview strategy
    technical_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    system_design_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    behavioral_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    custom_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    interview_focus_areas: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Metadata
    analysis_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    model_used: Mapped[str] = mapped_column(String(100), nullable=True)

    # Relationships
    candidate: Mapped["Candidate"] = relationship(back_populates="analysis")

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "skills": self.skills or [],
            "experience_years": self.experience_years,
            "tech_stack": self.tech_stack or [],
            "domain_knowledge": self.domain_knowledge or [],
            "seniority": self.seniority,
            "strengths": self.strengths or [],
            "weaknesses": self.weaknesses or [],
            "skill_match_score": self.skill_match_score,
            "experience_score": self.experience_score,
            "domain_score": self.domain_score,
            "project_complexity_score": self.project_complexity_score,
            "soft_skills_score": self.soft_skills_score,
            "final_score": self.final_score,
            "decision": self.decision,
            "recommendation": self.recommendation,
            "risks": self.risks or [],
            "risk_level": self.risk_level,
            "technical_questions": self.technical_questions or [],
            "system_design_questions": self.system_design_questions or [],
            "behavioral_questions": self.behavioral_questions or [],
            "custom_questions": self.custom_questions or [],
            "interview_focus_areas": self.interview_focus_areas or [],
            "analysis_timestamp": self.analysis_timestamp.isoformat() if self.analysis_timestamp else None,
            "model_used": self.model_used,
        }


class CandidateAnalysisRun(Base):
    """Immutable analysis history for candidates per job description."""

    __tablename__ = "candidate_analysis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    job_description_id: Mapped[int] = mapped_column(ForeignKey("job_descriptions.id"), nullable=False)

    # Extracted information
    skills: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    experience_years: Mapped[float] = mapped_column(Float, default=0.0)
    tech_stack: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    domain_knowledge: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    seniority: Mapped[str] = mapped_column(String(50), nullable=True)
    strengths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    weaknesses: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Scoring
    skill_match_score: Mapped[float] = mapped_column(Float, default=0.0)
    experience_score: Mapped[float] = mapped_column(Float, default=0.0)
    domain_score: Mapped[float] = mapped_column(Float, default=0.0)
    project_complexity_score: Mapped[float] = mapped_column(Float, default=0.0)
    soft_skills_score: Mapped[float] = mapped_column(Float, default=0.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)

    # Decision
    decision: Mapped[str] = mapped_column(String(50), nullable=True)
    recommendation: Mapped[str] = mapped_column(Text, nullable=True)

    # Risk analysis
    risks: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    risk_level: Mapped[str] = mapped_column(String(50), nullable=True)

    # Interview strategy
    technical_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    system_design_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    behavioral_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    custom_questions: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    interview_focus_areas: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    # Metadata
    analysis_timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    model_used: Mapped[str] = mapped_column(String(100), nullable=True)

    candidate: Mapped["Candidate"] = relationship(back_populates="analysis_runs")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "job_description_id": self.job_description_id,
            "skills": self.skills or [],
            "experience_years": self.experience_years,
            "tech_stack": self.tech_stack or [],
            "domain_knowledge": self.domain_knowledge or [],
            "seniority": self.seniority,
            "strengths": self.strengths or [],
            "weaknesses": self.weaknesses or [],
            "skill_match_score": self.skill_match_score,
            "experience_score": self.experience_score,
            "domain_score": self.domain_score,
            "project_complexity_score": self.project_complexity_score,
            "soft_skills_score": self.soft_skills_score,
            "final_score": self.final_score,
            "decision": self.decision,
            "recommendation": self.recommendation,
            "risks": self.risks or [],
            "risk_level": self.risk_level,
            "technical_questions": self.technical_questions or [],
            "system_design_questions": self.system_design_questions or [],
            "behavioral_questions": self.behavioral_questions or [],
            "custom_questions": self.custom_questions or [],
            "interview_focus_areas": self.interview_focus_areas or [],
            "analysis_timestamp": self.analysis_timestamp.isoformat() if self.analysis_timestamp else None,
            "model_used": self.model_used,
        }


class CandidateJobLink(Base):
    """Candidate to job description links."""

    __tablename__ = "candidate_job_links"
    __table_args__ = (
        UniqueConstraint("candidate_id", "job_description_id", name="uq_candidate_job_link"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    job_description_id: Mapped[int] = mapped_column(ForeignKey("job_descriptions.id"), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    linked_by: Mapped[str] = mapped_column(String(50), default="ai")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    candidate: Mapped["Candidate"] = relationship(back_populates="job_links")
    job_description: Mapped["JobDescription"] = relationship(back_populates="candidate_links")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "job_description_id": self.job_description_id,
            "confidence": self.confidence,
            "linked_by": self.linked_by,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class HiringAction(Base):
    """Hiring action log model."""

    __tablename__ = "hiring_actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    action_type: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=True)
    performed_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    performed_by: Mapped[str] = mapped_column(String(255), default="system")

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "action_type": self.action_type,
            "description": self.description,
            "performed_at": self.performed_at.isoformat() if self.performed_at else None,
            "performed_by": self.performed_by,
        }


class InterviewSession(Base):
    """Interview session model for audio screenings."""

    __tablename__ = "interview_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    job_description_id: Mapped[int] = mapped_column(ForeignKey("job_descriptions.id"), nullable=False)

    status: Mapped[str] = mapped_column(String(50), default="scheduled")
    interviewer_type: Mapped[str] = mapped_column(String(50), default="ai_audio")

    consent_given: Mapped[bool] = mapped_column(Boolean, default=False)
    notice_period_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    expected_ctc: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_ctc: Mapped[str | None] = mapped_column(String(100), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    join_date_preference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    willing_to_join: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    overall_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    recommendation: Mapped[str | None] = mapped_column(Text, nullable=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    candidate: Mapped["Candidate"] = relationship(back_populates="interview_sessions")
    questions: Mapped[list["InterviewQuestion"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )
    feedback: Mapped["InterviewFeedback"] = relationship(
        back_populates="session",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "candidate_id": self.candidate_id,
            "job_description_id": self.job_description_id,
            "status": self.status,
            "interviewer_type": self.interviewer_type,
            "consent_given": self.consent_given,
            "notice_period_days": self.notice_period_days,
            "expected_ctc": self.expected_ctc,
            "current_ctc": self.current_ctc,
            "location": self.location,
            "join_date_preference": self.join_date_preference,
            "willing_to_join": self.willing_to_join,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "overall_score": self.overall_score,
            "recommendation": self.recommendation,
            "summary": self.summary,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class InterviewQuestion(Base):
    """Interview question model."""

    __tablename__ = "interview_questions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id"), nullable=False)
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    order_index: Mapped[int] = mapped_column(Integer, default=0)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)

    session: Mapped["InterviewSession"] = relationship(back_populates="questions")
    response: Mapped["InterviewResponse"] = relationship(
        back_populates="question",
        uselist=False,
        cascade="all, delete-orphan",
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "category": self.category,
            "order_index": self.order_index,
            "question_text": self.question_text,
        }


class InterviewResponse(Base):
    """Interview response model."""

    __tablename__ = "interview_responses"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("interview_questions.id"), nullable=False, unique=True)
    transcript_text: Mapped[str] = mapped_column(Text, nullable=False)
    score_1_to_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    question: Mapped["InterviewQuestion"] = relationship(back_populates="response")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "question_id": self.question_id,
            "transcript_text": self.transcript_text,
            "score_1_to_10": self.score_1_to_10,
            "notes": self.notes,
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
        }


class InterviewFeedback(Base):
    """Interview feedback model."""

    __tablename__ = "interview_feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("interview_sessions.id"), nullable=False, unique=True)
    strengths: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    concerns: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    hire_signal: Mapped[str | None] = mapped_column(String(50), nullable=True)
    next_steps: Mapped[str | None] = mapped_column(Text, nullable=True)
    overall_score_1_to_10: Mapped[float | None] = mapped_column(Float, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    session: Mapped["InterviewSession"] = relationship(back_populates="feedback")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "session_id": self.session_id,
            "strengths": self.strengths or [],
            "concerns": self.concerns or [],
            "hire_signal": self.hire_signal,
            "next_steps": self.next_steps,
            "overall_score_1_to_10": self.overall_score_1_to_10,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class OutlookCandidate(Base):
    """Outlook-ingested candidate model."""

    __tablename__ = "outlook_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    source_message_id: Mapped[str] = mapped_column(String(255), nullable=False)
    source_attachment_id: Mapped[str] = mapped_column(String(255), nullable=False)
    sender_email: Mapped[str] = mapped_column(String(255), nullable=True)
    email_subject: Mapped[str] = mapped_column(String(500), nullable=True)
    received_at: Mapped[str] = mapped_column(String(50), nullable=True)

    candidate_name: Mapped[str] = mapped_column(String(255), nullable=True)
    candidate_email: Mapped[str] = mapped_column(String(255), nullable=True)
    tech_stack: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    job_category: Mapped[str] = mapped_column(String(255), nullable=True)
    seniority: Mapped[str] = mapped_column(String(50), nullable=True)

    resume_text: Mapped[str] = mapped_column(Text, nullable=False)
    resume_file_path: Mapped[str] = mapped_column(String(500), nullable=True)

    linked_candidate_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "source_message_id": self.source_message_id,
            "source_attachment_id": self.source_attachment_id,
            "sender_email": self.sender_email,
            "email_subject": self.email_subject,
            "received_at": self.received_at,
            "candidate_name": self.candidate_name,
            "candidate_email": self.candidate_email,
            "tech_stack": self.tech_stack,
            "job_category": self.job_category,
            "seniority": self.seniority,
            "resume_file_path": self.resume_file_path,
            "linked_candidate_id": self.linked_candidate_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }
