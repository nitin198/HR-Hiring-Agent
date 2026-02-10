"""Router for audio interview endpoints."""

from __future__ import annotations

from datetime import datetime
import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy import select, func
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from src.api.schemas import (
    InterviewDetailResponse,
    InterviewNextResponse,
    InterviewQuestionResponse,
    InterviewResponseResponse,
    InterviewSessionResponse,
    InterviewStartRequest,
    InterviewStartResponse,
    InterviewSummaryItem,
)
from src.database.connection import get_db
from src.database.models import (
    Candidate,
    CandidateAnalysis,
    CandidateJobLink,
    InterviewFeedback,
    InterviewQuestion,
    InterviewResponse,
    InterviewSession,
    JobDescription,
)
from src.services.interview_service import InterviewService
from src.services.stt_service import WhisperSTT
from src.services.tts_service import PiperTTS

router = APIRouter(prefix="/interviews", tags=["Interviews"])

interview_service = InterviewService()
stt_service = WhisperSTT()
tts_service = PiperTTS()


@router.post("/start", response_model=InterviewStartResponse)
async def start_interview(
    payload: InterviewStartRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Start an interview session and generate questions."""
    result = await db.execute(select(Candidate).where(Candidate.id == payload.candidate_id))
    candidate = result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    jd = None
    if payload.job_description_id is not None:
        jd_result = await db.execute(
            select(JobDescription).where(JobDescription.id == payload.job_description_id)
        )
        jd = jd_result.scalar_one_or_none()
    elif candidate.job_description_id is not None:
        jd_result = await db.execute(
            select(JobDescription).where(JobDescription.id == candidate.job_description_id)
        )
        jd = jd_result.scalar_one_or_none()
    else:
        link_result = await db.execute(
            select(CandidateJobLink)
            .where(CandidateJobLink.candidate_id == candidate.id)
            .order_by(CandidateJobLink.confidence.desc(), CandidateJobLink.id.desc())
        )
        link = link_result.scalars().first()
        if link:
            jd_result = await db.execute(
                select(JobDescription).where(JobDescription.id == link.job_description_id)
            )
            jd = jd_result.scalar_one_or_none()

    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")

    analysis_result = await db.execute(
        select(CandidateAnalysis).where(CandidateAnalysis.candidate_id == candidate.id)
    )
    analysis = analysis_result.scalar_one_or_none()

    session = InterviewSession(
        candidate_id=candidate.id,
        job_description_id=jd.id,
        status="in_progress",
        interviewer_type="ai_audio",
        consent_given=payload.consent_given,
        notice_period_days=payload.notice_period_days,
        expected_ctc=payload.expected_ctc,
        current_ctc=payload.current_ctc,
        location=payload.location,
        join_date_preference=payload.join_date_preference,
        willing_to_join=payload.willing_to_join,
        started_at=datetime.utcnow(),
    )
    db.add(session)

    for attempt in range(3):
        try:
            await db.flush()
            break
        except OperationalError as exc:
            if attempt == 2 or "locked" not in str(exc).lower():
                raise
            await asyncio.sleep(0.4 * (attempt + 1))

    focus_areas = analysis.interview_focus_areas if analysis else []
    question_specs = await interview_service.generate_questions(
        resume_text=candidate.resume_text,
        jd_text=jd.description,
        focus_areas=focus_areas,
    )

    questions: list[InterviewQuestion] = []
    for idx, question_spec in enumerate(question_specs):
        question = InterviewQuestion(
            session_id=session.id,
            category=question_spec.category,
            order_index=idx,
            question_text=question_spec.question_text,
        )
        db.add(question)
        questions.append(question)

    await db.commit()
    await db.refresh(session)

    first_question = questions[0] if questions else None

    return {
        "session": session.to_dict(),
        "first_question": first_question.to_dict() if first_question else None,
    }


@router.get("/{session_id}/next", response_model=InterviewNextResponse)
async def get_next_question(
    session_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Return the next unanswered question."""
    result = await db.execute(
        select(InterviewQuestion)
        .where(InterviewQuestion.session_id == session_id)
        .order_by(InterviewQuestion.order_index.asc())
    )
    questions = list(result.scalars().all())
    if not questions:
        raise HTTPException(status_code=404, detail="No questions found for this session")

    response_result = await db.execute(
        select(InterviewResponse).join(InterviewQuestion).where(
            InterviewQuestion.session_id == session_id
        )
    )
    responses = list(response_result.scalars().all())
    answered_ids = {response.question_id for response in responses}

    next_question = next((q for q in questions if q.id not in answered_ids), None)
    remaining = len([q for q in questions if q.id not in answered_ids])

    return {
        "question": next_question.to_dict() if next_question else None,
        "remaining": remaining,
        "status": "completed" if next_question is None else "in_progress",
    }


@router.post("/{session_id}/answer", response_model=InterviewResponseResponse)
async def submit_answer(
    session_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
    question_id: Annotated[int, Form()],
    audio: UploadFile = File(...),
) -> dict:
    """Submit an audio answer for a question."""
    question_result = await db.execute(
        select(InterviewQuestion).where(
            InterviewQuestion.id == question_id,
            InterviewQuestion.session_id == session_id,
        )
    )
    question = question_result.scalar_one_or_none()
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    session_result = await db.execute(
        select(InterviewSession).where(InterviewSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    candidate_result = await db.execute(
        select(Candidate).where(Candidate.id == session.candidate_id)
    )
    candidate = candidate_result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found for session")

    jd_result = await db.execute(
        select(JobDescription).where(JobDescription.id == session.job_description_id)
    )
    jd = jd_result.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")

    audio_bytes = await audio.read()
    transcript = await stt_service.transcribe_wav(audio_bytes)
    if not transcript.strip():
        transcript = "(no speech detected)"

    existing_result = await db.execute(
        select(InterviewResponse).where(InterviewResponse.question_id == question.id)
    )
    response = existing_result.scalar_one_or_none()
    if response:
        response.transcript_text = transcript
        response.score_1_to_10 = None
        response.notes = None
        response.answered_at = datetime.utcnow()
    else:
        response = InterviewResponse(
            question_id=question.id,
            transcript_text=transcript,
            score_1_to_10=None,
            notes=None,
        )
        db.add(response)
    await db.commit()
    await db.refresh(response)

    return response.to_dict()


@router.post("/{session_id}/finalize", response_model=InterviewDetailResponse)
async def finalize_interview(
    session_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Finalize the interview and generate feedback summary."""
    session_result = await db.execute(
        select(InterviewSession).where(InterviewSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    candidate_result = await db.execute(
        select(Candidate).where(Candidate.id == session.candidate_id)
    )
    candidate = candidate_result.scalar_one_or_none()
    if not candidate:
        raise HTTPException(status_code=404, detail="Candidate not found")

    jd_result = await db.execute(
        select(JobDescription).where(JobDescription.id == session.job_description_id)
    )
    jd = jd_result.scalar_one_or_none()
    if not jd:
        raise HTTPException(status_code=404, detail="Job description not found")

    questions_result = await db.execute(
        select(InterviewQuestion)
        .where(InterviewQuestion.session_id == session_id)
        .order_by(InterviewQuestion.order_index.asc())
    )
    questions = list(questions_result.scalars().all())

    responses_result = await db.execute(
        select(InterviewResponse).join(InterviewQuestion).where(
            InterviewQuestion.session_id == session_id
        )
    )
    responses = list(responses_result.scalars().all())

    question_map = {q.id: q for q in questions}
    for response in responses:
        if response.score_1_to_10 is not None:
            continue
        question = question_map.get(response.question_id)
        if not question:
            continue
        if response.transcript_text == "(no speech detected)":
            score_payload = {
                "score_1_to_10": 1,
                "notes": "No speech detected in the audio.",
            }
        else:
            score_payload = await interview_service.score_response(
                question_text=question.question_text,
                transcript_text=response.transcript_text,
                resume_text=candidate.resume_text,
                jd_text=jd.description,
            )
        response.score_1_to_10 = score_payload["score_1_to_10"]
        response.notes = score_payload.get("notes")
        response.answered_at = response.answered_at or datetime.utcnow()

    await db.commit()
    await db.refresh(session)

    score_values = [resp.score_1_to_10 for resp in responses if resp.score_1_to_10 is not None]
    average_score = sum(score_values) / len(score_values) if score_values else 0.0

    transcript_items = []
    response_map = {resp.question_id: resp for resp in responses}
    for question in questions:
        response = response_map.get(question.id)
        if response:
            transcript_items.append(
                {"question": question.question_text, "answer": response.transcript_text}
            )

    summary_payload = await interview_service.summarize_interview(
        jd_text=jd.description,
        transcript_items=transcript_items,
        average_score=average_score,
    )

    session.overall_score = average_score
    session.recommendation = summary_payload.get("hire_signal")
    session.summary = summary_payload.get("summary")
    session.status = "completed"
    session.completed_at = datetime.utcnow()

    feedback_result = await db.execute(
        select(InterviewFeedback).where(InterviewFeedback.session_id == session.id)
    )
    feedback = feedback_result.scalar_one_or_none()
    if feedback:
        feedback.strengths = summary_payload.get("strengths") or []
        feedback.concerns = summary_payload.get("concerns") or []
        feedback.hire_signal = summary_payload.get("hire_signal")
        feedback.next_steps = summary_payload.get("next_steps")
        feedback.overall_score_1_to_10 = average_score
    else:
        feedback = InterviewFeedback(
            session_id=session.id,
            strengths=summary_payload.get("strengths") or [],
            concerns=summary_payload.get("concerns") or [],
            hire_signal=summary_payload.get("hire_signal"),
            next_steps=summary_payload.get("next_steps"),
            overall_score_1_to_10=average_score,
        )
        db.add(feedback)
    await db.commit()
    await db.refresh(session)

    return {
        "session": session.to_dict(),
        "questions": [q.to_dict() for q in questions],
        "responses": [r.to_dict() for r in responses],
        "feedback": feedback.to_dict(),
    }


@router.get("/{session_id}", response_model=InterviewDetailResponse)
async def get_interview(
    session_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> dict:
    """Get interview details."""
    session_result = await db.execute(
        select(InterviewSession).where(InterviewSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    questions_result = await db.execute(
        select(InterviewQuestion)
        .where(InterviewQuestion.session_id == session_id)
        .order_by(InterviewQuestion.order_index.asc())
    )
    questions = list(questions_result.scalars().all())

    responses_result = await db.execute(
        select(InterviewResponse).join(InterviewQuestion).where(
            InterviewQuestion.session_id == session_id
        )
    )
    responses = list(responses_result.scalars().all())

    feedback_result = await db.execute(
        select(InterviewFeedback).where(InterviewFeedback.session_id == session_id)
    )
    feedback = feedback_result.scalar_one_or_none()

    return {
        "session": session.to_dict(),
        "questions": [q.to_dict() for q in questions],
        "responses": [r.to_dict() for r in responses],
        "feedback": feedback.to_dict() if feedback else None,
    }


@router.get("", response_model=list[InterviewSessionResponse])
async def list_interviews(
    db: Annotated[AsyncSession, Depends(get_db)],
    candidate_id: int | None = None,
) -> list[dict]:
    """List interview sessions, optionally filtered by candidate."""
    query = select(InterviewSession).order_by(InterviewSession.created_at.desc())
    if candidate_id is not None:
        query = query.where(InterviewSession.candidate_id == candidate_id)

    result = await db.execute(query)
    sessions = list(result.scalars().all())
    return [session.to_dict() for session in sessions]


@router.get("/summary", response_model=list[InterviewSummaryItem])
async def list_interview_summaries(
    db: Annotated[AsyncSession, Depends(get_db)],
    job_description_id: int | None = None,
) -> list[dict]:
    """List candidates with latest interview summary and analysis."""
    latest_subq = (
        select(
            InterviewSession.candidate_id.label("candidate_id"),
            func.max(InterviewSession.id).label("latest_session_id"),
        )
        .group_by(InterviewSession.candidate_id)
        .subquery()
    )

    query = (
        select(Candidate, CandidateAnalysis, InterviewSession, InterviewFeedback)
        .outerjoin(CandidateAnalysis, Candidate.id == CandidateAnalysis.candidate_id)
        .outerjoin(latest_subq, latest_subq.c.candidate_id == Candidate.id)
        .outerjoin(InterviewSession, InterviewSession.id == latest_subq.c.latest_session_id)
        .outerjoin(InterviewFeedback, InterviewFeedback.session_id == InterviewSession.id)
        .order_by(Candidate.created_at.desc())
    )

    if job_description_id is not None:
        query = query.where(Candidate.job_description_id == job_description_id)

    result = await db.execute(query)
    rows = result.all()
    summaries = []
    for candidate, analysis, session, feedback in rows:
        summaries.append(
            {
                "candidate": candidate.to_dict(),
                "analysis": analysis.to_dict() if analysis else None,
                "session": session.to_dict() if session else None,
                "feedback": feedback.to_dict() if feedback else None,
            }
        )
    return summaries


@router.delete("/{session_id}", status_code=200)
async def delete_interview(
    session_id: int,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    """Delete an interview session and its related data."""
    session_result = await db.execute(
        select(InterviewSession).where(InterviewSession.id == session_id)
    )
    session = session_result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=404, detail="Interview session not found")

    await db.delete(session)
    await db.commit()
    return {"status": "deleted", "session_id": session_id}


@router.post("/tts")
async def generate_tts(
    text: Annotated[str, Form()],
) -> StreamingResponse:
    """Generate TTS audio for the given text."""
    try:
        audio_bytes = await tts_service.synthesize(text)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return StreamingResponse(
        iter([audio_bytes]),
        media_type="audio/wav",
        headers={"Content-Disposition": "inline; filename=tts.wav"},
    )
