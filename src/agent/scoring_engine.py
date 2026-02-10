"""Scoring engine for candidate evaluation."""

from dataclasses import dataclass
from typing import Any

from src.config.settings import get_settings

settings = get_settings()


@dataclass
class ScoringResult:
    """Result of candidate scoring."""

    skill_match_score: float
    experience_score: float
    domain_score: float
    project_complexity_score: float
    soft_skills_score: float
    final_score: float
    decision: str
    recommendation: str


class ScoringEngine:
    """Engine for scoring candidates based on multiple dimensions."""

    def __init__(self):
        """Initialize scoring engine with settings."""
        self.weights = settings.scoring_weights
        self.thresholds = settings.decision_thresholds

    def calculate_final_score(
        self,
        skill_match_score: float,
        experience_score: float,
        domain_score: float,
        project_complexity_score: float,
        soft_skills_score: float,
    ) -> float:
        """
        Calculate final weighted score.

        Args:
            skill_match_score: Skill matching score (0-100)
            experience_score: Experience score (0-100)
            domain_score: Domain knowledge score (0-100)
            project_complexity_score: Project complexity score (0-100)
            soft_skills_score: Soft skills score (0-100)

        Returns:
            Final weighted score (0-100)
        """
        final_score = (
            skill_match_score * self.weights["skill_match"] / 100
            + experience_score * self.weights["experience"] / 100
            + domain_score * self.weights["domain_knowledge"] / 100
            + project_complexity_score * self.weights["project_complexity"] / 100
            + soft_skills_score * self.weights["soft_skills"] / 100
        )

        return round(final_score, 2)

    def determine_decision(self, final_score: float, risk_level: str = "low") -> str:
        """
        Determine hiring decision based on score and risk level.

        Args:
            final_score: Final candidate score (0-100)
            risk_level: Risk level (low, medium, high)

        Returns:
            Decision string (strong_hire, borderline, reject, hold)
        """
        # Adjust thresholds based on risk level
        if risk_level == "high":
            strong_hire_threshold = self.thresholds["strong_hire"] + 10
            borderline_threshold = self.thresholds["borderline"] + 5
        elif risk_level == "medium":
            strong_hire_threshold = self.thresholds["strong_hire"] + 5
            borderline_threshold = self.thresholds["borderline"]
        else:  # low risk
            strong_hire_threshold = self.thresholds["strong_hire"]
            borderline_threshold = self.thresholds["borderline"]

        if final_score >= strong_hire_threshold:
            return "strong_hire"
        elif final_score >= borderline_threshold:
            return "borderline"
        else:
            return "reject"

    def generate_recommendation(
        self,
        final_score: float,
        decision: str,
        strengths: list[str],
        weaknesses: list[str],
        risks: list[str],
        interview_focus_areas: list[str],
    ) -> str:
        """
        Generate hiring recommendation text.

        Args:
            final_score: Final candidate score
            decision: Hiring decision
            strengths: Candidate strengths
            weaknesses: Candidate weaknesses
            risks: Identified risks
            interview_focus_areas: Areas to focus on in interviews

        Returns:
            Recommendation text
        """
        if decision == "strong_hire":
            base = f"**Strong Hire Recommendation** (Score: {final_score}/100)\n\n"
            base += "This candidate is well-qualified for the role. "
            if strengths:
                base += f"Key strengths: {', '.join(strengths[:3])}. "
            if risks:
                base += f"Note: {len(risks)} risk(s) identified that should be explored in interviews. "
            base += "Proceed to technical interview round."
            if interview_focus_areas:
                base += f"\n\nFocus areas: {', '.join(interview_focus_areas[:3])}."

        elif decision == "borderline":
            base = f"**Borderline Candidate** (Score: {final_score}/100)\n\n"
            base += "This candidate shows potential but has some gaps. "
            if strengths:
                base += f"Strengths: {', '.join(strengths[:2])}. "
            if weaknesses:
                base += f"Areas of concern: {', '.join(weaknesses[:2])}. "
            if risks:
                base += f"Risks: {', '.join(risks[:2])}. "
            base += "Consider for interview if other candidates are not stronger."
            if interview_focus_areas:
                base += f"\n\nMust verify: {', '.join(interview_focus_areas[:3])}."

        else:  # reject
            base = f"**Not Recommended** (Score: {final_score}/100)\n\n"
            base += "This candidate does not meet the requirements for the role. "
            if weaknesses:
                base += f"Primary concerns: {', '.join(weaknesses[:3])}. "
            if risks:
                base += f"Significant risks: {', '.join(risks[:3])}. "
            base += "Do not proceed to interview."

        return base

    def score_candidate(self, analysis: dict[str, Any]) -> ScoringResult:
        """
        Score a candidate based on LLM analysis.

        Args:
            analysis: LLM analysis results

        Returns:
            ScoringResult with all scores and decision
        """
        # Extract scores from analysis
        skill_match_score = analysis.get("skill_match_score", 0)
        experience_score = analysis.get("experience_score", 0)
        domain_score = analysis.get("domain_score", 0)
        project_complexity_score = analysis.get("project_complexity_score", 0)
        soft_skills_score = analysis.get("soft_skills_score", 0)

        # Calculate final score
        final_score = self.calculate_final_score(
            skill_match_score,
            experience_score,
            domain_score,
            project_complexity_score,
            soft_skills_score,
        )

        # Determine decision
        risk_level = analysis.get("risk_level", "low")
        decision = self.determine_decision(final_score, risk_level)

        # Generate recommendation
        strengths = self._as_list(analysis.get("strengths"))
        weaknesses = self._as_list(analysis.get("weaknesses"))
        risks = self._as_list(analysis.get("risks"))
        interview_focus_areas = self._as_list(analysis.get("interview_focus_areas"))

        recommendation = self.generate_recommendation(
            final_score,
            decision,
            strengths,
            weaknesses,
            risks,
            interview_focus_areas,
        )

        return ScoringResult(
            skill_match_score=skill_match_score,
            experience_score=experience_score,
            domain_score=domain_score,
            project_complexity_score=project_complexity_score,
            soft_skills_score=soft_skills_score,
            final_score=final_score,
            decision=decision,
            recommendation=recommendation,
        )

    @staticmethod
    def _as_list(value: Any) -> list[str]:
        """Normalize possibly null values into a list."""
        if isinstance(value, list):
            return value
        return []

    def rank_candidates(self, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """
        Rank candidates by their final scores.

        Args:
            candidates: List of candidate analysis results

        Returns:
            Ranked list of candidates
        """
        # Sort by final score descending
        ranked = sorted(candidates, key=lambda x: x.get("final_score", 0), reverse=True)

        # Add rank
        for i, candidate in enumerate(ranked, 1):
            candidate["rank"] = i

        return ranked
