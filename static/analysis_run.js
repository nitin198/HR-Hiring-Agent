const API_BASE_URL = ((window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || window.location.origin).replace(/\/$/, "");

function getQueryParams() {
    const params = new URLSearchParams(window.location.search);
    return {
        run_id: params.get('run_id'),
    };
}

async function loadAnalysis() {
    const params = getQueryParams();
    if (!params.run_id) {
        document.getElementById('analysis-subtitle').textContent = 'Missing analysis run id.';
        return;
    }
    const response = await fetch(`${API_BASE_URL}/api/candidates/analysis-runs/${params.run_id}`);
    if (!response.ok) {
        document.getElementById('analysis-subtitle').textContent = 'Unable to load analysis details.';
        return;
    }
    const data = await response.json();
    document.getElementById('analysis-subtitle').textContent = `Run #${data.id} • ${data.analysis_timestamp || ''}`;
    document.getElementById('analysis-jd').textContent = data.job_description_title || `JD ${data.job_description_id}`;
    document.getElementById('analysis-score').textContent = data.final_score != null ? data.final_score.toFixed(2) : 'N/A';
    document.getElementById('analysis-decision').textContent = data.decision || 'N/A';
    document.getElementById('analysis-recommendation').textContent = data.recommendation || 'N/A';

    document.getElementById('score-skill').textContent = data.skill_match_score ?? 'N/A';
    document.getElementById('score-experience').textContent = data.experience_score ?? 'N/A';
    document.getElementById('score-domain').textContent = data.domain_score ?? 'N/A';
    document.getElementById('score-project').textContent = data.project_complexity_score ?? 'N/A';
    document.getElementById('score-soft').textContent = data.soft_skills_score ?? 'N/A';

    document.getElementById('analysis-strengths').textContent = (data.strengths || []).join(', ') || 'N/A';
    document.getElementById('analysis-weaknesses').textContent = (data.weaknesses || []).join(', ') || 'N/A';
    document.getElementById('analysis-risks').textContent = (data.risks || []).join(', ') || 'N/A';
    document.getElementById('analysis-focus').textContent = (data.interview_focus_areas || []).join(', ') || 'N/A';
    document.getElementById('analysis-tech').textContent = (data.technical_questions || []).join(' | ') || 'N/A';
    document.getElementById('analysis-design').textContent = (data.system_design_questions || []).join(' | ') || 'N/A';
    document.getElementById('analysis-behavioral').textContent = (data.behavioral_questions || []).join(' | ') || 'N/A';
    document.getElementById('analysis-custom').textContent = (data.custom_questions || []).join(' | ') || 'N/A';
}

window.addEventListener('load', loadAnalysis);
