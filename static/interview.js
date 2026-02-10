const API_BASE_URL = ((window.APP_CONFIG && window.APP_CONFIG.API_BASE_URL) || window.location.origin).replace(/\/$/, "");

const SILENCE_THRESHOLD = 0.005;
const SILENCE_DURATION_MS = 3500;
const MIN_RECORDING_MS = 2000;

let currentStep = 1;
let candidateId = null;
let sessionId = null;
let currentQuestion = null;
let questionNumber = 1;
let interviewJobDescriptionId = null;

let mediaStream = null;
let audioContext = null;
let sourceNode = null;
let processorNode = null;
let gainNode = null;
let recordedChunks = [];
let recordingStart = 0;
let silenceStart = null;
let meterFill = null;

const stepPanels = {
    1: document.getElementById('step-1-panel'),
    2: document.getElementById('step-2-panel'),
    3: document.getElementById('step-3-panel'),
    4: document.getElementById('step-4-panel'),
};

function setStep(step) {
    currentStep = step;
    Object.values(stepPanels).forEach(panel => panel.classList.add('d-none'));
    stepPanels[step].classList.remove('d-none');

    for (let i = 1; i <= 4; i++) {
        const stepEl = document.getElementById(`interview-step-${i}`);
        stepEl.classList.remove('active', 'completed');
        if (i < step) {
            stepEl.classList.add('completed');
        } else if (i === step) {
            stepEl.classList.add('active');
        }
    }
}

function getQueryParams() {
    const params = new URLSearchParams(window.location.search);
    return {
        candidate_id: params.get('candidate_id'),
        job_description_id: params.get('job_description_id'),
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
    return await response.json();
}

function setStatus(text) {
    const status = document.getElementById('audio-status-text');
    status.textContent = text;
}

async function requestMicrophone() {
    if (mediaStream) {
        return mediaStream;
    }
    mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
    return mediaStream;
}

function startRecording() {
    recordedChunks = [];
    silenceStart = null;
    recordingStart = Date.now();
    setStatus('Listening... speak now.');
    if (!meterFill) {
        meterFill = document.getElementById('mic-meter-fill');
    }

    audioContext = new AudioContext();
    sourceNode = audioContext.createMediaStreamSource(mediaStream);
    processorNode = audioContext.createScriptProcessor(4096, 1, 1);
    gainNode = audioContext.createGain();
    gainNode.gain.value = 0;

    processorNode.onaudioprocess = (event) => {
        const input = event.inputBuffer.getChannelData(0);
        recordedChunks.push(new Float32Array(input));

        let sum = 0;
        for (let i = 0; i < input.length; i++) {
            sum += input[i] * input[i];
        }
        const rms = Math.sqrt(sum / input.length);
        if (meterFill) {
            const level = Math.min(100, Math.max(0, rms * 200));
            meterFill.style.width = `${level}%`;
        }

        if (rms < SILENCE_THRESHOLD) {
            if (!silenceStart) {
                silenceStart = Date.now();
            }
            const silenceDuration = Date.now() - silenceStart;
            const elapsed = Date.now() - recordingStart;
            if (silenceDuration >= SILENCE_DURATION_MS && elapsed >= MIN_RECORDING_MS) {
                stopRecording(true);
            }
        } else {
            silenceStart = null;
        }
    };

    sourceNode.connect(processorNode);
    processorNode.connect(gainNode);
    gainNode.connect(audioContext.destination);
}

function stopRecording(autoAdvance = false) {
    if (!processorNode) {
        return;
    }
    processorNode.disconnect();
    sourceNode.disconnect();
    gainNode.disconnect();

    processorNode = null;
    sourceNode = null;
    gainNode = null;

    const audioBuffer = mergeBuffers(recordedChunks);
    if (!audioBuffer.length) {
        setStatus('No audio captured. Please try again.');
        return;
    }
    const wavBuffer = encodeWAV(audioBuffer, audioContext.sampleRate);
    const wavBlob = new Blob([wavBuffer], { type: 'audio/wav' });

    if (audioContext) {
        audioContext.close();
        audioContext = null;
    }
    if (meterFill) {
        meterFill.style.width = '0%';
    }

    document.getElementById('stop-answer').disabled = true;
    setStatus('Saving your answer...');
    sendAnswer(wavBlob).finally(() => {
        if (autoAdvance) {
            // continue to next question automatically
            return;
        }
    });
}

function mergeBuffers(chunks) {
    const length = chunks.reduce((total, chunk) => total + chunk.length, 0);
    const buffer = new Float32Array(length);
    let offset = 0;
    chunks.forEach((chunk) => {
        buffer.set(chunk, offset);
        offset += chunk.length;
    });
    return buffer;
}

function writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
        view.setUint8(offset + i, string.charCodeAt(i));
    }
}

function encodeWAV(samples, sampleRate) {
    const buffer = new ArrayBuffer(44 + samples.length * 2);
    const view = new DataView(buffer);

    writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + samples.length * 2, true);
    writeString(view, 8, 'WAVE');
    writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, 1, true);
    view.setUint16(22, 1, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * 2, true);
    view.setUint16(32, 2, true);
    view.setUint16(34, 16, true);
    writeString(view, 36, 'data');
    view.setUint32(40, samples.length * 2, true);

    let offset = 44;
    for (let i = 0; i < samples.length; i++, offset += 2) {
        const sample = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, sample < 0 ? sample * 0x8000 : sample * 0x7fff, true);
    }
    return buffer;
}

async function playQuestion(text) {
    const audio = document.getElementById('tts-audio');
    const formData = new FormData();
    formData.append('text', text);

    try {
        setStatus('AI voice speaking...');
        const response = await fetch(`${API_BASE_URL}/api/interviews/tts`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) {
            throw new Error('TTS request failed');
        }
        const audioBlob = await response.blob();
        audio.src = URL.createObjectURL(audioBlob);
        await audio.play();
        audio.onended = () => {
            startRecording();
        };
    } catch (error) {
        if ('speechSynthesis' in window) {
            setStatus('Using browser voice...');
            const utterance = new SpeechSynthesisUtterance(text);
            utterance.onend = () => {
                startRecording();
            };
            window.speechSynthesis.speak(utterance);
        } else {
            setStatus('Unable to play AI voice. Please answer after reading the question.');
            startRecording();
        }
    }
}

async function sendAnswer(wavBlob) {
    if (!sessionId || !currentQuestion) {
        return;
    }
    setStatus('Saving your answer...');
    document.getElementById('stop-answer').disabled = true;

    const formData = new FormData();
    formData.append('question_id', currentQuestion.id);
    formData.append('audio', wavBlob, 'answer.wav');

    try {
        const response = await fetch(`${API_BASE_URL}/api/interviews/${sessionId}/answer`, {
            method: 'POST',
            body: formData,
        });
        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.detail || 'Failed to submit answer');
        }
        const result = await response.json();
        const transcriptBox = document.getElementById('transcript-preview');
        transcriptBox.textContent = `Transcript: ${result.transcript_text}`;
        setStatus('Answer saved. Loading next question...');
        await loadNextQuestion();
    } catch (error) {
        setStatus(`Error: ${error.message}`);
    }
}

async function loadNextQuestion() {
    const data = await apiCall(`/api/interviews/${sessionId}/next`);
    if (!data.question) {
        await finalizeInterview();
        return;
    }
    questionNumber += 1;
    currentQuestion = data.question;
    updateQuestionUI();
    setStatus('Preparing next question...');
    await playQuestion(currentQuestion.question_text);
}

function updateQuestionUI() {
    document.getElementById('question-text').textContent = currentQuestion.question_text;
    document.getElementById('question-count').textContent = `Question ${questionNumber}`;
    document.getElementById('stop-answer').disabled = false;
}

async function finalizeInterview() {
    setStatus('Finalizing interview and analyzing responses...');
    await apiCall(`/api/interviews/${sessionId}/finalize`, { method: 'POST' });
    const summary = document.getElementById('summary-content');
    summary.innerHTML = `
        <p><strong>Interview completed.</strong></p>
        <p>Thank you for your time. Our HR team will review your responses and contact you with next steps.</p>
        <p class="mb-0">You can close this page now.</p>
    `;
    setStep(4);
}

async function startInterview() {
    const startButton = document.getElementById('step-2-next');
    const startStatus = document.getElementById('start-interview-status');
    if (startButton) {
        startButton.disabled = true;
    }
    if (startStatus) {
        startStatus.classList.remove('d-none');
    }
    await requestMicrophone();
    const payload = {
        candidate_id: candidateId,
        job_description_id: interviewJobDescriptionId ? parseInt(interviewJobDescriptionId, 10) : null,
        consent_given: document.getElementById('consent-checkbox').checked,
        notice_period_days: parseInt(document.getElementById('notice-period').value, 10) || null,
        expected_ctc: document.getElementById('expected-ctc').value || null,
        current_ctc: document.getElementById('current-ctc').value || null,
        location: document.getElementById('candidate-location').value || null,
        join_date_preference: document.getElementById('join-date').value || null,
        willing_to_join: document.getElementById('willing-to-join').value === ''
            ? null
            : document.getElementById('willing-to-join').value === 'true',
    };

    try {
        const response = await apiCall('/api/interviews/start', {
            method: 'POST',
            body: JSON.stringify(payload),
        });
        sessionId = response.session.id;
        currentQuestion = response.first_question;
        questionNumber = 1;
        updateQuestionUI();
        setStep(3);
        await playQuestion(currentQuestion.question_text);
    } finally {
        if (startButton) {
            startButton.disabled = false;
        }
        if (startStatus) {
            startStatus.classList.add('d-none');
        }
    }
}

document.getElementById('consent-checkbox').addEventListener('change', (event) => {
    document.getElementById('step-1-next').disabled = !event.target.checked;
});

document.getElementById('step-1-next').addEventListener('click', () => setStep(2));
document.getElementById('step-2-back').addEventListener('click', () => setStep(1));

document.getElementById('step-2-next').addEventListener('click', async () => {
    try {
        await startInterview();
    } catch (error) {
        alert(`Unable to start interview: ${error.message}`);
    }
});

document.getElementById('play-question').addEventListener('click', async () => {
    if (currentQuestion) {
        await playQuestion(currentQuestion.question_text);
    }
});

document.getElementById('stop-answer').addEventListener('click', () => stopRecording(true));

window.addEventListener('load', () => {
    const params = getQueryParams();
    candidateId = params.candidate_id ? parseInt(params.candidate_id, 10) : null;
    interviewJobDescriptionId = params.job_description_id || null;
    if (!candidateId) {
        alert('Missing candidate_id in URL. Please use the interview link provided.');
        return;
    }
    document.getElementById('candidate-id-label').textContent = candidateId;
});
