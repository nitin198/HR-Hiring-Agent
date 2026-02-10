"""Text-to-speech service for audio interviews."""

from __future__ import annotations

import asyncio
import os
import subprocess
import tempfile

from src.config.settings import get_settings


class PiperTTS:
    """Piper TTS wrapper using the local CLI binary."""

    def __init__(self) -> None:
        settings = get_settings()
        self.bin_path = settings.tts_piper_bin
        self.voice_path = settings.tts_piper_voice

    async def synthesize(self, text: str) -> bytes:
        """Synthesize text to WAV bytes."""
        if not text.strip():
            raise ValueError("TTS text is empty")
        return await asyncio.to_thread(self._synthesize_sync, text)

    def _synthesize_sync(self, text: str) -> bytes:
        if not os.path.exists(self.voice_path):
            raise FileNotFoundError(f"Piper voice model not found: {self.voice_path}")

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            output_path = tmp_file.name

        try:
            result = subprocess.run(
                [self.bin_path, "--model", self.voice_path, "--output_file", output_path],
                input=text.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                check=False,
            )
            if result.returncode != 0:
                stderr = result.stderr.decode("utf-8", errors="ignore")
                raise RuntimeError(f"Piper TTS failed: {stderr.strip() or 'unknown error'}")
            with open(output_path, "rb") as audio_file:
                return audio_file.read()
        finally:
            try:
                os.remove(output_path)
            except OSError:
                pass
