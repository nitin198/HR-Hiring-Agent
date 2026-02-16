const API_BASE_URL = ((window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || window.location.origin).replace(/\/$/, "");

function getQueryParams() {
    const params = new URLSearchParams(window.location.search);
    return {
        run_id: params.get("run_id"),
    };
}

function formatDateTime(value) {
    if (!value) return "N/A";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return value;
    return date.toLocaleString();
}

function toTitle(value) {
    if (!value) return "N/A";
    return String(value).replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
}

function normalizeText(value) {
    return String(value || "")
        .replace(/\*\*/g, "")
        .replace(/\r\n/g, "\n")
        .trim();
}

function splitRecommendationToBullets(text) {
    const normalized = normalizeText(text);
    if (!normalized) return [];

    const rawLines = normalized
        .split("\n")
        .map(line => line.trim())
        .filter(Boolean);

    const bullets = [];
    rawLines.forEach(line => {
        const cleanLine = line.replace(/^[-*]\s+/, "").trim();
        if (!cleanLine) return;

        const sentenceParts = cleanLine
            .split(/(?<=[.!?])\s+(?=[A-Z])/)
            .map(part => part.trim())
            .filter(Boolean);

        if (sentenceParts.length > 1) {
            bullets.push(...sentenceParts);
        } else {
            bullets.push(cleanLine);
        }
    });

    return bullets;
}

function renderRecommendation(text) {
    const container = document.getElementById("analysis-recommendation");
    if (!container) return;

    const bullets = splitRecommendationToBullets(text);
    if (bullets.length === 0) {
        container.innerHTML = '<div class="empty-block">Not available</div>';
        return;
    }

    container.innerHTML = `<ul class="recommendation-list">${bullets.map(item => `<li>${item}</li>`).join("")}</ul>`;
}

function renderList(elementId, items, ordered = false) {
    const el = document.getElementById(elementId);
    if (!el) return;

    if (!Array.isArray(items) || items.length === 0) {
        el.innerHTML = '<div class="empty-block">Not available</div>';
        return;
    }

    const tag = ordered ? "ol" : "ul";
    const className = ordered ? "question-list" : "analysis-list";
    el.innerHTML = `<${tag} class="${className}">${items.map(item => `<li>${item}</li>`).join("")}</${tag}>`;
}

function setMetric(metricId, barId, value) {
    const label = document.getElementById(metricId);
    const bar = document.getElementById(barId);
    const score = typeof value === "number" ? value : Number(value);

    if (!label || !bar) return;

    if (Number.isNaN(score)) {
        label.textContent = "N/A";
        bar.style.width = "0%";
        return;
    }

    label.textContent = score.toFixed(2);
    const normalized = Math.max(0, Math.min(100, score));
    bar.style.width = `${normalized}%`;
}

function setDecisionAndScore(decision, finalScore, riskLevel) {
    const decisionEl = document.getElementById("analysis-decision");
    const scoreRing = document.getElementById("score-ring");
    const riskEl = document.getElementById("analysis-risk-level");
    const scoreEl = document.getElementById("analysis-score");
    const score = typeof finalScore === "number" ? finalScore : Number(finalScore);
    const decisionLabel = toTitle(decision);

    if (decisionEl) {
        decisionEl.textContent = `Decision: ${decisionLabel}`;
        decisionEl.classList.remove("chip-decision-strong-hire", "chip-decision-borderline", "chip-decision-reject");
        if (decision === "strong_hire") decisionEl.classList.add("chip-decision-strong-hire");
        if (decision === "borderline") decisionEl.classList.add("chip-decision-borderline");
        if (decision === "reject") decisionEl.classList.add("chip-decision-reject");
    }

    if (riskEl) {
        riskEl.textContent = `Risk: ${toTitle(riskLevel)}`;
    }

    if (scoreEl) {
        scoreEl.textContent = Number.isNaN(score) ? "N/A" : score.toFixed(1);
    }

    if (scoreRing) {
        scoreRing.classList.remove("score-high", "score-mid", "score-low");
        if (Number.isNaN(score)) return;
        if (score >= 70) scoreRing.classList.add("score-high");
        else if (score >= 50) scoreRing.classList.add("score-mid");
        else scoreRing.classList.add("score-low");
    }
}

async function loadAnalysis() {
    const params = getQueryParams();
    if (!params.run_id) {
        document.getElementById("analysis-subtitle").textContent = "Missing analysis run id.";
        return;
    }

    const response = await fetch(`${API_BASE_URL}/api/candidates/analysis-runs/${params.run_id}`);
    if (!response.ok) {
        document.getElementById("analysis-subtitle").textContent = "Unable to load analysis details.";
        return;
    }

    const data = await response.json();
    document.getElementById("analysis-subtitle").textContent = `Run #${data.id} | ${formatDateTime(data.analysis_timestamp)}`;
    document.getElementById("analysis-jd").textContent = data.job_description_title || `JD ${data.job_description_id}`;
    renderRecommendation(data.recommendation);

    setDecisionAndScore(data.decision, data.final_score, data.risk_level);
    setMetric("score-skill", "bar-skill", data.skill_match_score);
    setMetric("score-experience", "bar-experience", data.experience_score);
    setMetric("score-domain", "bar-domain", data.domain_score);
    setMetric("score-project", "bar-project", data.project_complexity_score);
    setMetric("score-soft", "bar-soft", data.soft_skills_score);

    renderList("analysis-strengths", data.strengths);
    renderList("analysis-weaknesses", data.weaknesses);
    renderList("analysis-risks", data.risks);
    renderList("analysis-focus", data.interview_focus_areas);
    renderList("analysis-tech", data.technical_questions, true);
    renderList("analysis-design", data.system_design_questions, true);
    renderList("analysis-behavioral", data.behavioral_questions, true);
    renderList("analysis-custom", data.custom_questions, true);
}

window.addEventListener("load", loadAnalysis);
