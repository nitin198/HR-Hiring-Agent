// API Base URL
const API_BASE_URL = ((window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || window.location.origin).replace(/\/$/, "");

// State Management
let currentStep = 1;
let selectedJobDescription = null;
let addedCandidates = [];
let jdCandidatesCache = [];
let analysisResults = null;
let outlookCandidates = [];
let outlookSelection = new Set();
let aiConsoleTimer = null;
let aiConsoleCursor = 0;
let aiConsoleLinesRendered = 0;
let pipelineTimer = null;
let pipelineStage = 0;
let pipelineProgress = [0, 0, 0, 0];
let pipelineCompleted = false;

// Utility Functions
function showToast(message, type = 'success') {
    const toastContainer = document.getElementById('toast-container');
    const toastId = 'toast-' + Date.now();
    
    const toastHTML = `
        <div id="${toastId}" class="toast align-items-center text-white bg-${type} border-0" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="d-flex">
                <div class="toast-body">
                    ${message}
                </div>
                <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        </div>
    `;
    
    toastContainer.insertAdjacentHTML('beforeend', toastHTML);
    const toastElement = document.getElementById(toastId);
    const toast = new bootstrap.Toast(toastElement);
    toast.show();
    
    toastElement.addEventListener('hidden.bs.toast', () => {
        toastElement.remove();
    });
}

function formatScore(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : 'N/A';
}

function formatCandidateName(name) {
    if (!name) {
        return 'Unknown';
    }
    const normalized = name.replace(/\\/g, '/');
    const lastSegment = normalized.split('/').pop() || name;
    const withoutExt = lastSegment.replace(/\.[^/.]+$/, '');
    return withoutExt.replace(/_/g, ' ').trim() || name;
}

function getCandidateId(result) {
    const candidate = result.candidate || result;
    return candidate && candidate.id ? candidate.id : null;
}

function downloadCandidatePdf(candidateId) {
    if (!candidateId) {
        showToast('Candidate ID not available for PDF download', 'warning');
        return;
    }
    const url = `${API_BASE_URL}/api/candidates/${candidateId}/analysis/pdf`;
    window.open(url, '_blank');
}

function downloadAllCandidatePdfs() {
    let ids = [];
    if (analysisResults && analysisResults.length > 0) {
        ids = analysisResults.map(result => getCandidateId(result)).filter(Boolean);
    } else {
        const container = document.getElementById('detailed-results');
        if (container && container.dataset.candidateIds) {
            ids = container.dataset.candidateIds.split(',').map(id => parseInt(id, 10)).filter(Boolean);
        }
    }
    if (ids.length === 0) {
        showToast('No candidate IDs available for bulk download', 'warning');
        return;
    }
    const params = ids.map(id => `candidate_ids=${encodeURIComponent(id)}`).join('&');
    const url = `${API_BASE_URL}/api/candidates/analysis/pdf?${params}`;
    window.open(url, '_blank');
}

function copyInterviewLink(link) {
    if (!link) {
        showToast('Interview link not available', 'warning');
        return;
    }
    navigator.clipboard.writeText(link)
        .then(() => showToast('Interview link copied to clipboard!'))
        .catch(() => showToast('Failed to copy link', 'danger'));
}

const AI_CONSOLE_EVENTS = [
    "Booting hiring pipeline engine...",
    "Loading job description signals...",
    "Parsing resume content and metadata...",
    "Extracting skills, stack, and seniority markers...",
    "Computing experience alignment curve...",
    "Assessing project complexity indicators...",
    "Cross-checking domain relevance...",
    "Evaluating risk factors and gaps...",
    "Generating interview focus areas...",
    "Synthesizing technical questions (5+)...",
    "Synthesizing system design questions (5+)...",
    "Synthesizing behavioral questions (5+)...",
    "Calibrating final score and decision...",
    "Compiling detailed analysis report...",
];

function startAiConsole() {
    const body = document.getElementById('ai-console-body');
    if (!body) {
        return;
    }
    body.innerHTML = '';
    aiConsoleCursor = 0;
    aiConsoleLinesRendered = 0;
    startPipelineAnimation();

    const renderLine = () => {
        if (!document.getElementById('analysis-loading')?.classList.contains('active')) {
            stopAiConsole();
            return;
        }

        const timestamp = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
        const message = AI_CONSOLE_EVENTS[aiConsoleCursor % AI_CONSOLE_EVENTS.length];
        aiConsoleCursor += 1;
        aiConsoleLinesRendered += 1;

        const line = document.createElement('div');
        line.className = 'ai-console-line';
        line.innerHTML = `<span class="ai-console-timestamp">${timestamp}</span><span>${message}</span>`;
        body.appendChild(line);

        const lines = body.querySelectorAll('.ai-console-line');
        if (lines.length > 8) {
            lines[0].remove();
        }

        if (aiConsoleLinesRendered % 4 === 0) {
            const caretLine = document.createElement('div');
            caretLine.className = 'ai-console-line';
            caretLine.innerHTML = `<span class="ai-console-timestamp">${timestamp}</span><span>Awaiting next signal<span class="ai-console-caret"></span></span>`;
            body.appendChild(caretLine);
        }
    };

    renderLine();
    aiConsoleTimer = window.setInterval(renderLine, 900);
}

function stopAiConsole() {
    if (aiConsoleTimer) {
        clearInterval(aiConsoleTimer);
        aiConsoleTimer = null;
    }
    stopPipelineAnimation();
}

function startPipelineAnimation() {
    const pipeline = document.getElementById('ai-pipeline');
    const dot = document.getElementById('ai-pipeline-dot');
    if (!pipeline || !dot) {
        return;
    }

    pipelineStage = 0;
    pipelineProgress = [0, 0, 0, 0];
    pipelineCompleted = false;
    updatePipelineUI();

    const tick = () => {
        if (!document.getElementById('analysis-loading')?.classList.contains('active')) {
            stopPipelineAnimation();
            return;
        }
        if (pipelineCompleted) {
            return;
        }

        const increment = 4 + Math.random() * 6;
        const cap = pipelineStage === 3 ? 92 : 95;
        pipelineProgress[pipelineStage] = Math.min(cap, pipelineProgress[pipelineStage] + increment);

        if (pipelineProgress[pipelineStage] >= cap && pipelineStage < 3) {
            pipelineProgress[pipelineStage] = 100;
            pipelineStage += 1;
            pipelineProgress[pipelineStage] = Math.max(pipelineProgress[pipelineStage], 6 + Math.random() * 8);
        }
        updatePipelineUI();
    };

    pipelineTimer = window.setInterval(tick, 700);
}

function stopPipelineAnimation() {
    if (pipelineTimer) {
        clearInterval(pipelineTimer);
        pipelineTimer = null;
    }
    finalizePipelineUI();
}

function updatePipelineUI() {
    const pipeline = document.getElementById('ai-pipeline');
    const dot = document.getElementById('ai-pipeline-dot');
    if (!pipeline || !dot) {
        return;
    }
    const stages = pipeline.querySelectorAll('.ai-pipeline-stage');
    stages.forEach((stageEl, index) => {
        stageEl.classList.toggle('active', index === pipelineStage);
        const progressEl = document.getElementById(`pipeline-progress-${index}`);
        if (progressEl) {
            progressEl.textContent = `${Math.round(pipelineProgress[index])}%`;
        }
    });

    const activeStage = stages[pipelineStage];
    if (activeStage) {
        const pipelineRect = pipeline.getBoundingClientRect();
        const stageRect = activeStage.getBoundingClientRect();
        const centerX = stageRect.left - pipelineRect.left + stageRect.width / 2 - 6;
        dot.style.left = `${Math.max(8, Math.min(centerX, pipelineRect.width - 16))}px`;
    }
}

function finalizePipelineUI() {
    const pipeline = document.getElementById('ai-pipeline');
    if (!pipeline) {
        return;
    }
    pipelineCompleted = true;
    pipelineStage = 3;
    pipelineProgress = [100, 100, 100, 100];
    updatePipelineUI();
}

// API Functions
async function apiCall(endpoint, options = {}) {
    const url = `${API_BASE_URL}${endpoint}`;
    const defaultOptions = {
        headers: {
            'Content-Type': 'application/json',
        },
    };
    
    try {
        const response = await fetch(url, { ...defaultOptions, ...options });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'API request failed');
        }
        
        return await response.json();
    } catch (error) {
        console.error('API Error:', error);
        throw error;
    }
}

// Step Navigation
function goToStep(stepNumber) {
    // Hide all step contents
    for (let i = 1; i <= 4; i++) {
        document.getElementById(`step-${i}-content`).style.display = 'none';
        document.getElementById(`step-${i}`).classList.remove('active');
    }
    
    // Show selected step content
    document.getElementById(`step-${stepNumber}-content`).style.display = 'block';
    document.getElementById(`step-${stepNumber}`).classList.add('active');
    
    // Mark previous steps as completed
    for (let i = 1; i < stepNumber; i++) {
        document.getElementById(`step-${i}`).classList.add('completed');
    }
    
    currentStep = stepNumber;
}

// Load Job Descriptions
async function loadJobDescriptions() {
    try {
        const jds = await apiCall('/api/job-descriptions');
        const select = document.getElementById('selected-jd');
        select.innerHTML = '<option value="">Select Job Description</option>';
        
        jds.forEach(jd => {
            select.innerHTML += `<option value="${jd.id}">${jd.title}</option>`;
        });
        
    } catch (error) {
        console.error('Failed to load job descriptions:', error);
    }
}

// Create Job Description
document.getElementById('jd-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    
    const title = document.getElementById('jd-title').value;
    const description = document.getElementById('jd-description').value;
    const skills = document.getElementById('jd-skills').value.split(',').map(s => s.trim()).filter(s => s);
    const experience = parseFloat(document.getElementById('jd-experience').value) || 0;
    const domain = document.getElementById('jd-domain').value;
    
    try {
        await apiCall('/api/job-descriptions', {
            method: 'POST',
            body: JSON.stringify({
                title,
                description,
                required_skills: skills,
                min_experience_years: experience,
                domain
            })
        });
        
        showToast('Job description created successfully!');
        document.getElementById('jd-form').reset();
        
        // Hide the collapse form using Bootstrap API
        const collapseElement = document.getElementById('create-jd-form');
        const bsCollapse = bootstrap.Collapse.getInstance(collapseElement);
        if (bsCollapse) {
            bsCollapse.hide();
        }
        
        loadJobDescriptions();
        
    } catch (error) {
        showToast('Failed to create job description: ' + error.message, 'danger');
    }
});

// Step 1: Select Job Description
document.getElementById('selected-jd').addEventListener('change', async (e) => {
    const jdId = e.target.value;
    
    if (jdId) {
        try {
            selectedJobDescription = await apiCall(`/api/job-descriptions/${jdId}`);
            document.getElementById('btn-step-1').disabled = false;
            await loadCandidatesForSelectedJd();
        } catch (error) {
            showToast('Failed to load job description: ' + error.message, 'danger');
        }
    } else {
        selectedJobDescription = null;
        document.getElementById('btn-step-1').disabled = true;
        const listContainer = document.getElementById('jd-candidates-list');
        if (listContainer) {
            listContainer.innerHTML = '<p class="text-muted">Select a job description to load candidates.</p>';
        }
    }
});

document.getElementById('btn-step-1').addEventListener('click', () => {
    goToStep(2);
    loadCandidatesForSelectedJd();
});

async function loadCandidatesForSelectedJd() {
    const listContainer = document.getElementById('jd-candidates-list');
    if (!listContainer) {
        return;
    }
    listContainer.innerHTML = '<p class="text-muted">Loading candidates...</p>';
    try {
        const candidates = await apiCall(`/api/candidates`);
        jdCandidatesCache = candidates || [];
        if (!jdCandidatesCache.length) {
            listContainer.innerHTML = '<p class="text-muted">No candidates available.</p>';
            return;
        }
        let html = '<div class="list-group">';
        jdCandidatesCache.forEach(candidate => {
            html += `
                <div class="list-group-item d-flex justify-content-between align-items-center">
                    <div>
                        <h6 class="mb-1">${formatCandidateName(candidate.name)}</h6>
                        <small class="text-muted">${candidate.email || 'No email'} • ${candidate.phone || 'No phone'}</small>
                    </div>
                    <input type="checkbox" class="form-check-input jd-candidate-checkbox" data-candidate-id="${candidate.id}">
                </div>
            `;
        });
        html += '</div>';
        listContainer.innerHTML = html;
    } catch (error) {
        listContainer.innerHTML = `<div class="alert alert-danger">Failed to load candidates: ${error.message}</div>`;
    }
}

// Override Step 2 loader to include filters and richer display (latest 20)
loadCandidatesForSelectedJd = async () => {
    const listContainer = document.getElementById('jd-candidates-list');
    if (!listContainer) {
        return;
    }
    listContainer.innerHTML = '<p class="text-muted">Loading candidates...</p>';
    try {
        const name = document.getElementById('step2-filter-name')?.value || '';
        const skills = document.getElementById('step2-filter-skills')?.value || '';
        const minExp = document.getElementById('step2-filter-min-exp')?.value || '';
        const maxExp = document.getElementById('step2-filter-max-exp')?.value || '';
        const jdId = document.getElementById('step2-filter-jd')?.value || '';
        const createdFrom = document.getElementById('step2-filter-from')?.value || '';
        const createdTo = document.getElementById('step2-filter-to')?.value || '';

        const params = new URLSearchParams();
        if (name) params.append('name', name);
        if (skills) params.append('skills', skills);
        if (minExp) params.append('min_experience', minExp);
        if (maxExp) params.append('max_experience', maxExp);
        if (jdId) params.append('job_description_id', jdId);
        if (createdFrom) params.append('created_from', createdFrom);
        if (createdTo) params.append('created_to', createdTo);
        params.append('limit', '20');

        const candidates = await apiCall(`/api/candidates/summary?${params.toString()}`);
        jdCandidatesCache = (candidates || []).map(item => ({
            ...item.candidate,
            profile: item.profile,
            job_links: item.job_links || [],
        }));
        if (!jdCandidatesCache.length) {
            listContainer.innerHTML = '<p class="text-muted">No candidates available.</p>';
            return;
        }
        let html = '<div class="list-group">';
        jdCandidatesCache.forEach(candidate => {
            const profile = candidate.profile || {};
            const headline = profile.headline || profile.current_role || 'Role not specified';
            const exp = profile.total_experience_years != null ? `${profile.total_experience_years} yrs` : 'Exp N/A';
            const linkBadges = candidate.job_links && candidate.job_links.length
                ? candidate.job_links.map(link => `<span class="badge bg-light text-dark me-1">${link.title}</span>`).join('')
                : '<span class="text-muted">No JD linked</span>';
            html += `
                <div class="list-group-item d-flex justify-content-between align-items-center">
                    <div>
                        <h6 class="mb-1">${formatCandidateName(candidate.name)}</h6>
                        <small class="text-muted">${headline} • ${exp}</small>
                        <div class="mt-1">${linkBadges}</div>
                    </div>
                    <input type="checkbox" class="form-check-input jd-candidate-checkbox" data-candidate-id="${candidate.id}">
                </div>
            `;
        });
        html += '</div>';
        listContainer.innerHTML = html;
        wireStep2Selection();
    } catch (error) {
        listContainer.innerHTML = `<div class="alert alert-danger">Failed to load candidates: ${error.message}</div>`;
    }
};

function wireStep2Selection() {
    const nextButton = document.getElementById('btn-step-2');
    const checkboxes = document.querySelectorAll('.jd-candidate-checkbox');
    const updateState = () => {
        const anyChecked = Array.from(checkboxes).some(box => box.checked);
        if (nextButton) {
            nextButton.disabled = !anyChecked;
        }
    };
    checkboxes.forEach(box => {
        box.addEventListener('change', updateState);
    });
    updateState();
}

document.getElementById('btn-back-1').addEventListener('click', () => {
    goToStep(1);
});

document.getElementById('btn-step-2').addEventListener('click', () => {
    const selectedIds = Array.from(document.querySelectorAll('.jd-candidate-checkbox'))
        .filter(box => box.checked)
        .map(box => parseInt(box.dataset.candidateId, 10));
    if (selectedIds.length === 0) {
        showToast('Select at least one candidate to analyze', 'warning');
        return;
    }
    addedCandidates = jdCandidatesCache.filter(candidate => selectedIds.includes(candidate.id));

    // Update step 3 content
    document.getElementById('candidate-count').textContent = addedCandidates.length;
    
    if (selectedJobDescription) {
        document.getElementById('selected-jd-info').innerHTML = `
            <h6>${selectedJobDescription.title}</h6>
            <p class="mb-0 text-muted">${selectedJobDescription.description.substring(0, 200)}...</p>
        `;
    }
    
    let candidatesHtml = '';
    addedCandidates.forEach(candidate => {
        candidatesHtml += `
            <div class="candidate-item d-flex justify-content-between align-items-center">
                <div>
                        <h6 class="mb-1">${formatCandidateName(candidate.name)}</h6>
                    <small class="text-muted">${candidate.email || 'No email'}</small>
                </div>
                <input type="checkbox" class="form-check-input analyze-checkbox" data-candidate-id="${candidate.id}" checked>
            </div>
        `;
    });
    document.getElementById('candidates-to-analyze').innerHTML = candidatesHtml || '<p class="text-muted">No candidates to analyze</p>';

    document.getElementById('btn-analyze').disabled = addedCandidates.length === 0;
    const analyzeSelectedButton = document.getElementById('btn-analyze-selected');
    if (analyzeSelectedButton) {
        analyzeSelectedButton.disabled = addedCandidates.length === 0;
    }
    
    goToStep(3);
});

// Step 3: Analyze
document.getElementById('btn-back-2').addEventListener('click', () => {
    goToStep(2);
});

document.getElementById('btn-analyze').addEventListener('click', async () => {
    goToStep(4);
    
    document.getElementById('analysis-loading').classList.add('active');
    document.getElementById('analysis-results').style.display = 'none';
    startAiConsole();
    
    try {
        // Analyze all candidates
        const analysisPromises = addedCandidates.map(candidate => 
            apiCall(`/api/candidates/${candidate.id}/analyze?job_description_id=${encodeURIComponent(selectedJobDescription.id)}`, { method: 'POST' })
        );
        
        await Promise.all(analysisPromises);
        
        // Get updated candidates with analysis
        const updatedCandidates = await Promise.all(
            addedCandidates.map(candidate => apiCall(`/api/candidates/${candidate.id}`))
        );
        
        analysisResults = updatedCandidates;
        
        // Display results
        displayAnalysisResults();
        
        showToast('Analysis completed successfully!');
        
    } catch (error) {
        showToast('Failed to analyze candidates: ' + error.message, 'danger');
        goToStep(3);
    } finally {
        document.getElementById('analysis-loading').classList.remove('active');
        stopAiConsole();
    }
});

const analyzeSelectedButton = document.getElementById('btn-analyze-selected');
if (analyzeSelectedButton) {
    analyzeSelectedButton.addEventListener('click', async () => {
        goToStep(4);
        document.getElementById('analysis-loading').classList.add('active');
        document.getElementById('analysis-results').style.display = 'none';
        startAiConsole();

        try {
            const selectedIds = Array.from(document.querySelectorAll('.analyze-checkbox'))
                .filter(box => box.checked)
                .map(box => parseInt(box.dataset.candidateId, 10));
            const selectedCandidates = addedCandidates.filter(candidate => selectedIds.includes(candidate.id));
            if (selectedCandidates.length === 0) {
                throw new Error('No candidates selected');
            }
            const analysisPromises = selectedCandidates.map(candidate =>
                apiCall(`/api/candidates/${candidate.id}/analyze?job_description_id=${encodeURIComponent(selectedJobDescription.id)}`, { method: 'POST' })
            );
            await Promise.all(analysisPromises);
            const updatedCandidates = await Promise.all(
                selectedCandidates.map(candidate => apiCall(`/api/candidates/${candidate.id}`))
            );
            analysisResults = updatedCandidates;
            displayAnalysisResults();
            showToast('Selected candidates analyzed successfully!');
        } catch (error) {
            showToast('Failed to analyze selected candidates: ' + error.message, 'danger');
            goToStep(3);
        } finally {
            document.getElementById('analysis-loading').classList.remove('active');
            stopAiConsole();
        }
    });
}

function displayAnalysisResults() {
    if (!analysisResults || analysisResults.length === 0) {
        return;
    }
    
    // Update stats
    let strongHire = 0;
    let borderline = 0;
    let reject = 0;
    
    analysisResults.forEach(candidate => {
        if (candidate.analysis) {
            const decision = candidate.analysis.decision;
            if (decision === 'strong_hire') {
                strongHire++;
            } else if (decision === 'borderline') {
                borderline++;
            } else if (decision === 'reject') {
                reject++;
            }
        }
    });
    
    document.getElementById('stat-total').textContent = analysisResults.length;
    document.getElementById('stat-strong-hire').textContent = strongHire;
    document.getElementById('stat-borderline').textContent = borderline;
    document.getElementById('stat-reject').textContent = reject;
    
    // Display summary
    displaySummaryResults();
    
    // Display ranking
    displayRankingResults();
    
    // Display detailed analysis
    displayDetailedResults();

    const downloadAllButton = document.getElementById('btn-download-all-pdfs');
    if (downloadAllButton) {
        downloadAllButton.disabled = analysisResults.length === 0;
    }
    
    document.getElementById('analysis-results').style.display = 'block';
}

function displaySummaryResults() {
    const container = document.getElementById('summary-results');
    
    let html = '<div class="row">';
    analysisResults.forEach(result => {
        const candidate = result.candidate || result;
        const analysis = result.analysis;
        const decision = analysis ? analysis.decision : 'PENDING';
        const badgeClass = getBadgeClass(decision);
        const score = formatScore(analysis ? analysis.final_score : null);
        
        html += `
            <div class="col-md-6 mb-3">
                <div class="card">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-center">
                            <h6 class="mb-1">${candidate.name || 'Unknown'}</h6>
                            <span class="badge ${badgeClass}">${decision}</span>
                        </div>
                        <p class="mb-0 text-muted">Score: ${score}</p>
                    </div>
                </div>
            </div>
        `;
    });
    html += '</div>';
    
    container.innerHTML = html;
}

function displayRankingResults() {
    const container = document.getElementById('ranking-results');
    
    // Sort candidates by score
    const sortedCandidates = [...analysisResults].sort((a, b) => {
        const analysisA = a.analysis || {};
        const analysisB = b.analysis || {};
        const scoreA = analysisA.final_score || 0;
        const scoreB = analysisB.final_score || 0;
        return scoreB - scoreA;
    });
    
    let html = '<div class="list-group">';
    sortedCandidates.forEach((result, index) => {
        const candidate = result.candidate || result;
        const analysis = result.analysis;
        const decision = analysis ? analysis.decision : 'PENDING';
        const badgeClass = getBadgeClass(decision);
        const score = formatScore(analysis ? analysis.final_score : null);
        const rank = index + 1;
        
        html += `
            <div class="list-group-item">
                <div class="d-flex w-100 justify-content-between align-items-center">
                    <div class="d-flex align-items-center">
                        <span class="badge bg-primary me-3">#${rank}</span>
                        <h6 class="mb-1">${candidate.name || 'Unknown'}</h6>
                    </div>
                    <span class="badge ${badgeClass}">${decision}</span>
                </div>
                <small class="text-muted">Score: ${score}</small>
            </div>
        `;
    });
    html += '</div>';
    
    container.innerHTML = html;
}

function displayDetailedResults() {
    const container = document.getElementById('detailed-results');
    
    let html = '';
    const candidateIds = [];
    analysisResults.forEach(result => {
        const candidate = result.candidate || result;
        const candidateId = candidate && candidate.id ? candidate.id : null;
        const analysis = result.analysis;
        const decision = analysis ? analysis.decision : 'PENDING';
        const badgeClass = getBadgeClass(decision);
        const score = formatScore(analysis ? analysis.final_score : null);
        const scoreClass = getScoreClass(typeof analysis?.final_score === 'number' ? analysis.final_score : 0);
        const downloadButton = candidateId
            ? `<button class="btn btn-sm btn-light" onclick="downloadCandidatePdf(${candidateId})">
                    <i class="bi bi-download me-1"></i>PDF
               </button>`
            : '';
        const interviewUrl = candidateId
            ? `${API_BASE_URL}/static/interview.html?candidate_id=${candidateId}`
            : '';
        const interviewLink = candidateId
            ? `<a class="btn btn-sm btn-outline-primary" href="${interviewUrl}" target="_blank">
                    <i class="bi bi-mic me-1"></i>Interview Link
               </a>`
            : '';
        const copyLinkButton = candidateId
            ? `<button class="btn btn-sm btn-outline-secondary" onclick="copyInterviewLink('${interviewUrl}')">
                    <i class="bi bi-clipboard me-1"></i>Copy Link
               </button>`
            : '';
        const reviewLink = candidateId
            ? `<a class="btn btn-sm btn-outline-success" href="${API_BASE_URL}/static/interview_review.html?candidate_id=${candidateId}" target="_blank">
                    <i class="bi bi-card-checklist me-1"></i>Review
               </a>`
            : '';
        if (candidateId) {
            candidateIds.push(candidateId);
        }
        
        html += `
            <div class="card mb-4">
                <div class="card-header">
                        <div class="d-flex justify-content-between align-items-center">
                            <h6 class="mb-0">${candidate.name || 'Unknown'}</h6>
                            <div class="d-flex align-items-center gap-2">
                                ${interviewLink}
                                ${copyLinkButton}
                                ${reviewLink}
                                ${downloadButton}
                                <span class="badge ${badgeClass}">${decision}</span>
                            </div>
                        </div>
                </div>
                <div class="card-body">
        `;
        
        if (analysis) {
            // Score and Decision Summary
            html += `
                    <div class="row mb-4">
                        <div class="col-md-4 text-center">
                            <div class="score-circle ${scoreClass}">${score}</div>
                            <p class="text-muted mb-0 mt-2">Total Score</p>
                        </div>
                        <div class="col-md-8">
                            <h5 class="mb-2">Score: ${score}/100, Decision: ${analysis.decision}</h5>
                            <div class="row">
                                <div class="col-md-6">
                                    <p class="mb-1"><strong>Risk Level:</strong> <span class="badge bg-${getRiskLevelClass(analysis.risk_level)}">${analysis.risk_level || 'N/A'}</span></p>
                                    <p class="mb-1"><strong>Seniority:</strong> ${analysis.seniority || 'N/A'}</p>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Individual Score Metrics -->
                    <h6 class="mb-3">Score Breakdown</h6>
                    <div class="row mb-4">
                        <div class="col-md-6 mb-3">
                            <div class="metric-card skill-match">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span class="metric-label">Skill Match Score</span>
                                    <span class="metric-value">${analysis.skill_match_score || 0}</span>
                                </div>
                                <div class="metric-bar">
                                    <div class="metric-bar-fill bg-success" style="width: ${analysis.skill_match_score || 0}%"></div>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-6 mb-3">
                            <div class="metric-card experience">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span class="metric-label">Experience Score</span>
                                    <span class="metric-value">${analysis.experience_score || 0}</span>
                                </div>
                                <div class="metric-bar">
                                    <div class="metric-bar-fill bg-info" style="width: ${analysis.experience_score || 0}%"></div>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-6 mb-3">
                            <div class="metric-card domain">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span class="metric-label">Domain Score</span>
                                    <span class="metric-value">${analysis.domain_score || 0}</span>
                                </div>
                                <div class="metric-bar">
                                    <div class="metric-bar-fill bg-secondary" style="width: ${analysis.domain_score || 0}%"></div>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-6 mb-3">
                            <div class="metric-card project-complexity">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span class="metric-label">Project Complexity Score</span>
                                    <span class="metric-value">${analysis.project_complexity_score || 0}</span>
                                </div>
                                <div class="metric-bar">
                                    <div class="metric-bar-fill bg-warning" style="width: ${analysis.project_complexity_score || 0}%"></div>
                                </div>
                            </div>
                        </div>
                        <div class="col-md-6 mb-3">
                            <div class="metric-card soft-skills">
                                <div class="d-flex justify-content-between align-items-center">
                                    <span class="metric-label">Soft Skills Score</span>
                                    <span class="metric-value">${analysis.soft_skills_score || 0}</span>
                                </div>
                                <div class="metric-bar">
                                    <div class="metric-bar-fill bg-primary" style="width: ${analysis.soft_skills_score || 0}%"></div>
                                </div>
                            </div>
                        </div>
                    </div>
                    
                    <!-- Strengths -->
                    ${analysis.strengths && analysis.strengths.length > 0 ? `
                    <div class="mb-4">
                        <h6 class="mb-2"><i class="bi bi-check-circle-fill text-success me-2"></i>Strengths</h6>
                        <ul class="list-unstyled">
                            ${analysis.strengths.map(strength => `<li class="strength-item mb-1"><i class="bi bi-check me-2"></i>${strength}</li>`).join('')}
                        </ul>
                    </div>
                    ` : ''}
                    
                    <!-- Weaknesses -->
                    ${analysis.weaknesses && analysis.weaknesses.length > 0 ? `
                    <div class="mb-4">
                        <h6 class="mb-2"><i class="bi bi-exclamation-circle-fill text-warning me-2"></i>Weaknesses</h6>
                        <ul class="list-unstyled">
                            ${analysis.weaknesses.map(weakness => `<li class="weakness-item mb-1"><i class="bi bi-dash me-2"></i>${weakness}</li>`).join('')}
                        </ul>
                    </div>
                    ` : ''}
                    
                    <!-- Risks -->
                    ${analysis.risks && analysis.risks.length > 0 ? `
                    <div class="mb-4">
                        <h6 class="mb-2"><i class="bi bi-exclamation-triangle-fill text-danger me-2"></i>Risks</h6>
                        <ul class="list-unstyled">
                            ${analysis.risks.map(risk => `<li class="risk-item mb-1"><i class="bi bi-exclamation-triangle me-2"></i>${risk}</li>`).join('')}
                        </ul>
                    </div>
                    ` : ''}
                    
                    <!-- Interview Strategy -->
                    <div class="interview-strategy-card ${decision === 'strong_hire' || decision === 'borderline' ? 'pass' : 'fail'}">
                        <h6 class="mb-3">
                            <i class="bi bi-${decision === 'strong_hire' || decision === 'borderline' ? 'check-circle' : 'x-circle'} me-2"></i>
                            ${decision === 'strong_hire' || decision === 'borderline' ? '✅ PASS' : '❌ FAIL'}: Interview Strategy for ${candidate.name || 'Unknown'}
                        </h6>
                        <div class="row mb-3">
                            <div class="col-md-6">
                                <p class="mb-1"><strong>Risk Level:</strong> <span class="badge bg-${getRiskLevelClass(analysis.risk_level)}">${analysis.risk_level || 'N/A'}</span></p>
                            </div>
                        </div>
                        
                        <!-- Question Counts -->
                        <div class="row mb-3">
                            <div class="col-md-4">
                                <p class="mb-1"><span class="question-badge">Technical</span> ${analysis.technical_questions ? analysis.technical_questions.length : 0} Questions</p>
                            </div>
                            <div class="col-md-4">
                                <p class="mb-1"><span class="question-badge" style="background: var(--secondary-color);">System Design</span> ${analysis.system_design_questions ? analysis.system_design_questions.length : 0} Questions</p>
                            </div>
                            <div class="col-md-4">
                                <p class="mb-1"><span class="question-badge" style="background: var(--success-color);">Behavioral</span> ${analysis.behavioral_questions ? analysis.behavioral_questions.length : 0} Questions</p>
                            </div>
                        </div>
                        
                        <!-- Focus Areas -->
                        ${analysis.interview_focus_areas && analysis.interview_focus_areas.length > 0 ? `
                        <div class="mb-3">
                            <p class="mb-2"><strong>Focus Areas:</strong></p>
                            <div>
                                ${analysis.interview_focus_areas.map(area => `<span class="focus-area-tag">${area}</span>`).join('')}
                            </div>
                        </div>
                        ` : ''}
                        
                        <!-- Technical Questions -->
                        ${analysis.technical_questions && analysis.technical_questions.length > 0 ? `
                        <div class="mb-3">
                            <p class="mb-2"><strong>Technical Questions:</strong></p>
                            <ol class="mb-0">
                                ${analysis.technical_questions.map(question => `<li>${question}</li>`).join('')}
                            </ol>
                        </div>
                        ` : ''}
                        
                        <!-- System Design Questions -->
                        ${analysis.system_design_questions && analysis.system_design_questions.length > 0 ? `
                        <div class="mb-3">
                            <p class="mb-2"><strong>System Design Questions:</strong></p>
                            <ol class="mb-0">
                                ${analysis.system_design_questions.map(question => `<li>${question}</li>`).join('')}
                            </ol>
                        </div>
                        ` : ''}
                        
                        <!-- Behavioral Questions -->
                        ${analysis.behavioral_questions && analysis.behavioral_questions.length > 0 ? `
                        <div class="mb-0">
                            <p class="mb-2"><strong>Behavioral Questions:</strong></p>
                            <ol class="mb-0">
                                ${analysis.behavioral_questions.map(question => `<li>${question}</li>`).join('')}
                            </ol>
                        </div>
                        ` : ''}
                    </div>
            `;
        } else {
            html += `
                    <p class="text-muted">No analysis data available</p>
            `;
        }
        
        html += `
                </div>
            </div>
        `;
    });
    
    container.innerHTML = html;
    if (candidateIds.length > 0) {
        container.dataset.candidateIds = candidateIds.join(',');
    } else {
        delete container.dataset.candidateIds;
    }
}

// Helper Functions
function getBadgeClass(decision) {
    switch (decision) {
        case 'strong_hire':
            return 'badge-strong-hire';
        case 'borderline':
            return 'badge-borderline';
        case 'reject':
            return 'badge-reject';
        default:
            return 'badge-pending';
    }
}

function getScoreClass(score) {
    if (score >= 70) {
        return 'score-high';
    } else if (score >= 50) {
        return 'score-medium';
    } else {
        return 'score-low';
    }
}

function getRiskLevelClass(riskLevel) {
    switch (riskLevel) {
        case 'low':
            return 'success';
        case 'medium':
            return 'warning';
        case 'high':
            return 'danger';
        default:
            return 'secondary';
    }
}

// Report Tab Navigation
function showReportTab(tabName) {
    // Hide all report sections
    document.querySelectorAll('.report-section').forEach(section => {
        section.classList.remove('active');
    });
    
    // Remove active class from all nav links
    document.querySelectorAll('#reportTabs .nav-link').forEach(link => {
        link.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(`${tabName}-tab`).classList.add('active');
    
    // Add active class to clicked link
    event.target.classList.add('active');
}

function startNewAnalysis() {
    // Reset state
    currentStep = 1;
    selectedJobDescription = null;
    addedCandidates = [];
    analysisResults = null;
    outlookSelection.clear();
    
    // Reset UI
    document.getElementById('selected-jd').value = '';
    document.getElementById('btn-step-1').disabled = true;
    document.getElementById('btn-step-2').disabled = true;
    document.getElementById('btn-analyze').disabled = true;
    const candidatesList = document.getElementById('jd-candidates-list')
        || document.getElementById('candidates-list');
    if (candidatesList) {
        candidatesList.innerHTML = '<p class="text-muted">Select a job description to load candidates.</p>';
    }
    
    // Reset step indicators
    for (let i = 1; i <= 4; i++) {
        document.getElementById(`step-${i}`).classList.remove('active', 'completed');
    }
    
    // Go to step 1
    goToStep(1);
    
    showToast('Ready to start a new analysis!');
}

// Start Over
document.getElementById('btn-start-over').addEventListener('click', startNewAnalysis);

const startOverTop = document.getElementById('btn-start-over-top');
if (startOverTop) {
    startOverTop.addEventListener('click', startNewAnalysis);
}

// Main Tab Navigation
function showMainTab(tabName) {
    // Hide all tab contents
    document.querySelectorAll('.tab-content').forEach(tab => {
        tab.style.display = 'none';
    });
    
    // Remove active class from all nav links
    document.querySelectorAll('#mainTabs .nav-link').forEach(link => {
        link.classList.remove('active');
    });
    
    // Show selected tab
    document.getElementById(`${tabName}-tab`).style.display = 'block';
    
    // Add active class to clicked link
    event.target.classList.add('active');
    
    // Load job descriptions if switching to job-descriptions tab
    if (tabName === 'job-descriptions') {
        loadJobDescriptionsList();
    }

    if (tabName === 'outlook-candidates') {
        loadOutlookCandidates(true);
    }

    if (tabName === 'interview-reviews') {
        loadInterviewSummaries();
    }

    if (tabName === 'candidates-management') {
        loadCandidateManagementJds();
        loadCandidatesManagement();
    }

    if (tabName === 'workflow') {
        loadCandidateManagementJds();
    }
}

function showDeviceCodeBanner(message) {
    const banner = document.getElementById('device-code-banner');
    if (!banner) {
        return;
    }
    banner.textContent = message;
    banner.classList.remove('d-none');
}

function hideDeviceCodeBanner() {
    const banner = document.getElementById('device-code-banner');
    if (!banner) {
        return;
    }
    banner.classList.add('d-none');
    banner.textContent = '';
}

// Outlook Candidates
async function loadOutlookCandidates(includeLinked = false) {
    try {
        const query = includeLinked ? '?include_linked=true' : '?include_linked=false';
        const candidates = await apiCall(`/api/outlook/candidates${query}`);
        outlookCandidates = candidates;
        renderOutlookCandidatesList(candidates);
        renderOutlookCandidatesSelection(candidates);
    } catch (error) {
        console.error('Failed to load Outlook candidates:', error);
    }
}

async function syncOutlookCandidates() {
    try {
        const result = await apiCall('/api/outlook/imap/ingest', { method: 'POST' });
        const errorCount = result.errors ? result.errors.length : 0;
        const message = `IMAP sync complete: ${result.created_candidates} new, ${result.skipped_candidates} skipped.`;
        showToast(errorCount > 0 ? `${message} (${errorCount} errors)` : message, errorCount > 0 ? 'warning' : 'success');
        await loadOutlookCandidates(true);
    } catch (error) {
        showToast('Failed to sync IMAP: ' + error.message, 'danger');
    }
}

function renderOutlookCandidatesList(candidates) {
    const container = document.getElementById('outlook-candidates-list');
    if (!container) {
        return;
    }

    if (!candidates || candidates.length === 0) {
        container.innerHTML = '<p class="text-muted">No Outlook candidates loaded</p>';
        return;
    }

    let html = `
        <div class="table-responsive">
            <table class="table outlook-table">
                <thead>
                    <tr>
                        <th>Name</th>
                        <th>Tech Stack</th>
                        <th>Category</th>
                        <th>Seniority</th>
                        <th>Status</th>
                        <th>Resume</th>
                    </tr>
                </thead>
                <tbody>
    `;

    candidates.forEach(candidate => {
        const name = candidate.candidate_name || 'Unknown';
        const techStack = candidate.tech_stack && candidate.tech_stack.length
            ? candidate.tech_stack.map(skill => `<span class="outlook-pill">${skill}</span>`).join('')
            : '<span class="text-muted">N/A</span>';
        const status = candidate.linked_candidate_id ? '<span class="badge bg-success">Imported</span>' : '<span class="badge bg-secondary">New</span>';
        const resumeLink = `<a class="btn btn-sm btn-outline-primary" href="${API_BASE_URL}/api/outlook/candidates/${candidate.id}/resume" target="_blank">Download</a>`;

        html += `
            <tr>
                <td>${name}</td>
                <td>${techStack}</td>
                <td>${candidate.job_category || 'N/A'}</td>
                <td>${candidate.seniority || 'N/A'}</td>
                <td>${status}</td>
                <td>${resumeLink}</td>
            </tr>
        `;
    });

    html += `
                </tbody>
            </table>
        </div>
    `;

    container.innerHTML = html;
}

function renderOutlookCandidatesSelection(candidates) {
    const container = document.getElementById('outlook-candidates-selection');
    if (!container) {
        return;
    }

    const available = (candidates || []).filter(candidate => !candidate.linked_candidate_id);
    const availableIds = new Set(available.map(candidate => candidate.id));
    outlookSelection.forEach(id => {
        if (!availableIds.has(id)) {
            outlookSelection.delete(id);
        }
    });
    if (available.length === 0) {
        container.innerHTML = '<p class="text-muted">No new Outlook candidates available</p>';
        document.getElementById('btn-add-outlook').disabled = true;
        return;
    }

    let html = `
        <div class="table-responsive">
            <table class="table outlook-table">
                <thead>
                    <tr>
                        <th></th>
                        <th>Name</th>
                        <th>Tech Stack</th>
                        <th>Category</th>
                        <th>Resume</th>
                    </tr>
                </thead>
                <tbody>
    `;

    available.forEach(candidate => {
        const checked = outlookSelection.has(candidate.id) ? 'checked' : '';
        const techStack = candidate.tech_stack && candidate.tech_stack.length
            ? candidate.tech_stack.join(', ')
            : 'N/A';
        html += `
            <tr>
                <td>
                    <input type="checkbox" class="form-check-input" data-outlook-id="${candidate.id}" ${checked}>
                </td>
                <td>${candidate.candidate_name || 'Unknown'}</td>
                <td>${techStack}</td>
                <td>${candidate.job_category || 'N/A'}</td>
                <td>
                    <a class="btn btn-sm btn-outline-primary" href="${API_BASE_URL}/api/outlook/candidates/${candidate.id}/resume" target="_blank">Download</a>
                </td>
            </tr>
        `;
    });

    html += `
                </tbody>
            </table>
        </div>
    `;

    container.innerHTML = html;

    container.querySelectorAll('input[type="checkbox"]').forEach(checkbox => {
        checkbox.addEventListener('change', (event) => {
            const id = parseInt(event.target.dataset.outlookId, 10);
            if (event.target.checked) {
                outlookSelection.add(id);
            } else {
                outlookSelection.delete(id);
            }
            document.getElementById('btn-add-outlook').disabled = outlookSelection.size === 0;
        });
    });

    document.getElementById('btn-add-outlook').disabled = outlookSelection.size === 0;
}

const addOutlookButton = document.getElementById('btn-add-outlook');
if (addOutlookButton) {
    addOutlookButton.addEventListener('click', async () => {
        if (!selectedJobDescription) {
            showToast('Please select a job description first', 'warning');
            return;
        }

        if (outlookSelection.size === 0) {
            showToast('Select at least one Outlook candidate', 'warning');
            return;
        }

        try {
            const payload = {
                job_description_id: selectedJobDescription.id,
                outlook_candidate_ids: Array.from(outlookSelection),
            };
            const candidates = await apiCall('/api/outlook/attach', {
                method: 'POST',
                body: JSON.stringify(payload),
            });
            candidates.forEach(candidate => addedCandidates.push(candidate));
            outlookSelection.clear();
            document.getElementById('btn-step-2').disabled = addedCandidates.length === 0;
            showToast('Outlook candidates added to analysis!');
            await loadOutlookCandidates(true);
        } catch (error) {
            showToast('Failed to add Outlook candidates: ' + error.message, 'danger');
        }
    });
}

// Job Descriptions Management
async function loadJobDescriptionsList() {
    try {
        const jds = await apiCall('/api/job-descriptions');
        const container = document.getElementById('jd-list-container');
        
        if (jds.length === 0) {
            container.innerHTML = `
                <div class="text-center py-5">
                    <i class="bi bi-briefcase text-muted" style="font-size: 3rem;"></i>
                    <p class="text-muted mt-3">No job descriptions found</p>
                    <button class="btn btn-primary" onclick="showCreateJdModal()">
                        <i class="bi bi-plus me-1"></i>Create First Job Description
                    </button>
                </div>
            `;
            return;
        }
        
        let html = '<div class="row">';
        jds.forEach(jd => {
            html += `
                <div class="col-md-6 mb-3">
                    <div class="card">
                        <div class="card-body">
                            <div class="d-flex justify-content-between align-items-start mb-2">
                                <h6 class="mb-1">${jd.title}</h6>
                                <div class="dropdown">
                                    <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button" data-bs-toggle="dropdown">
                                        <i class="bi bi-three-dots"></i>
                                    </button>
                                    <ul class="dropdown-menu">
                                        <li>
                                            <a class="dropdown-item" href="#" onclick="viewJobDescription(${jd.id})">
                                                <i class="bi bi-eye me-2"></i>View
                                            </a>
                                        </li>
                                        <li>
                                            <a class="dropdown-item" href="#" onclick="editJobDescription(${jd.id})">
                                                <i class="bi bi-pencil me-2"></i>Edit
                                            </a>
                                        </li>
                                        <li>
                                            <hr class="dropdown-divider">
                                        </li>
                                        <li>
                                            <a class="dropdown-item text-danger" href="#" onclick="deleteJobDescription(${jd.id})">
                                                <i class="bi bi-trash me-2"></i>Delete
                                            </a>
                                        </li>
                                    </ul>
                                </div>
                            </div>
                            <p class="text-muted mb-2" style="font-size: 0.875rem;">${jd.description.substring(0, 150)}...</p>
                            <div class="mb-2">
                                ${jd.required_skills && jd.required_skills.length > 0 ?
                                    jd.required_skills.map(skill => `<span class="badge bg-light text-dark me-1">${skill}</span>`).join('') :
                                    '<span class="text-muted">No skills specified</span>'
                                }
                            </div>
                            <div class="d-flex justify-content-between align-items-center">
                                <small class="text-muted">
                                    <i class="bi bi-clock me-1"></i>${jd.min_experience_years}+ years
                                    ${jd.domain ? `<span class="ms-2"><i class="bi bi-tag me-1"></i>${jd.domain}</span>` : ''}
                                </small>
                                <small class="text-muted">
                                    ${jd.created_at ? new Date(jd.created_at).toLocaleDateString() : ''}
                                </small>
                            </div>
                        </div>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        
        container.innerHTML = html;
        
    } catch (error) {
        console.error('Failed to load job descriptions:', error);
        document.getElementById('jd-list-container').innerHTML = `
            <div class="alert alert-danger">
                <i class="bi bi-exclamation-triangle me-2"></i>
                Failed to load job descriptions: ${error.message}
            </div>
        `;
    }
}

function showCreateJdModal() {
    document.getElementById('jdModalTitle').textContent = 'Create Job Description';
    document.getElementById('jd-modal-id').value = '';
    document.getElementById('jd-modal-form').reset();
    
    const modal = new bootstrap.Modal(document.getElementById('jdModal'));
    modal.show();
}

async function editJobDescription(jdId) {
    try {
        const jd = await apiCall(`/api/job-descriptions/${jdId}`);
        
        document.getElementById('jdModalTitle').textContent = 'Edit Job Description';
        document.getElementById('jd-modal-id').value = jd.id;
        document.getElementById('jd-modal-title').value = jd.title;
        document.getElementById('jd-modal-description').value = jd.description;
        document.getElementById('jd-modal-skills').value = jd.required_skills ? jd.required_skills.join(', ') : '';
        document.getElementById('jd-modal-experience').value = jd.min_experience_years || 0;
        document.getElementById('jd-modal-domain').value = jd.domain || '';
        
        const modal = new bootstrap.Modal(document.getElementById('jdModal'));
        modal.show();
        
    } catch (error) {
        showToast('Failed to load job description: ' + error.message, 'danger');
    }
}

async function saveJobDescription() {
    const jdId = document.getElementById('jd-modal-id').value;
    const title = document.getElementById('jd-modal-title').value;
    const description = document.getElementById('jd-modal-description').value;
    const skills = document.getElementById('jd-modal-skills').value.split(',').map(s => s.trim()).filter(s => s);
    const experience = parseFloat(document.getElementById('jd-modal-experience').value) || 0;
    const domain = document.getElementById('jd-modal-domain').value;
    
    if (!title || !description) {
        showToast('Please fill in all required fields', 'warning');
        return;
    }
    
    try {
        if (jdId) {
            // Update existing
            await apiCall(`/api/job-descriptions/${jdId}`, {
                method: 'PUT',
                body: JSON.stringify({
                    title,
                    description,
                    required_skills: skills,
                    min_experience_years: experience,
                    domain
                })
            });
            showToast('Job description updated successfully!');
        } else {
            // Create new
            await apiCall('/api/job-descriptions', {
                method: 'POST',
                body: JSON.stringify({
                    title,
                    description,
                    required_skills: skills,
                    min_experience_years: experience,
                    domain
                })
            });
            showToast('Job description created successfully!');
        }
        
        // Close modal and reload list
        const modal = bootstrap.Modal.getInstance(document.getElementById('jdModal'));
        modal.hide();
        
        loadJobDescriptionsList();
        loadJobDescriptions(); // Also update the dropdown in workflow
        
    } catch (error) {
        showToast('Failed to save job description: ' + error.message, 'danger');
    }
}

async function viewJobDescription(jdId) {
    try {
        const jd = await apiCall(`/api/job-descriptions/${jdId}`);
        
        document.getElementById('viewJdModalTitle').textContent = jd.title;
        
        let html = `
            <div class="mb-3">
                <h6>Description</h6>
                <p class="text-muted">${jd.description}</p>
            </div>
            <div class="mb-3">
                <h6>Required Skills</h6>
                <div>
                    ${jd.required_skills && jd.required_skills.length > 0 ?
                        jd.required_skills.map(skill => `<span class="badge bg-primary me-1">${skill}</span>`).join('') :
                        '<span class="text-muted">No skills specified</span>'
                    }
                </div>
            </div>
            <div class="row mb-3">
                <div class="col-md-6">
                    <h6>Minimum Experience</h6>
                    <p class="text-muted">${jd.min_experience_years}+ years</p>
                </div>
                <div class="col-md-6">
                    <h6>Domain</h6>
                    <p class="text-muted">${jd.domain || 'Not specified'}</p>
                </div>
            </div>
            <div class="row">
                <div class="col-md-6">
                    <small class="text-muted">
                        <i class="bi bi-calendar me-1"></i>Created: ${jd.created_at ? new Date(jd.created_at).toLocaleString() : 'N/A'}
                    </small>
                </div>
                <div class="col-md-6">
                    <small class="text-muted">
                        <i class="bi bi-clock me-1"></i>Updated: ${jd.updated_at ? new Date(jd.updated_at).toLocaleString() : 'N/A'}
                    </small>
                </div>
            </div>
        `;
        
        document.getElementById('view-jd-content').innerHTML = html;
        
        const modal = new bootstrap.Modal(document.getElementById('viewJdModal'));
        modal.show();
        
    } catch (error) {
        showToast('Failed to load job description: ' + error.message, 'danger');
    }
}

async function deleteJobDescription(jdId) {
    if (!confirm('Are you sure you want to delete this job description? This action cannot be undone.')) {
        return;
    }
    
    try {
        const url = `${API_BASE_URL}/api/job-descriptions/${jdId}`;
        const response = await fetch(url, { method: 'DELETE' });
        
        if (!response.ok) {
            const error = await response.json();
            throw new Error(error.detail || 'Delete failed');
        }
        
        showToast('Job description deleted successfully!');
        loadJobDescriptionsList();
        loadJobDescriptions(); // Also update the dropdown in workflow
    } catch (error) {
        showToast('Failed to delete job description: ' + error.message, 'danger');
    }
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    loadJobDescriptions();
    loadOutlookCandidates(true);
    loadCandidateManagementJds();
});

const refreshJdCandidatesButton = document.getElementById('btn-refresh-jd-candidates');
if (refreshJdCandidatesButton) {
    refreshJdCandidatesButton.addEventListener('click', loadCandidatesForSelectedJd);
}

const step2FilterButton = document.getElementById('step2-filter-apply');
if (step2FilterButton) {
    step2FilterButton.addEventListener('click', loadCandidatesForSelectedJd);
}

// Candidate Management
async function loadCandidateManagementJds() {
    try {
        const jds = await apiCall('/api/job-descriptions');
        const selects = [
            document.getElementById('cm-jd'),
            document.getElementById('cm-folder-jd'),
            document.getElementById('cm-filter-jd'),
            document.getElementById('cm-bulk-link-jd'),
            document.getElementById('step2-filter-jd'),
        ];
        selects.forEach(select => {
            if (!select) return;
            const firstOption = select.id === 'cm-filter-jd'
                ? '<option value="">All</option>'
                : select.id === 'cm-bulk-link-jd'
                    ? '<option value="">Link selected to JD...</option>'
                    : select.id === 'step2-filter-jd'
                        ? '<option value="">All JDs</option>'
                    : '<option value="">No JD selected</option>';
            select.innerHTML = firstOption;
            jds.forEach(jd => {
                select.innerHTML += `<option value="${jd.id}">${jd.title}</option>`;
            });
        });
    } catch (error) {
        console.error('Failed to load JDs for candidate management:', error);
    }
}

async function loadCandidatesManagement() {
    const container = document.getElementById('cm-candidate-list');
    if (!container) {
        return;
    }
    container.innerHTML = '<p class="text-muted">Loading candidates...</p>';

    const name = document.getElementById('cm-filter-name')?.value || '';
    const skills = document.getElementById('cm-filter-skills')?.value || '';
    const minExp = document.getElementById('cm-filter-min-exp')?.value || '';
    const maxExp = document.getElementById('cm-filter-max-exp')?.value || '';
    const jdId = document.getElementById('cm-filter-jd')?.value || '';

    const params = new URLSearchParams();
    if (name) params.append('name', name);
    if (skills) params.append('skills', skills);
    if (minExp) params.append('min_experience', minExp);
    if (maxExp) params.append('max_experience', maxExp);
    if (jdId) params.append('job_description_id', jdId);

    try {
        const candidates = await apiCall(`/api/candidates/summary?${params.toString()}`);
        if (!candidates || candidates.length === 0) {
            container.innerHTML = '<p class="text-muted">No candidates found.</p>';
            return;
        }
        let html = '<div class="list-group">';
        candidates.forEach(item => {
            const candidate = item.candidate || {};
            const profile = item.profile || {};
            const jobLinks = item.job_links || [];
            const invalidBadge = profile.invalid_resume
                ? '<span class="badge bg-danger ms-2">Invalid Resume</span>'
                : '';
            const headline = profile.headline || profile.current_role || 'Role not specified';
            const exp = profile.total_experience_years != null ? `${profile.total_experience_years} yrs` : 'Exp N/A';
            const linkBadges = jobLinks.length
                ? jobLinks.map(link => `<span class="badge bg-light text-dark me-1">${link.title}</span>`).join('')
                : '<span class="text-muted">No JD linked</span>';
            const resumeLink = candidate.resume_file_path
                ? `<a class="btn btn-sm btn-outline-primary" href="${API_BASE_URL}/api/candidates/${candidate.id}/resume" target="_blank">Resume</a>`
                : '';
            const reviewLink = `<a class="btn btn-sm btn-outline-success" href="${API_BASE_URL}/static/interview_review.html?candidate_id=${candidate.id}" target="_blank">Review</a>`;
            html += `
                <div class="list-group-item">
                    <div class="d-flex justify-content-between align-items-center">
                        <div>
                            <div class="d-flex align-items-center gap-2">
                                <input class="form-check-input cm-select" type="checkbox" data-candidate-id="${candidate.id}">
                            <h6 class="mb-1">${formatCandidateName(candidate.name)}${invalidBadge}</h6>
                            </div>
                            <small class="text-muted">${headline} • ${exp}</small>
                            <div class="mt-1">${linkBadges}</div>
                        </div>
                        <div class="d-flex gap-2">
                            ${resumeLink}
                            ${reviewLink}
                            <button class="btn btn-sm btn-outline-secondary" onclick="viewCandidateDetail(${candidate.id})">View</button>
                            <button class="btn btn-sm btn-danger" onclick="deleteCandidate(${candidate.id})">Delete</button>
                        </div>
                    </div>
                </div>
            `;
        });
        html += '</div>';
        container.innerHTML = html;
        wireCandidateSelection();
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger">Failed to load candidates: ${error.message}</div>`;
    }
}

function wireCandidateSelection() {
    const selectAll = document.getElementById('cm-select-all');
    const checkboxes = document.querySelectorAll('.cm-select');
    if (selectAll) {
        selectAll.checked = false;
        selectAll.addEventListener('change', () => {
            checkboxes.forEach(box => {
                box.checked = selectAll.checked;
            });
        });
    }
}

async function viewCandidateDetail(candidateId) {
    try {
        const detail = await apiCall(`/api/candidates/${candidateId}/detail`);
        const candidate = detail.candidate || {};
        const profile = detail.profile || {};
        const history = detail.analysis_history || [];
        const resumeLink = candidate.resume_file_path
            ? `<a class="btn btn-sm btn-outline-primary" href="${API_BASE_URL}/api/candidates/${candidate.id}/resume" target="_blank">Download Resume</a>`
            : '';
        let historyHtml = '';
        if (history.length) {
            historyHtml = history.map(run => {
                const interviewUrl = run.candidate_id
                    ? `${API_BASE_URL}/static/interview.html?candidate_id=${run.candidate_id}${run.job_description_id ? `&job_description_id=${run.job_description_id}` : ''}`
                    : '';
                const copyLinkButton = interviewUrl
                    ? `<button class="btn btn-sm btn-outline-secondary" onclick="copyInterviewLink('${interviewUrl}')">Copy Interview Link</button>`
                    : '';
                return `
                    <div class="border rounded p-2 mb-2">
                        <div class="small text-muted">
                            JD: ${run.job_description_title || run.job_description_id} • Score: ${run.final_score?.toFixed?.(2) ?? 'N/A'} • ${run.analysis_timestamp || ''}
                        </div>
                        <div class="d-flex justify-content-between align-items-center">
                            <div><strong>Decision:</strong> ${run.decision || 'N/A'}</div>
                            <div class="d-flex align-items-center gap-2">
                                ${copyLinkButton}
                                <a class="btn btn-sm btn-outline-primary" href="${API_BASE_URL}/static/analysis_run.html?run_id=${run.id}" target="_blank">View Analysis</a>
                            </div>
                        </div>
                    </div>
                `;
            }).join('');
        } else {
            historyHtml = '<p class="text-muted">No analysis history yet.</p>';
        }

        const body = document.getElementById('candidate-modal-body');
        body.innerHTML = `
            <div class="mb-3">
                <h6>Basic Details</h6>
                <p class="mb-1"><strong>Name:</strong> ${formatCandidateName(candidate.name) || 'N/A'}</p>
                <p class="mb-1"><strong>Email:</strong> ${candidate.email || 'N/A'}</p>
                <p class="mb-1"><strong>Phone:</strong> ${candidate.phone || 'N/A'}</p>
                ${resumeLink}
            </div>
            <div class="mb-3">
                <h6>Profile</h6>
                <p class="mb-1"><strong>Role:</strong> ${profile.current_role || 'N/A'}</p>
                <p class="mb-1"><strong>Experience:</strong> ${profile.total_experience_years ?? 'N/A'} years</p>
                <p class="mb-1"><strong>Primary Skills:</strong> ${(profile.primary_skills || []).join(', ') || 'N/A'}</p>
                <p class="mb-1"><strong>Secondary Skills:</strong> ${(profile.secondary_skills || []).join(', ') || 'N/A'}</p>
                <p class="mb-1"><strong>Education:</strong> ${profile.education || 'N/A'}</p>
                <p class="mb-1"><strong>Summary:</strong> ${profile.summary || 'N/A'}</p>
                <p class="mb-1"><strong>Location:</strong> ${profile.location || 'N/A'}</p>
                <p class="mb-1"><strong>Invalid Resume:</strong> ${profile.invalid_resume ? 'Yes' : 'No'}</p>
            </div>
            <div class="mb-3">
                <h6>Analysis History</h6>
                ${historyHtml}
            </div>
        `;

        const modal = new bootstrap.Modal(document.getElementById('candidateModal'));
        modal.show();
    } catch (error) {
        showToast(`Failed to load candidate detail: ${error.message}`, 'danger');
    }
}

async function deleteCandidate(candidateId) {
    if (!confirm('Delete this candidate and all related data?')) {
        return;
    }
    try {
        await apiCall(`/api/candidates/${candidateId}`, { method: 'DELETE' });
        showToast('Candidate deleted');
        loadCandidatesManagement();
    } catch (error) {
        showToast(`Failed to delete candidate: ${error.message}`, 'danger');
    }
}

const cmForm = document.getElementById('candidate-management-form');
if (cmForm) {
    cmForm.addEventListener('submit', async (event) => {
        event.preventDefault();
        const name = document.getElementById('cm-name').value;
        const email = document.getElementById('cm-email').value;
        const phone = document.getElementById('cm-phone').value;
        const jdId = document.getElementById('cm-jd').value;
        const fileInput = document.getElementById('cm-resume');
        const file = fileInput.files[0];
        if (!file) {
            showToast('Please select a resume file.', 'warning');
            return;
        }
        try {
            showToast('Adding candidate...', 'info');
            const submitButton = cmForm.querySelector('button[type="submit"]');
            const originalLabel = submitButton ? submitButton.innerHTML : '';
            if (submitButton) {
                submitButton.disabled = true;
                submitButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Saving...';
            }
            const formData = new FormData();
            formData.append('file', file);
            formData.append('name', name);
            formData.append('email', email);
            formData.append('phone', phone);
            if (jdId) {
                formData.append('job_description_id', jdId);
            }
            const response = await fetch(`${API_BASE_URL}/api/candidates/upload`, {
                method: 'POST',
                body: formData,
            });
            if (!response.ok) {
                const errorData = await response.json();
                if (response.status === 409) {
                    throw new Error('Duplicate candidate found (same name and email).');
                }
                throw new Error(errorData.detail || 'Upload failed');
            }
            showToast('Candidate added');
            cmForm.reset();
            loadCandidatesManagement();
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = originalLabel;
            }
        } catch (error) {
            showToast(`Failed to add candidate: ${error.message}`, 'danger');
            const submitButton = cmForm.querySelector('button[type="submit"]');
            if (submitButton) {
                submitButton.disabled = false;
                submitButton.innerHTML = '<i class="bi bi-plus me-2"></i>Add Candidate';
            }
        }
    });
}

const folderUploadButton = document.getElementById('cm-folder-upload');
if (folderUploadButton) {
    folderUploadButton.addEventListener('click', async () => {
        const jdId = document.getElementById('cm-folder-jd').value;
        const folderInput = document.getElementById('cm-folder');
        const filesInput = document.getElementById('cm-files');
        const files = filesInput?.files?.length ? filesInput.files : folderInput.files;
        if (!files.length) {
            showToast('Select a folder or files.', 'warning');
            return;
        }
        try {
            showToast('Uploading folder...', 'info');
            const originalLabel = folderUploadButton.innerHTML;
            folderUploadButton.disabled = true;
            folderUploadButton.innerHTML = '<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Uploading...';
            const progress = document.getElementById('cm-folder-progress');
            const progressBar = document.getElementById('cm-folder-progress-bar');
            const progressText = document.getElementById('cm-folder-progress-text');
            progress.classList.remove('d-none');
            progressText.classList.remove('d-none');

            const fileArray = Array.from(files);
            let uploaded = 0;
            const total = fileArray.length;

            for (const file of fileArray) {
                const formData = new FormData();
                formData.append('file', file);
                formData.append('name', file.name.replace(/\.[^/.]+$/, '').replace(/_/g, ' '));
                if (jdId) {
                    formData.append('job_description_id', jdId);
                }

                const response = await fetch(`${API_BASE_URL}/api/candidates/upload`, {
                    method: 'POST',
                    body: formData,
                });

                if (!response.ok) {
                    const errorData = await response.json();
                    if (response.status !== 409) {
                        throw new Error(errorData.detail || 'Upload failed');
                    }
                }

                uploaded += 1;
                const pct = Math.round((uploaded / total) * 100);
                progressBar.style.width = `${pct}%`;
                progressBar.textContent = `${pct}%`;
                progressText.textContent = `Uploaded ${uploaded} of ${total} resumes`;
            }

            showToast('Folder upload completed');
            folderInput.value = '';
            if (filesInput) {
                filesInput.value = '';
            }
            loadCandidatesManagement();
            progress.classList.add('d-none');
            progressText.classList.add('d-none');
            progressBar.style.width = '0%';
            progressBar.textContent = '0%';
            folderUploadButton.disabled = false;
            folderUploadButton.innerHTML = originalLabel;
        } catch (error) {
            showToast(`Bulk upload failed: ${error.message}`, 'danger');
            folderUploadButton.disabled = false;
            folderUploadButton.innerHTML = '<i class="bi bi-upload me-2"></i>Upload Folder';
            const progress = document.getElementById('cm-folder-progress');
            const progressText = document.getElementById('cm-folder-progress-text');
            if (progress) progress.classList.add('d-none');
            if (progressText) progressText.classList.add('d-none');
        }
    });
}

const filterApplyButton = document.getElementById('cm-filter-apply');
if (filterApplyButton) {
    filterApplyButton.addEventListener('click', loadCandidatesManagement);
}

const bulkDeleteButton = document.getElementById('cm-bulk-delete');
if (bulkDeleteButton) {
    bulkDeleteButton.addEventListener('click', async () => {
        const selected = Array.from(document.querySelectorAll('.cm-select'))
            .filter(box => box.checked)
            .map(box => parseInt(box.dataset.candidateId, 10));
        if (!selected.length) {
            showToast('Select candidates to delete', 'warning');
            return;
        }
        if (!confirm(`Delete ${selected.length} candidates and all data?`)) {
            return;
        }
        try {
            await apiCall('/api/candidates/bulk-delete', {
                method: 'POST',
                body: JSON.stringify(selected),
            });
            showToast('Candidates deleted');
            loadCandidatesManagement();
        } catch (error) {
            showToast(`Bulk delete failed: ${error.message}`, 'danger');
        }
    });
}

const bulkLinkButton = document.getElementById('cm-bulk-link');
if (bulkLinkButton) {
    bulkLinkButton.addEventListener('click', async () => {
        const jdId = document.getElementById('cm-bulk-link-jd').value;
        const selected = Array.from(document.querySelectorAll('.cm-select'))
            .filter(box => box.checked)
            .map(box => parseInt(box.dataset.candidateId, 10));
        if (!jdId || !selected.length) {
            showToast('Select candidates and a job description to link', 'warning');
            return;
        }
        try {
            await apiCall('/api/candidates/link-jd', {
                method: 'POST',
                body: JSON.stringify({
                    candidate_ids: selected,
                    job_description_id: parseInt(jdId, 10),
                }),
            });
            showToast('Candidates linked to JD');
            loadCandidatesManagement();
        } catch (error) {
            showToast(`Linking failed: ${error.message}`, 'danger');
        }
    });
}

// Interview Reviews
async function loadInterviewSummaries() {
    const container = document.getElementById('interview-summary-list');
    if (!container) {
        return;
    }
    container.innerHTML = '<p class="text-muted">Loading interview summaries...</p>';
    try {
        const summaries = await apiCall('/api/interviews/summary');
        if (!summaries || summaries.length === 0) {
            container.innerHTML = '<p class="text-muted">No interview summaries available.</p>';
            return;
        }
        let html = `
            <div class="table-responsive">
                <table class="table">
                    <thead>
                        <tr>
                            <th>Candidate</th>
                            <th>Analysis Score</th>
                            <th>Decision</th>
                            <th>Interview Score</th>
                            <th>Recommendation</th>
                            <th>Status</th>
                            <th>Summary</th>
                            <th>Review</th>
                        </tr>
                    </thead>
                    <tbody>
        `;
        summaries.forEach(item => {
            const candidate = item.candidate || {};
            const analysis = item.analysis || {};
            const session = item.session || {};
            const feedback = item.feedback || {};
            const analysisScore = typeof analysis.final_score === 'number' ? analysis.final_score.toFixed(2) : 'N/A';
            const decision = analysis.decision || 'N/A';
            const interviewScore = typeof session.overall_score === 'number' ? session.overall_score.toFixed(1) : 'N/A';
            const recommendation = session.recommendation || feedback.hire_signal || 'N/A';
            const status = session.status || 'No interview';
            const summary = session.summary || 'N/A';
            const reviewLink = candidate.id
                ? `<a class="btn btn-sm btn-outline-primary" href="${API_BASE_URL}/static/interview_review.html?candidate_id=${candidate.id}" target="_blank">Open</a>`
                : '';
            html += `
                <tr>
                    <td>${candidate.name || 'Unknown'}</td>
                    <td>${analysisScore}</td>
                    <td>${decision}</td>
                    <td>${interviewScore}</td>
                    <td>${recommendation}</td>
                    <td>${status}</td>
                    <td style="max-width: 280px;">${summary}</td>
                    <td>${reviewLink}</td>
                </tr>
            `;
        });
        html += `
                    </tbody>
                </table>
            </div>
        `;
        container.innerHTML = html;
    } catch (error) {
        container.innerHTML = `<div class="alert alert-danger">Failed to load interview summaries: ${error.message}</div>`;
    }
}
