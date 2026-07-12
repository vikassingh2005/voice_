"""
stt.py — Speech-to-Text using faster-whisper with 8-bit quantisation.

Accepts raw 16-bit PCM bytes from AudioHandler, converts them to a
normalised float32 array, and returns a clean transcript string.

Public API
──────────
STTEngine.transcribe(pcm_bytes: bytes) -> str
"""

from __future__ import annotations

import time

import numpy as np
from faster_whisper import WhisperModel
from loguru import logger

import config


class STTEngine:
    """
    Wraps a faster-whisper WhisperModel for single-shot transcription.

    The model is loaded once at construction time and reused across calls,
    avoiding the significant model-loading latency on each turn.
    """

    def __init__(self) -> None:
        logger.info(
            f"Loading Whisper model '{config.WHISPER_MODEL_SIZE}' "
            f"({config.WHISPER_COMPUTE_TYPE}) on {config.WHISPER_DEVICE} …"
        )
        self._model = WhisperModel(
            config.WHISPER_MODEL_SIZE,
            device=config.WHISPER_DEVICE,
            compute_type=config.WHISPER_COMPUTE_TYPE,
        )
        logger.success("Whisper model ready.")

    # ──────────────────────────────────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────────────────────────────────

    def transcribe(self, pcm_bytes: bytes) -> str:
        """
        Convert raw 16-bit PCM audio bytes to a text transcript.

        Parameters
        ----------
        pcm_bytes:
            Raw audio captured at MIC_SAMPLE_RATE Hz, mono, int16 format.

        Returns
        -------
        str
            The recognised utterance.  Returns an empty string if nothing
            intelligible was found.
        """
        if not pcm_bytes:
            return ""

        t0 = time.perf_counter()

        # Convert int16 PCM → float32 normalised to [-1.0, 1.0]
        audio_int16 = np.frombuffer(pcm_bytes, dtype=np.int16)
        audio_f32: np.ndarray = audio_int16.astype(np.float32) / 32768.0

        # faster-whisper accepts a numpy float32 array directly
        segments, info = self._model.transcribe(
            audio_f32,
            language=config.WHISPER_LANGUAGE,
            beam_size=5,
            vad_filter=True,               # built-in VAD post-filter
            vad_parameters=dict(
                min_silence_duration_ms=300
            ),
        )

        # Collect all segment texts (generator — must be consumed)
        parts: list[str] = []
        for segment in segments:
            text = segment.text.strip()
            if text:
                parts.append(text)

        transcript = " ".join(parts).strip()

        elapsed_ms = (time.perf_counter() - t0) * 1000
        logger.info(
            f"STT [{elapsed_ms:.0f} ms] detected lang={info.language} "
            f"prob={info.language_probability:.2f}: '{transcript}'"
        )
        return transcript
