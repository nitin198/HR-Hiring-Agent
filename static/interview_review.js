const API_BASE_URL = 'http://localhost:8000';

let candidateId = null;
let sessionId = null;
let sessions = [];

function getQueryParams() {
    const params = new URLSearchParams(window.location.search);
    return {
        candidate_id: params.get('candidate_id'),
    };
}

async function apiCall(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };
    const response = await fetch(url, { ...defaultOptions, ...options });
    if (!response.ok) {
        let errorDetail = 'Request failed';
        try {
            const data = await response.json();
            errorDetail = data.detail || errorDetail;
        } catch (err) {
            // ignore
        }
        throw new Error(errorDetail);
    }
    if (response.status === 204) {
        return null;
    }
    return await response.json();
}

function renderSessionOptions() {
    const select = document.getElementById('session-select');
    select.innerHTML = '';
    if (!sessions.length) {
        select.innerHTML = '<option value="">No sessions</option>';
        return;
    }
    sessions.forEach((session) => {
        const option = document.createElement('option');
        option.value = session.id;
        option.textContent = `Session #${session.id} (${session.status})`;
        select.appendChild(option);
    });
    select.value = sessionId;
}

async function loadSessions() {
    sessions = await apiCall(`/api/interviews?candidate_id=${candidateId}`);
    if (sessions.length) {
        sessionId = sessions[0].id;
    }
    renderSessionOptions();
    if (sessionId) {
        await loadSessionDetail(sessionId);
    }
}

function renderSummary(detail) {
    document.getElementById('summary-score').textContent = detail.session.overall_score
        ? detail.session.overall_score.toFixed(1)
        : 'N/A';
    document.getElementById('summary-recommendation').textContent = detail.session.recommendation || 'N/A';
    document.getElementById('summary-status').textContent = detail.session.status || 'N/A';
    document.getElementById('summary-text').textContent = detail.session.summary || 'No summary available.';
    document.getElementById('summary-strengths').textContent = detail.feedback?.strengths?.join(', ') || 'N/A';
    document.getElementById('summary-concerns').textContent = detail.feedback?.concerns?.join(', ') || 'N/A';
    document.getElementById('summary-next-steps').textContent = detail.feedback?.next_steps || 'N/A';
}

function renderTranscripts(detail) {
    const container = document.getElementById('transcript-list');
    const responsesByQuestion = new Map(detail.responses.map(resp => [resp.question_id, resp]));
    if (!detail.questions.length) {
        container.textContent = 'No transcripts yet.';
        return;
    }
    container.innerHTML = detail.questions.map((question) => {
        const response = responsesByQuestion.get(question.id);
        const transcript = response ? response.transcript_text : '(no answer)';
        const score = response && response.score_1_to_10 != null ? response.score_1_to_10 : 'N/A';
        return `
            <div class="transcript-item">
                <div class="transcript-meta">${question.category.toUpperCase()} • Score: ${score}</div>
                <div class="fw-semibold">${question.question_text}</div>
                <div class="text-muted mt-2">${transcript}</div>
            </div>
        `;
    }).join('');
}

async function loadSessionDetail(id) {
    const detail = await apiCall(`/api/interviews/${id}`);
    renderSummary(detail);
    renderTranscripts(detail);
}

document.getElementById('session-select').addEventListener('change', async (event) => {
    sessionId = parseInt(event.target.value, 10);
    if (sessionId) {
        await loadSessionDetail(sessionId);
    }
});

document.getElementById('delete-session').addEventListener('click', async () => {
    if (!sessionId) {
        return;
    }
    if (!confirm('Delete this interview session? This cannot be undone.')) {
        return;
    }
    await apiCall(`/api/interviews/${sessionId}`, { method: 'DELETE' });
    await loadSessions();
});

window.addEventListener('load', async () => {
    const params = getQueryParams();
    candidateId = params.candidate_id ? parseInt(params.candidate_id, 10) : null;
    if (!candidateId) {
        alert('Missing candidate_id in URL.');
        return;
    }
    document.getElementById('review-candidate-id').textContent = candidateId;
    await loadSessions();
});
