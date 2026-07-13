"""
audio_handler.py — Microphone capture, Silero-VAD state machine, and
Acoustic Echo Cancellation (AEC).

State machine
─────────────
  IDLE          Mic is open but we discard audio — waiting for speech onset.
  LISTENING     Speech detected; we accumulate frames into a rolling buffer.
  PAUSING       Short gap in speech (breath / hesitation). We keep buffering
                but count silence frames; if speech resumes we go back to
                LISTENING, else we transition to ENDPOINT.
  ENDPOINT      Utterance is complete. Buffer is flushed to the STT caller.

Acoustic Echo Cancellation
──────────────────────────
A global flag `is_speaking` is set/cleared by the TTS engine.  While it is
True the incoming mic frames are multiplied by AEC_ATTENUATION (nearly muted)
so Whisper never sees the synthesized audio leaking back in.

Public API
──────────
AudioHandler.record_utterance() -> bytes
    Blocks until a complete utterance is detected and returns raw 16-bit PCM.
AudioHandler.set_speaking(speaking: bool) -> None
    Called by the TTS layer to toggle AEC suppression.
"""

from __future__ import annotations

import enum
import time
from typing import List

import numpy as np
import pyaudio
import torch
from loguru import logger

import config


# ─────────────────────────────────────────────────────────────────────────────
# Silero-VAD loader
# ─────────────────────────────────────────────────────────────────────────────

def _load_silero_vad():
    """Load Silero-VAD from torch.hub (cached after first download)."""
    logger.info("Loading Silero-VAD …")
    model, utils = torch.hub.load(
        repo_or_dir="snakers4/silero-vad",
        model="silero_vad",
        force_reload=False,
        onnx=False,
        verbose=False,
    )
    # utils contains (get_speech_timestamps, save_audio, read_audio,
    #                 VADIterator, collect_chunks)
    return model, utils


# ─────────────────────────────────────────────────────────────────────────────
# VAD state enum
# ─────────────────────────────────────────────────────────────────────────────

class _VadState(enum.Enum):
    IDLE = "idle"
    LISTENING = "listening"
    PAUSING = "pausing"
    ENDPOINT = "endpoint"


# ─────────────────────────────────────────────────────────────────────────────
# AudioHandler
# ─────────────────────────────────────────────────────────────────────────────

class AudioHandler:
    """
    Opens the microphone, feeds frames through Silero-VAD, and drives the
    state machine described at the top of this module.
    """

    def __init__(self) -> None:
        self._vad_model, self._vad_utils = _load_silero_vad()
        self._vad_model.eval()

        # AEC suppression flag (written from the TTS thread)
        self._is_speaking: bool = False

        # PyAudio handle — opened lazily in record_utterance()
        self._pa: pyaudio.PyAudio = pyaudio.PyAudio()

    # ──────────────────────────────────────────────────────────────────────────
    # AEC control
    # ──────────────────────────────────────────────────────────────────────────

    def set_speaking(self, speaking: bool) -> None:
        """
        Set to True when TTS playback starts, False when it finishes.
        Thread-safe because Python bool assignment is atomic on CPython.
        """
        self._is_speaking = speaking
        if speaking:
            logger.debug("AEC: suppression ON (Echos is speaking)")
        else:
            logger.debug("AEC: suppression OFF")

    # ──────────────────────────────────────────────────────────────────────────
    # VAD helper
    # ──────────────────────────────────────────────────────────────────────────

    def _vad_confidence(self, pcm_int16: np.ndarray) -> float:
        """Return Silero-VAD speech probability for a single 30 ms frame."""
        # Normalise to float32 in [-1, 1]
        audio_f32 = pcm_int16.astype(np.float32) / 32768.0
        tensor = torch.from_numpy(audio_f32).unsqueeze(0)  # shape [1, N]
        with torch.no_grad():
            prob = self._vad_model(tensor, config.MIC_SAMPLE_RATE).item()
        return prob

    # ──────────────────────────────────────────────────────────────────────────
    # Main capture loop
    # ──────────────────────────────────────────────────────────────────────────

    def record_utterance(self) -> bytes:
        """
        Open the microphone, run the VAD state machine, and return the
        complete utterance as raw 16-bit PCM bytes when an endpoint is reached.

        This method is blocking and single-shot — call it once per turn.
        """
        stream = self._pa.open(
            rate=config.MIC_SAMPLE_RATE,
            channels=config.MIC_CHANNELS,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=config.MIC_CHUNK_SAMPLES,
        )

        state = _VadState.IDLE
        buffer: List[bytes] = []   # accumulated raw PCM frames
        silence_count: int = 0     # consecutive silent frames in PAUSING

        logger.info("Listening for speech …")

        try:
            while True:
                raw = stream.read(
                    config.MIC_CHUNK_SAMPLES, exception_on_overflow=False
                )
                frame = np.frombuffer(raw, dtype=np.int16).copy()

                # ── AEC attenuation ──────────────────────────────────────────
                if self._is_speaking:
                    frame = (frame * config.AEC_ATTENUATION).astype(np.int16)

                prob = self._vad_confidence(frame)
                is_speech = prob >= config.VAD_THRESHOLD

                # ── State transitions ────────────────────────────────────────
                if state is _VadState.IDLE:
                    if is_speech:
                        logger.debug(f"Speech onset  (prob={prob:.2f})")
                        state = _VadState.LISTENING
                        buffer.append(frame.tobytes())

                elif state is _VadState.LISTENING:
                    buffer.append(frame.tobytes())
                    if not is_speech:
                        state = _VadState.PAUSING
                        silence_count = 1
                        logger.debug("Entered PAUSING …")
                    elif len(buffer) >= config.MAX_UTTERANCE_FRAMES:
                        logger.debug(f"Forcing endpoint: hit maximum utterance limit of {config.MAX_UTTERANCE_SECONDS}s.")
                        state = _VadState.ENDPOINT
                        break

                elif state is _VadState.PAUSING:
                    buffer.append(frame.tobytes())
                    if is_speech:
                        logger.debug("Speech resumed → back to LISTENING")
                        state = _VadState.LISTENING
                        silence_count = 0
                    else:
                        silence_count += 1
                        if silence_count >= config.ENDPOINT_SILENCE_FRAMES:
                            logger.debug(
                                f"Endpoint reached after {silence_count} silent frames."
                            )
                            state = _VadState.ENDPOINT
                            break

                    if len(buffer) >= config.MAX_UTTERANCE_FRAMES:
                        logger.debug(f"Forcing endpoint: hit maximum utterance limit of {config.MAX_UTTERANCE_SECONDS}s.")
                        state = _VadState.ENDPOINT
                        break

        finally:
            stream.stop_stream()
            stream.close()

        utterance_bytes = b"".join(buffer)
        duration_s = len(utterance_bytes) / (
            config.MIC_SAMPLE_RATE * 2  # 2 bytes per int16 sample
        )
        logger.info(f"Utterance captured: {duration_s:.2f} s")
        return utterance_bytes

    def close(self) -> None:
        """Release PyAudio resources."""
        self._pa.terminate()
        logger.debug("AudioHandler closed.")
