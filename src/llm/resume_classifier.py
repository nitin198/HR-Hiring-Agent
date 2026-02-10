"""LLM-based resume classification."""

from __future__ import annotations

import logging
from typing import Any

from src.llm.ollama_service import OllamaService

logger = logging.getLogger(__name__)


class ResumeClassifier:
    """Classify resumes into tech stack and job category."""

    def __init__(self) -> None:
        self._llm = OllamaService()

    async def classify_resume(self, resume_text: str) -> dict[str, Any]:
        """Classify resume text into structured metadata."""
        system_prompt = (
            "You are an AI assistant that extracts structured candidate metadata from resumes."
        )
        user_prompt = f"""Extract the following information from this resume.

RESUME:
{resume_text}

Provide your response in this JSON format:
{{
  "candidate_name": "<full name or null>",
  "candidate_email": "<email or null>",
  "tech_stack": ["Java", "Python", "React", "..."],
  "job_category": "<Backend Engineer | Frontend Engineer | Full Stack | Data Engineer | ML Engineer | DevOps | QA | Product | Other>",
  "seniority": "<junior|mid|senior|lead|principal|unknown>"
}}

Use null for unknown fields. Keep tech_stack concise (5-10 items)."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            return await self._llm.invoke_with_json(messages)
        except Exception as exc:
            logger.exception("Resume classification failed: %s", exc)
            return {
                "candidate_name": None,
                "candidate_email": None,
                "tech_stack": [],
                "job_category": "Other",
                "seniority": "unknown",
            }
