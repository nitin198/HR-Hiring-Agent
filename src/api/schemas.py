"""API request and response schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# Job Description Schemas
class JobDescriptionCreate(BaseModel):
    """Schema for creating a job description."""

    title: str = Field(..., description="Job title")
    description: str = Field(..., description="Full job description")
    required_skills: list[str] = Field(default_factory=list, description="List of required skills")
    min_experience_years: int = Field(default=0, description="Minimum years of experience")
    domain: str | None = Field(None, description="Primary domain")


class JobDescriptionResponse(BaseModel):
    """Schema for job description response."""

    id: int
    title: str
    description: str
    required_skills: list[str]
    min_experience_years: int
    domain: str | None
    created_at: str | None = None
    updated_at: str | None = None


class JobDescriptionUpdate(BaseModel):
    """Schema for updating a job description."""

    title: str | None = Field(None, description="Job title")
    description: str | None = Field(None, description="Full job description")
    required_skills: list[str] | None = Field(None, description="List of required skills")
    min_experience_years: int | None = Field(None, description="Minimum years of experience")
    domain: str | None = Field(None, description="Primary domain")


# Candidate Schemas
class CandidateCreate(BaseModel):
    """Schema for creating a candidate."""

    name: str = Field(..., description="Candidate name")
    email: str | None = Field(None, description="Candidate email")
    phone: str | None = Field(None, description="Candidate phone")
    resume_text: str = Field(..., description="Resume text content")
    job_description_id: int | None = Field(None, description="ID of the job description")


class CandidateCreateFromFile(BaseModel):
    """Schema for creating a candidate from file."""

    name: str = Field(..., description="Candidate name")
    email: str | None = Field(None, description="Candidate email")
    phone: str | None = Field(None, description="Candidate phone")
    resume_file_path: str = Field(..., description="Path to resume file")
    job_description_id: int | None = Field(None, description="ID of the job description")


class CandidateResponse(BaseModel):
    """Schema for candidate response."""

    id: int
    name: str
    email: str | None
    phone: str | None
    resume_text: str
    resume_file_path: str | None
    job_description_id: int | None
    created_at: str | None

    model_config = {"from_attributes": True}


class CandidateProfileResponse(BaseModel):
    """Schema for candidate profile response."""

    id: int
    candidate_id: int
    current_role: str | None
    headline: str | None
    total_experience_years: float | None
    primary_skills: list[str]
    secondary_skills: list[str]
    education: str | None
    certifications: list[str]
    summary: str | None
    location: str | None
    linkedin_url: str | None
    portfolio_url: str | None
    invalid_resume: bool
    created_at: str | None
    updated_at: str | None

    model_config = {"from_attributes": True}


class CandidateAnalysisRunResponse(BaseModel):
    """Schema for analysis history response."""

    id: int
    candidate_id: int
    job_description_id: int
    skills: list[str]
    experience_years: float
    tech_stack: list[str]
    domain_knowledge: list[str]
    seniority: str | None
    strengths: list[str]
    weaknesses: list[str]
    skill_match_score: float
    experience_score: float
    domain_score: float
    project_complexity_score: float
    soft_skills_score: float
    final_score: float
    decision: str | None
    recommendation: str | None
    risks: list[str]
    risk_level: str | None
    technical_questions: list[str]
    system_design_questions: list[str]
    behavioral_questions: list[str]
    custom_questions: list[str]
    interview_focus_areas: list[str]
    analysis_timestamp: str | None
    model_used: str | None
    job_description_title: str | None = None

    model_config = {"from_attributes": True}


class OutlookCandidateResponse(BaseModel):
    """Schema for Outlook candidate response."""

    id: int
    candidate_name: str | None
    candidate_email: str | None
    tech_stack: list[str]
    job_category: str | None
    seniority: str | None
    resume_file_path: str | None
    linked_candidate_id: int | None
    created_at: str | None

    model_config = {"from_attributes": True}


class OutlookIngestResponse(BaseModel):
    """Schema for Outlook ingestion response."""

    status: str
    processed_messages: int
    processed_attachments: int
    created_candidates: int
    skipped_candidates: int
    errors: list[str]
    device_code_message: str | None = None


class OutlookAttachRequest(BaseModel):
    """Schema for attaching Outlook candidates to a job description."""

    job_description_id: int
    outlook_candidate_ids: list[int]


# Analysis Schemas
class CandidateAnalysisResponse(BaseModel):
    """Schema for candidate analysis response."""

    id: int
    candidate_id: int
    skills: list[str]
    experience_years: float
    tech_stack: list[str]
    domain_knowledge: list[str]
    seniority: str | None
    strengths: list[str]
    weaknesses: list[str]
    skill_match_score: float
    experience_score: float
    domain_score: float
    project_complexity_score: float
    soft_skills_score: float
    final_score: float
    decision: str | None
    recommendation: str | None
    risks: list[str]
    risk_level: str | None
    technical_questions: list[str]
    system_design_questions: list[str]
    behavioral_questions: list[str]
    custom_questions: list[str]
    interview_focus_areas: list[str]
    analysis_timestamp: str | None
    model_used: str | None

    model_config = {
        "from_attributes": True,
        "protected_namespaces": (),
    }


class CandidateWithAnalysisResponse(BaseModel):
    """Schema for candidate with analysis response."""

    candidate: CandidateResponse
    analysis: CandidateAnalysisResponse | None = None


class CandidateDetailResponse(BaseModel):
    """Schema for candidate detail response."""

    candidate: CandidateResponse
    profile: CandidateProfileResponse | None = None
    analysis: CandidateAnalysisResponse | None = None
    analysis_history: list[CandidateAnalysisRunResponse] = Field(default_factory=list)


# Ranking Schemas
class RankedCandidateResponse(BaseModel):
    """Schema for ranked candidate response."""

    rank: int
    candidate: CandidateResponse
    analysis: CandidateAnalysisResponse


# Report Schemas
class HiringReportSummary(BaseModel):
    """Schema for hiring report summary."""

    total_candidates: int
    strong_hires: int
    borderline: int
    rejects: int
    average_score: float


class HiringReportResponse(BaseModel):
    """Schema for hiring report response."""

    job_description: JobDescriptionResponse
    summary: HiringReportSummary
    ranked_candidates: list[dict[str, Any]]
    strong_hires: list[dict[str, Any]]
    borderline: list[dict[str, Any]]
    rejects: list[dict[str, Any]]
    generated_at: str


# Interview Strategy Schemas
class InterviewStrategyResponse(BaseModel):
    """Schema for interview strategy response."""

    candidate: CandidateResponse
    analysis: CandidateAnalysisResponse
    interview_strategy: dict[str, Any]


# Action Schemas
class HiringActionResponse(BaseModel):
    """Schema for hiring action response."""

    id: int
    candidate_id: int
    action_type: str
    description: str | None
    performed_at: str | None
    performed_by: str

    model_config = {"from_attributes": True}


# Health Schemas
class HealthResponse(BaseModel):
    """Schema for health check response."""

    status: str
    timestamp: str
    ollama_connected: bool
    ollama_model: str | None


# Error Schemas
class ErrorResponse(BaseModel):
    """Schema for error response."""

    error: str
    detail: str | None = None
    timestamp: str = Field(default_factory=lambda: datetime.utcnow().isoformat())


# Interview Schemas
class InterviewStartRequest(BaseModel):
    """Schema for starting an interview session."""

    candidate_id: int
    job_description_id: int | None = None
    consent_given: bool = False
    notice_period_days: int | None = None
    expected_ctc: str | None = None
    current_ctc: str | None = None
    location: str | None = None
    join_date_preference: str | None = None
    willing_to_join: bool | None = None


class InterviewSessionResponse(BaseModel):
    """Schema for interview session response."""

    id: int
    candidate_id: int
    job_description_id: int
    status: str
    interviewer_type: str
    consent_given: bool
    notice_period_days: int | None
    expected_ctc: str | None
    current_ctc: str | None
    location: str | None
    join_date_preference: str | None
    willing_to_join: bool | None
    started_at: str | None
    completed_at: str | None
    overall_score: float | None
    recommendation: str | None
    summary: str | None
    created_at: str | None
    updated_at: str | None

    model_config = {"from_attributes": True}


class InterviewQuestionResponse(BaseModel):
    """Schema for interview question response."""

    id: int
    session_id: int
    category: str
    order_index: int
    question_text: str

    model_config = {"from_attributes": True}


class InterviewResponseResponse(BaseModel):
    """Schema for interview response response."""

    id: int
    question_id: int
    transcript_text: str
    score_1_to_10: float | None
    notes: str | None
    answered_at: str | None

    model_config = {"from_attributes": True}


class InterviewFeedbackResponse(BaseModel):
    """Schema for interview feedback response."""

    id: int
    session_id: int
    strengths: list[str]
    concerns: list[str]
    hire_signal: str | None
    next_steps: str | None
    overall_score_1_to_10: float | None
    created_at: str | None

    model_config = {"from_attributes": True}


class InterviewStartResponse(BaseModel):
    """Schema for interview start response."""

    session: InterviewSessionResponse
    first_question: InterviewQuestionResponse | None = None


class InterviewNextResponse(BaseModel):
    """Schema for interview next question response."""

    question: InterviewQuestionResponse | None = None
    remaining: int
    status: str


class InterviewDetailResponse(BaseModel):
    """Schema for interview detail response."""

    session: InterviewSessionResponse
    questions: list[InterviewQuestionResponse]
    responses: list[InterviewResponseResponse]
    feedback: InterviewFeedbackResponse | None = None


class InterviewSummaryItem(BaseModel):
    """Schema for candidate interview summary list."""

    candidate: CandidateResponse
    analysis: CandidateAnalysisResponse | None = None
    session: InterviewSessionResponse | None = None
    feedback: InterviewFeedbackResponse | None = None
