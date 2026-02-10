"""Interview orchestration and scoring utilities."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.llm.ollama_service import OllamaService


@dataclass
class InterviewQuestionSpec:
    """Structured question spec."""

    category: str
    question_text: str


class InterviewService:
    """Service for generating and scoring interview questions."""

    def __init__(self) -> None:
        self.llm = OllamaService()

    async def generate_questions(
        self,
        resume_text: str,
        jd_text: str,
        focus_areas: list[str] | None = None,
    ) -> list[InterviewQuestionSpec]:
        """Generate ordered interview questions."""
        base_questions = [
            InterviewQuestionSpec("basic", "Please introduce yourself and summarize your recent experience."),
            InterviewQuestionSpec("basic", "What are your core strengths that are most relevant to this role?"),
            InterviewQuestionSpec("experience", "Tell me about your most recent project and your specific contributions."),
            InterviewQuestionSpec("experience", "Describe a challenging technical problem you solved and how you approached it."),
            InterviewQuestionSpec("motivation", "Why are you interested in this role and our company?"),
            InterviewQuestionSpec("motivation", "What are you looking for in your next role?"),
            InterviewQuestionSpec("logistics", "What is your notice period or earliest possible joining date?"),
            InterviewQuestionSpec("logistics", "What are your current and expected compensation ranges?"),
            InterviewQuestionSpec("logistics", "Are you willing to join this role if selected?"),
        ]

        llm_questions: list[InterviewQuestionSpec] = []
        try:
            llm_payload = await self.llm.generate_interview_questions(
                resume_text=resume_text,
                jd_text=jd_text,
                focus_areas=focus_areas or [],
            )
            llm_questions.extend(
                [InterviewQuestionSpec("technical", q) for q in llm_payload.get("technical_questions", [])]
            )
            llm_questions.extend(
                [InterviewQuestionSpec("system_design", q) for q in llm_payload.get("system_design_questions", [])]
            )
            llm_questions.extend(
                [InterviewQuestionSpec("behavioral", q) for q in llm_payload.get("behavioral_questions", [])]
            )
            llm_questions.extend(
                [InterviewQuestionSpec("custom", q) for q in llm_payload.get("custom_questions", [])]
            )
        except Exception:
            # Fall back to a minimal set if LLM is unavailable.
            llm_questions = [
                InterviewQuestionSpec("technical", "Describe a system you built that is similar to this role."),
                InterviewQuestionSpec("behavioral", "Tell me about a time you handled a conflict in a team."),
            ]

        questions = base_questions + llm_questions
        if len(questions) < 10:
            filler = [
                InterviewQuestionSpec("technical", "Walk me through a project where you designed or optimized a system."),
                InterviewQuestionSpec("behavioral", "Share an example of a time you received critical feedback."),
                InterviewQuestionSpec("technical", "What would you improve in your current tech stack and why?"),
            ]
            questions.extend(filler)
        return questions[:10]

    async def score_response(
        self,
        question_text: str,
        transcript_text: str,
        resume_text: str,
        jd_text: str,
    ) -> dict[str, Any]:
        """Score a response on a 1-10 scale and return notes."""
        system_prompt = (
            "You are an interview evaluator. Score the candidate response from 1 to 10 "
            "based on relevance, clarity, depth, and alignment with the job description."
        )
        user_prompt = f"""Question: {question_text}

Candidate response (transcript):
{transcript_text}

Job description:
{jd_text}

Resume:
{resume_text}

Return JSON:
{{
  "score_1_to_10": <number between 1 and 10>,
  "notes": "<short feedback notes>"
}}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await self.llm.invoke_with_json(messages)
        except Exception:
            result = {"score_1_to_10": 5, "notes": "Unable to score automatically; manual review recommended."}

        score = result.get("score_1_to_10")
        if not isinstance(score, (int, float)):
            score = 5
        score = max(1, min(10, float(score)))
        return {
            "score_1_to_10": score,
            "notes": result.get("notes") or "",
        }

    async def summarize_interview(
        self,
        jd_text: str,
        transcript_items: list[dict[str, str]],
        average_score: float,
    ) -> dict[str, Any]:
        """Generate interview summary and recommendations."""
        system_prompt = (
            "You are an interview evaluator. Summarize the interview and recommend next steps."
        )
        transcript_block = "\n\n".join(
            [f"Q: {item['question']}\nA: {item['answer']}" for item in transcript_items]
        )
        user_prompt = f"""Job description:
{jd_text}

Interview transcript:
{transcript_block}

Average score: {average_score:.2f}

Return JSON:
{{
  "strengths": ["strength1", "strength2"],
  "concerns": ["concern1", "concern2"],
  "hire_signal": "<strong_hire|borderline|reject>",
  "next_steps": "<short next steps>",
  "summary": "<short summary>"
}}"""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            result = await self.llm.invoke_with_json(messages)
        except Exception:
            result = {
                "strengths": [],
                "concerns": ["Unable to generate automatic summary; manual review recommended."],
                "hire_signal": "borderline",
                "next_steps": "Manual review required.",
                "summary": "Automatic summary unavailable.",
            }

        return result
