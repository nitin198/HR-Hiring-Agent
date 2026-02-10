"""Ollama LLM service for AI-powered analysis."""

import ast
import json
import logging
import re
from typing import Any

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

        try:
            from langchain_ollama import ChatOllama
        except Exception as exc:
            raise RuntimeError("langchain-ollama is required to use OllamaService") from exc

        self._llm = ChatOllama(
            model=self.model,
            base_url=self.base_url,
            streaming=False,
            temperature=self.temperature,  # Lower temperature for more consistent analysis
            timeout=self.timeout,
        )

    async def _http_invoke(self, messages: list[dict[str, str]]) -> str:
        import httpx

        payload = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": self.temperature},
        }
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(f"{self.base_url}/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        content = None
        if isinstance(data, dict):
            content = (data.get("message") or {}).get("content")
            if content is None:
                content = data.get("response")
        if not content:
            raise ValueError("Ollama response missing content")
        return content


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
        langchain_messages = []

        for msg in messages:
            if msg["role"] == "system":
                langchain_messages.append(SystemMessage(content=msg["content"]))
            elif msg["role"] == "user":
                langchain_messages.append(HumanMessage(content=msg["content"]))

        try:
            response = await self._llm.ainvoke(langchain_messages)
            return response.content
        except Exception as e:
            logger = logging.getLogger(__name__)
            logger.warning("ChatOllama failed, falling back to HTTP API: %s", e)
            try:
                return await self._http_invoke(messages)
            except Exception:
                pass
            if "timeout" in str(e).lower() or "timed out" in str(e).lower():
                raise TimeoutError(f"Ollama request timed out after {self.timeout} seconds") from e
            elif "connection" in str(e).lower() or "refused" in str(e).lower():
                raise ConnectionError(f"Cannot connect to Ollama at {self.base_url}") from e
            else:
                raise

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
        logger = logging.getLogger(__name__)

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

        def sanitize(text: str) -> str:
            # Remove trailing commas before } or ]
            return re.sub(r",\s*([}\]])", r"\1", text)

        def try_json_load(text: str) -> dict[str, Any] | None:
            try:
                return json.loads(sanitize(text))
            except json.JSONDecodeError:
                return None

        parsed = try_json_load(json_text)
        if parsed is not None:
            return parsed

        # Try to find JSON in the text
        json_match = re.search(r"\{[\s\S]*\}", json_text)
        if json_match:
            parsed = try_json_load(json_match.group())
            if parsed is not None:
                return parsed

        # Fallback: try Python literal parsing (handles single quotes)
        alt_text = json_text
        alt_text = re.sub(r"\bnull\b", "None", alt_text, flags=re.IGNORECASE)
        alt_text = re.sub(r"\btrue\b", "True", alt_text, flags=re.IGNORECASE)
        alt_text = re.sub(r"\bfalse\b", "False", alt_text, flags=re.IGNORECASE)
        alt_text = sanitize(alt_text)
        try:
            data = ast.literal_eval(alt_text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass

        logger.warning("Failed to parse LLM JSON response. Raw output: %s", response_text[:1000])
        raise ValueError("Failed to parse LLM response as JSON.")

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

Ensure all scores are between 0 and 100. Be specific and evidence-based in your analysis."""

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            return await self.invoke_with_json(messages)
        except Exception as exc:
            # Graceful fallback so analysis flow doesn't crash if LLM fails
            return {
                "skills": [],
                "experience_years": 0,
                "tech_stack": [],
                "domain_knowledge": [],
                "seniority": None,
                "strengths": [],
                "weaknesses": [],
                "skill_match_score": 0,
                "experience_score": 0,
                "domain_score": 0,
                "project_complexity_score": 0,
                "soft_skills_score": 0,
                "risks": [],
                "risk_level": "low",
                "technical_questions": [],
                "system_design_questions": [],
                "behavioral_questions": [],
                "custom_questions": [],
                "interview_focus_areas": [],
                "recommendation": f"LLM analysis failed: {exc}",
            }

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

Generate 3-5 questions per category. Make questions specific to the candidate's background and the role requirements."""

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
