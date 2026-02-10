"""Speech-to-text service for audio interviews."""

from __future__ import annotations

import asyncio
from io import BytesIO
from typing import Optional

import numpy as np
import soundfile as sf

from src.config.settings import get_settings


class WhisperSTT:
    """Whisper STT wrapper using faster-whisper."""

    def __init__(self) -> None:
        self._model = None
        self._model_lock = asyncio.Lock()

    async def transcribe_wav(self, wav_bytes: bytes) -> str:
        """Transcribe WAV bytes into text."""
        if not wav_bytes:
            raise ValueError("Audio payload is empty")
        return await asyncio.to_thread(self._transcribe_sync, wav_bytes)

    def _load_model(self):
        if self._model is not None:
            return self._model

        settings = get_settings()
        from faster_whisper import WhisperModel  # pylint: disable=import-error

        self._model = WhisperModel(
            settings.stt_model_size,
            device=settings.stt_device,
            compute_type=settings.stt_compute_type,
        )
        return self._model

    def _transcribe_sync(self, wav_bytes: bytes) -> str:
        model = self._load_model()
        audio_data, sample_rate = sf.read(BytesIO(wav_bytes))

        if isinstance(audio_data, np.ndarray) and audio_data.ndim > 1:
            audio_data = np.mean(audio_data, axis=1)

        audio_data = audio_data.astype(np.float32)
        target_rate = 16000
        if sample_rate != target_rate:
            duration = audio_data.shape[0] / sample_rate
            target_length = int(duration * target_rate)
            if target_length > 0:
                x_old = np.linspace(0, duration, num=audio_data.shape[0], endpoint=False)
                x_new = np.linspace(0, duration, num=target_length, endpoint=False)
                audio_data = np.interp(x_new, x_old, audio_data).astype(np.float32)
            sample_rate = target_rate

        segments, _ = model.transcribe(audio_data, language="en")
        text_parts = [seg.text.strip() for seg in segments if seg.text.strip()]
        return " ".join(text_parts)
