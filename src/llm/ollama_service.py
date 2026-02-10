"""Ollama LLM service for AI-powered analysis."""

import json
from typing import Any

import httpx

from langchain_core.messages import HumanMessage, SystemMessage

from src.config.settings import get_settings


class OllamaService:
    """Service for interacting with Ollama LLM."""

    def __init__(self, model: str | None = None, base_url: str | None = None):
        """
        Initialize Ollama service.

        Args:
            model: Model name to use (defaults to settings)
            base_url: Ollama base URL (defaults to settings)
        """
        # Clear cache and get fresh settings to ensure latest .env values are used
        get_settings.cache_clear()
        settings = get_settings()
        self.model = model or settings.ollama_model
        self.base_url = base_url or settings.ollama_base_url
        self.timeout = settings.ollama_timeout

        self.temperature = 0.3

    def _format_messages(self, messages: list[dict[str, str]]) -> list[dict[str, str]]:
        """Normalize messages for Ollama API."""
        formatted = []
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            formatted.append({"role": role, "content": content})
        return formatted


    async def invoke(self, messages: list[dict[str, str]]) -> str:
        """
        Invoke the LLM with messages.

        Args:
            messages: List of message dicts with 'role' and 'content'

        Returns:
            LLM response text

        Raises:
            ConnectionError: If Ollama is not reachable
            TimeoutError: If request times out
        """
        payload = {
            "model": self.model,
            "messages": self._format_messages(messages),
            "stream": False,
            "options": {"temperature": self.temperature},
        }

        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
        except Exception as e:
            if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                raise TimeoutError(f"Ollama request timed out after {self.timeout} seconds") from e
            if "connection" in str(e).lower() or "refused" in str(e).lower():
                raise ConnectionError(f"Cannot connect to Ollama at {self.base_url}") from e
            raise

        message = (data.get("message") or {}).get("content")
        if not message:
            raise ValueError(f"Ollama response missing message content: {data}")
        return message

    async def invoke_with_json(self, messages: list[dict[str, str]]) -> dict[str, Any]:
        """
        Invoke the LLM and parse response as JSON.

        Args:
            messages: List of message dicts with 'role' and 'content'

        Returns:
            Parsed JSON response

        Raises:
            ValueError: If response cannot be parsed as JSON
        """
        response_text = await self.invoke(messages)

        # Try to extract JSON from response
        # Handle cases where LLM wraps JSON in markdown code blocks
        json_text = response_text.strip()

        # Remove markdown code blocks if present
        if json_text.startswith("```json"):
            json_text = json_text[7:]
        elif json_text.startswith("```"):
            json_text = json_text[3:]

        if json_text.endswith("```"):
            json_text = json_text[:-3]

        json_text = json_text.strip()

        try:
            return json.loads(json_text)
        except json.JSONDecodeError as e:
            # Try to find JSON in the text
            import re

            json_match = re.search(r"\{[\s\S]*\}", json_text)
            if json_match:
                try:
                    return json.loads(json_match.group())
                except json.JSONDecodeError:
                    pass

            raise ValueError(f"Failed to parse LLM response as JSON: {e}\nResponse: {response_text}")

    async def analyze_resume(self, resume_text: str, jd_text: str) -> dict[str, Any]:
        """
        Analyze resume against job description.

        Args:
            resume_text: Resume text content
            jd_text: Job description text

        Returns:
            Analysis results with skills, scores, risks, etc.
        """
        system_prompt = """You are an AI hiring agent for an IT company. Your task is to analyze resumes against job descriptions and provide structured, objective assessments.

You must:
1. Extract skills, experience, domain knowledge, strengths, and weaknesses from the resume
2. Compare with the job description
3. Score the candidate on multiple dimensions (0-100)
4. Identify potential risks
5. Suggest interview questions
6. Provide a hiring recommendation

Be objective and fair. Focus on evidence from the resume rather than assumptions."""

        user_prompt = f"""Analyze the following resume against the job description.

RESUME:
{resume_text}

JOB DESCRIPTION:
{jd_text}

Provide your analysis in the following JSON format:
{{
    "skills": ["skill1", "skill2", ...],
    "experience_years": <number>,
    "tech_stack": ["tech1", "tech2", ...],
    "domain_knowledge": ["domain1", "domain2", ...],
    "seniority": "<junior|mid-level|senior|lead|principal>",
    "strengths": ["strength1", "strength2", ...],
    "weaknesses": ["weakness1", "weakness2", ...],
    "skill_match_score": <0-100>,
    "experience_score": <0-100>,
    "domain_score": <0-100>,
    "project_complexity_score": <0-100>,
    "soft_skills_score": <0-100>,
    "risks": ["risk1", "risk2", ...],
    "risk_level": "<low|medium|high>",
    "technical_questions": ["question1", "question2", ...],
    "system_design_questions": ["question1", "question2", ...],
    "behavioral_questions": ["question1", "question2", ...],
    "custom_questions": ["question1", "question2", ...],
    "interview_focus_areas": ["area1", "area2", ...],
    "recommendation": "<detailed recommendation text>"
}}

Ensure all scores are between 0 and 100. Provide at least 5 questions per question category. Be specific and evidence-based in your analysis."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return await self.invoke_with_json(messages)

    async def extract_jd_info(self, jd_text: str) -> dict[str, Any]:
        """
        Extract structured information from job description.

        Args:
            jd_text: Job description text

        Returns:
            Extracted JD information
        """
        system_prompt = """You are an AI assistant that extracts structured information from job descriptions."""

        user_prompt = f"""Extract the following information from this job description:

JOB DESCRIPTION:
{jd_text}

Provide your analysis in the following JSON format:
{{
    "title": "<job title>",
    "required_skills": ["skill1", "skill2", ...],
    "min_experience_years": <number>,
    "domain": "<primary domain if applicable>",
    "preferred_skills": ["skill1", "skill2", ...],
    "responsibilities": ["responsibility1", "responsibility2", ...],
    "qualifications": ["qualification1", "qualification2", ...]
}}

If any field is not clearly specified, use null or an empty list."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return await self.invoke_with_json(messages)

    async def extract_candidate_profile(self, resume_text: str) -> dict[str, Any]:
        """
        Extract structured candidate profile information from resume text.

        Args:
            resume_text: Resume text content

        Returns:
            Extracted profile information
        """
        system_prompt = """You are an AI assistant that extracts structured information from resumes."""

        user_prompt = f"""Extract the following information from this resume:

RESUME:
{resume_text}

Provide your response in the following JSON format:
{{
    "current_role": "<current job title>",
    "headline": "<one-line role summary>",
    "total_experience_years": <number>,
    "primary_skills": ["skill1", "skill2", ...],
    "secondary_skills": ["skill1", "skill2", ...],
    "education": "<highest education and institution>",
    "certifications": ["cert1", "cert2", ...],
    "summary": "<short professional summary>",
    "location": "<current location if available>",
    "linkedin_url": "<url or null>",
    "portfolio_url": "<url or null>"
}}

If any field is not clearly specified, use null or an empty list."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return await self.invoke_with_json(messages)

    async def generate_interview_questions(
        self,
        resume_text: str,
        jd_text: str,
        focus_areas: list[str] | None = None,
    ) -> dict[str, list[str]]:
        """
        Generate interview questions based on resume and JD.

        Args:
            resume_text: Resume text content
            jd_text: Job description text
            focus_areas: Optional list of areas to focus on

        Returns:
            Dictionary with different question categories
        """
        focus_text = "\n".join(f"- {area}" for area in (focus_areas or []))

        system_prompt = """You are an AI hiring assistant that generates interview questions."""

        user_prompt = f"""Generate interview questions for a candidate based on their resume and the job description.

RESUME:
{resume_text}

JOB DESCRIPTION:
{jd_text}

FOCUS AREAS:
{focus_text if focus_text else "No specific focus areas provided."}

Provide your response in the following JSON format:
{{
    "technical_questions": ["question1", "question2", ...],
    "system_design_questions": ["question1", "question2", ...],
    "behavioral_questions": ["question1", "question2", ...],
    "custom_questions": ["question1", "question2", ...]
}}

Generate at least 5 questions per category. Make questions specific to the candidate's background and the role requirements."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return await self.invoke_with_json(messages)

    async def detect_risks(self, resume_text: str, jd_text: str) -> dict[str, Any]:
        """
        Detect potential risks in a candidate's profile.

        Args:
            resume_text: Resume text content
            jd_text: Job description text

        Returns:
            Risk analysis results
        """
        system_prompt = """You are an AI hiring assistant that identifies potential risks in candidate profiles.

Look for:
- Frequent job changes (stability risk)
- Gaps in employment
- Limited project complexity
- Shallow technical depth (many tools but no deep expertise)
- Lack of relevant domain experience
- Limited leadership or ownership
- Red flags in career progression

Be objective and evidence-based. Don't flag normal career progression as risks."""

        user_prompt = f"""Analyze the following resume for potential hiring risks.

RESUME:
{resume_text}

JOB DESCRIPTION:
{jd_text}

Provide your analysis in the following JSON format:
{{
    "risks": ["risk1", "risk2", ...],
    "risk_level": "<low|medium|high>",
    "risk_details": {{
        "risk1": "<explanation>",
        "risk2": "<explanation>"
    }},
    "mitigation_suggestions": ["suggestion1", "suggestion2", ...]
}}

Only include genuine risks supported by evidence in the resume."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        return await self.invoke_with_json(messages)
