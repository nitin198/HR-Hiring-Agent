const API_BASE_URL = ((window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || window.location.origin).replace(/\/$/, "");

function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

async function apiCall(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    const response = await fetch(url, {
        headers: { "Content-Type": "application/json" },
        ...options,
    });
    if (!response.ok) {
        const payload = await response.json().catch(() => ({}));
        throw new Error(payload.detail || payload.error || "Request failed");
    }
    return response.json();
}

function notifyParentHeight() {
    if (window.parent === window) {
        return;
    }
    const shell = document.querySelector(".page-shell");
    const contentHeight = shell
        ? Math.ceil(shell.getBoundingClientRect().height)
        : 0;
    const height = Math.max(contentHeight + 12, 900);
    window.parent.postMessage(
        { type: "jd_search_height", height },
        window.location.origin,
    );
}

function scheduleParentHeightSync() {
    window.requestAnimationFrame(() => notifyParentHeight());
}

function setLoading(isLoading) {
    const loading = document.getElementById("loading");
    if (!loading) {
        return;
    }
    loading.classList.toggle("d-none", !isLoading);
}

function getFilters() {
    return {
        jobDescriptionId: document.getElementById("filter-jd")?.value || "",
        query: (document.getElementById("filter-q")?.value || "").trim(),
        decision: document.getElementById("filter-decision")?.value || "",
        includeUnassigned: !!document.getElementById("filter-unassigned")?.checked,
        limitPerGroup: parseInt(document.getElementById("filter-limit")?.value || "50", 10),
    };
}

function formatDecision(decision) {
    const value = (decision || "").toLowerCase();
    if (!value) return "N/A";
    return value
        .split("_")
        .map(part => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
}

function formatDateTime(value) {
    if (!value) {
        return "N/A";
    }
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) {
        return value;
    }
    return d.toLocaleString();
}

function decisionBadge(decision) {
    const value = (decision || "").toLowerCase();
    const cls = value ? `decision-${value}` : "decision-na";
    return `<span class="decision-badge ${cls}">${escapeHtml(formatDecision(value))}</span>`;
}

function renderSkills(skills, limit = 4) {
    const list = (skills || []).slice(0, limit);
    if (!list.length) {
        return '<span class="text-muted small">No skills</span>';
    }
    return list.map(skill => `<span class="skill-chip">${escapeHtml(skill)}</span>`).join("");
}

function renderCandidateTableRows(rows, mode) {
    if (!rows.length) {
        return `<tr><td colspan="8" class="text-muted text-center py-3">No candidates in this section.</td></tr>`;
    }

    return rows.map(item => {
        const candidate = item.candidate || {};
        const analysis = item.analysis || {};
        const rank = mode === "freshers"
            ? `#${item.skill_rank || "-"}`
            : `#${item.rank || "-"}`;
        const score = typeof item.ranking_score === "number" ? item.ranking_score.toFixed(2) : "N/A";
        const skillScore = typeof item.skill_match_score === "number" ? `${item.skill_match_score.toFixed(1)}%` : "0%";
        const analysisLink = analysis.id
            ? `<a class="btn btn-sm btn-outline-primary" href="${API_BASE_URL}/static/analysis_run.html?run_id=${analysis.id}" target="_blank">Analysis</a>`
            : `<span class="text-muted small">No analysis</span>`;
        const pdfLink = analysis.id
            ? `<a class="btn btn-sm btn-outline-success" href="${API_BASE_URL}/api/candidates/analysis-runs/${analysis.id}/pdf" target="_blank">PDF</a>`
            : "";

        return `
            <tr>
                <td>${escapeHtml(rank)}</td>
                <td>
                    <div class="fw-semibold">${escapeHtml(candidate.name || "Unknown")}</div>
                    <div class="small text-muted">${escapeHtml(candidate.email || "No email")}</div>
                </td>
                <td>${escapeHtml(String(item.experience_years ?? 0))}</td>
                <td>${escapeHtml(score)}</td>
                <td>${escapeHtml(skillScore)}</td>
                <td>${decisionBadge(analysis.decision)}</td>
                <td>${renderSkills(item.matched_skills && item.matched_skills.length ? item.matched_skills : item.candidate_skills)}</td>
                <td>
                    <div class="d-flex flex-wrap gap-1">
                        ${analysisLink}
                        ${pdfLink}
                    </div>
                </td>
            </tr>
        `;
    }).join("");
}

function renderGroup(group) {
    const jd = group.job_description || {};
    const counts = group.counts || {};
    const requiredSkills = renderSkills(jd.required_skills || [], 6);
    const experiencedRows = group.experienced || [];
    const fresherRows = group.freshers || [];

    const experiencedSection = experiencedRows.length ? `
            <div class="section-block mb-3">
                <div class="section-title">Experienced <span class="badge text-bg-light">Ranked by score</span></div>
                <div class="table-responsive">
                    <table class="table table-sm table-hover">
                        <thead>
                            <tr>
                                <th>Rank</th>
                                <th>Candidate</th>
                                <th>Exp</th>
                                <th>Score</th>
                                <th>Skill Match</th>
                                <th>Decision</th>
                                <th>Skills</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>${renderCandidateTableRows(experiencedRows, "experienced")}</tbody>
                    </table>
                </div>
            </div>
    ` : "";

    const fresherSection = fresherRows.length ? `
            <div class="section-block">
                <div class="section-title">Freshers <span class="badge text-bg-info">Sorted by skill match</span></div>
                <div class="table-responsive">
                    <table class="table table-sm table-hover">
                        <thead>
                            <tr>
                                <th>Skill Rank</th>
                                <th>Candidate</th>
                                <th>Exp</th>
                                <th>Score</th>
                                <th>Skill Match</th>
                                <th>Decision</th>
                                <th>Skills</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>${renderCandidateTableRows(fresherRows, "freshers")}</tbody>
                    </table>
                </div>
            </div>
    ` : "";

    return `
        <article class="jd-group">
            <div class="jd-header">
                <div>
                    <div class="jd-title">${escapeHtml(jd.title || "Untitled JD")} <span class="text-muted small">(ID: ${escapeHtml(jd.id || "")})</span></div>
                    <div class="jd-meta">
                        Domain: ${escapeHtml(jd.domain || "N/A")} | Min Exp: ${escapeHtml(jd.min_experience_years ?? 0)} years
                    </div>
                </div>
                <div class="text-end">
                    <div class="jd-meta">Total: <strong>${escapeHtml(counts.total || 0)}</strong></div>
                    <div class="jd-meta">Experienced: <strong>${escapeHtml(counts.experienced || 0)}</strong> | Freshers: <strong>${escapeHtml(counts.freshers || 0)}</strong></div>
                </div>
            </div>
            <div class="mb-2"><small class="text-muted">JD Skills:</small> ${requiredSkills}</div>
            ${experiencedSection}
            ${fresherSection}
        </article>
    `;
}

function renderSummary(payload) {
    const target = document.getElementById("summary-cards");
    const summary = payload.summary || {};
    const groups = payload.groups || [];
    const unassigned = payload.unassigned || {};
    const unassignedCount = (unassigned.experienced || []).length + (unassigned.freshers || []).length;
    const fresherCountInGroups = groups.reduce(
        (sum, group) => sum + ((group.freshers || []).length),
        0,
    );
    const fresherCount = fresherCountInGroups + ((unassigned.freshers || []).length);

    target.innerHTML = `
        <div class="summary-grid">
            <div class="summary-card">
                <div class="label">JD Groups</div>
                <div class="value">${escapeHtml(summary.group_count || groups.length)}</div>
            </div>
            <div class="summary-card">
                <div class="label">Candidates Displayed</div>
                <div class="value">${escapeHtml(summary.total_candidates || 0)}</div>
            </div>
            <div class="summary-card">
                <div class="label">No JD Match</div>
                <div class="value">${escapeHtml(unassignedCount)}</div>
            </div>
            <div class="summary-card">
                <div class="label">Freshers</div>
                <div class="value">${escapeHtml(fresherCount)}</div>
            </div>
        </div>
    `;
    scheduleParentHeightSync();
}

function renderUnassigned(unassigned) {
    const experienced = unassigned?.experienced || [];
    const freshers = unassigned?.freshers || [];
    if (!experienced.length && !freshers.length) {
        return "";
    }

    const experiencedSection = experienced.length ? `
            <div class="section-block mb-3">
                <div class="section-title">Experienced</div>
                <div class="table-responsive">
                    <table class="table table-sm table-hover">
                        <thead>
                            <tr>
                                <th>Rank</th>
                                <th>Candidate</th>
                                <th>Exp</th>
                                <th>Score</th>
                                <th>Skill Match</th>
                                <th>Decision</th>
                                <th>Skills</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>${renderCandidateTableRows(experienced, "experienced")}</tbody>
                    </table>
                </div>
            </div>
    ` : "";

    const fresherSection = freshers.length ? `
            <div class="section-block">
                <div class="section-title">Freshers <span class="badge text-bg-info">Sorted by skill strength</span></div>
                <div class="table-responsive">
                    <table class="table table-sm table-hover">
                        <thead>
                            <tr>
                                <th>Skill Rank</th>
                                <th>Candidate</th>
                                <th>Exp</th>
                                <th>Score</th>
                                <th>Skill Match</th>
                                <th>Decision</th>
                                <th>Skills</th>
                                <th>Actions</th>
                            </tr>
                        </thead>
                        <tbody>${renderCandidateTableRows(freshers, "freshers")}</tbody>
                    </table>
                </div>
            </div>
    ` : "";

    return `
        <article class="jd-group">
            <div class="jd-header">
                <div>
                    <div class="jd-title"><i class="bi bi-exclamation-circle me-1"></i>No JD Match (Unassigned)</div>
                    <div class="jd-meta">Candidates are not linked to any job description yet.</div>
                </div>
            </div>
            ${experiencedSection}
            ${fresherSection}
        </article>
    `;
}

function renderResults(payload) {
    const container = document.getElementById("results-container");
    const groups = payload.groups || [];
    const unassigned = payload.unassigned || { experienced: [], freshers: [] };

    if (!groups.length && !(unassigned.experienced || []).length && !(unassigned.freshers || []).length) {
        container.innerHTML = `
            <div class="empty-state card">
                <div class="card-body">
                    <i class="bi bi-search" style="font-size: 2rem;"></i>
                    <p class="mt-2 mb-0">No candidates match the selected filters.</p>
                </div>
            </div>
        `;
        scheduleParentHeightSync();
        return;
    }

    const groupsHtml = groups.map(group => renderGroup(group)).join("");
    container.innerHTML = `${groupsHtml}${renderUnassigned(unassigned)}`;
    scheduleParentHeightSync();
}

async function loadJobDescriptionOptions() {
    const select = document.getElementById("filter-jd");
    if (!select) return;
    try {
        const jds = await apiCall("/api/job-descriptions");
        select.innerHTML = '<option value="">All JDs</option>';
        (jds || []).forEach(jd => {
            select.innerHTML += `<option value="${jd.id}">${escapeHtml(jd.title || `JD ${jd.id}`)}</option>`;
        });
    } catch (error) {
        console.error("Failed to load JD filter options", error);
    }
}

async function loadRankedResults() {
    const filters = getFilters();
    const params = new URLSearchParams();
    if (filters.jobDescriptionId) params.append("job_description_id", filters.jobDescriptionId);
    if (filters.query) params.append("q", filters.query);
    if (filters.decision) params.append("decision", filters.decision);
    params.append("include_unassigned", String(filters.includeUnassigned));
    params.append("limit_per_group", String(filters.limitPerGroup));

    setLoading(true);
    try {
        const payload = await apiCall(`/api/reports/ranking-grouped?${params.toString()}`);
        renderSummary(payload);
        renderResults(payload);
    } catch (error) {
        document.getElementById("results-container").innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle me-1"></i>
                Failed to load candidate rankings: ${escapeHtml(error.message)}
            </div>
        `;
    } finally {
        setLoading(false);
    }
}

document.addEventListener("DOMContentLoaded", async () => {
    await loadJobDescriptionOptions();
    await loadRankedResults();
    scheduleParentHeightSync();

    document.getElementById("btn-apply")?.addEventListener("click", loadRankedResults);
    document.getElementById("btn-refresh")?.addEventListener("click", async () => {
        await loadJobDescriptionOptions();
        await loadRankedResults();
    });

    document.getElementById("filter-q")?.addEventListener("keydown", event => {
        if (event.key === "Enter") {
            event.preventDefault();
            loadRankedResults();
        }
    });
});
