"""PDF report generation for candidate analyses."""

from __future__ import annotations

from io import BytesIO
from typing import Any

from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import ListFlowable, ListItem, Paragraph, SimpleDocTemplate, Spacer


def build_candidate_analysis_pdf(
    candidate: dict[str, Any],
    analysis: dict[str, Any],
    job_description: dict[str, Any],
) -> bytes:
    """Build a PDF report for a single candidate analysis."""
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=LETTER,
        leftMargin=48,
        rightMargin=48,
        topMargin=48,
        bottomMargin=48,
        title=f"Candidate Analysis - {candidate.get('name', 'Unknown')}",
    )
    styles = getSampleStyleSheet()
    story: list[Any] = []

    candidate_name = candidate.get("name") or "Unknown"
    job_title = job_description.get("title") or "Job Description"
    decision = (analysis.get("decision") or "N/A").upper()
    final_score = analysis.get("final_score")
    final_score_text = f"{final_score:.2f}" if isinstance(final_score, (int, float)) else "N/A"

    story.append(Paragraph(f"Candidate Analysis: {candidate_name}", styles["Title"]))
    story.append(Paragraph(f"Role: {job_title}", styles["Heading2"]))
    story.append(Spacer(1, 8))
    story.append(
        Paragraph(
            f"<b>Decision:</b> {decision} &nbsp;&nbsp; <b>Final Score:</b> {final_score_text}/100",
            styles["Heading3"],
        )
    )
    story.append(Spacer(1, 10))

    story.append(Paragraph("Candidate Details", styles["Heading3"]))
    story.append(Paragraph(f"<b>Email:</b> {candidate.get('email') or 'N/A'}", styles["BodyText"]))
    story.append(Paragraph(f"<b>Phone:</b> {candidate.get('phone') or 'N/A'}", styles["BodyText"]))
    story.append(Paragraph(f"<b>Experience (years):</b> {analysis.get('experience_years') or 0}", styles["BodyText"]))
    story.append(Paragraph(f"<b>Seniority:</b> {analysis.get('seniority') or 'N/A'}", styles["BodyText"]))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Score Breakdown", styles["Heading3"]))
    story.append(
        Paragraph(
            "<br/>".join(
                [
                    f"<b>Skill Match:</b> {analysis.get('skill_match_score', 0)}",
                    f"<b>Experience:</b> {analysis.get('experience_score', 0)}",
                    f"<b>Domain:</b> {analysis.get('domain_score', 0)}",
                    f"<b>Project Complexity:</b> {analysis.get('project_complexity_score', 0)}",
                    f"<b>Soft Skills:</b> {analysis.get('soft_skills_score', 0)}",
                ]
            ),
            styles["BodyText"],
        )
    )
    story.append(Spacer(1, 10))

    story.append(Paragraph("Strengths", styles["Heading3"]))
    story.append(_list_section(analysis.get("strengths"), styles))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Weaknesses", styles["Heading3"]))
    story.append(_list_section(analysis.get("weaknesses"), styles))
    story.append(Spacer(1, 6))

    story.append(Paragraph("Risks", styles["Heading3"]))
    story.append(_list_section(analysis.get("risks"), styles))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Interview Focus Areas", styles["Heading3"]))
    story.append(_list_section(analysis.get("interview_focus_areas"), styles))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Technical Questions", styles["Heading3"]))
    story.append(_list_section(analysis.get("technical_questions"), styles))
    story.append(Spacer(1, 8))

    story.append(Paragraph("System Design Questions", styles["Heading3"]))
    story.append(_list_section(analysis.get("system_design_questions"), styles))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Behavioral Questions", styles["Heading3"]))
    story.append(_list_section(analysis.get("behavioral_questions"), styles))
    story.append(Spacer(1, 8))

    story.append(Paragraph("Custom Questions", styles["Heading3"]))
    story.append(_list_section(analysis.get("custom_questions"), styles))
    story.append(Spacer(1, 10))

    story.append(Paragraph("Recommendation", styles["Heading3"]))
    story.append(Paragraph(analysis.get("recommendation") or "N/A", styles["BodyText"]))

    doc.build(story)
    pdf_bytes = buffer.getvalue()
    buffer.close()
    return pdf_bytes


def _list_section(items: Any, styles: dict) -> ListFlowable:
    if not isinstance(items, list) or not items:
        items = ["N/A"]

    list_items = [ListItem(Paragraph(str(item), styles["BodyText"])) for item in items]
    return ListFlowable(list_items, bulletType="bullet", leftIndent=16)
