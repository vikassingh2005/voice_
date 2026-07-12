"""
wake_word.py — Passive background listener for the "Hey Echos" activation phrase.

Uses openwakeword with a raw PyAudio stream.  Detection is CPU-only and
extremely lightweight so the main event loop can stay blocked here indefinitely
while consuming negligible resources.

Public API
----------
WakeWordDetector.wait_for_wake_word() -> None
    Blocks until the wake phrase is detected, then returns cleanly so the
    caller can hand off to the full audio pipeline.
"""

from __future__ import annotations

import threading
import time
from typing import Optional

import numpy as np
import pyaudio
from loguru import logger

import config

# openwakeword imports
try:
    from openwakeword.model import Model as OWWModel
    _OWW_AVAILABLE = True
except ImportError:
    _OWW_AVAILABLE = False
    logger.warning("openwakeword not installed – wake-word detection disabled.")


class WakeWordDetector:
    """
    Encapsulates the openwakeword inference loop.

    Parameters
    ----------
    model_name:
        Name of the bundled openwakeword model (e.g. 'hey_mycroft') or an
        absolute path to a custom .onnx / .tflite model file.
    threshold:
        Confidence threshold [0, 1] above which a detection is declared.
    """

    # openwakeword expects 16-bit PCM at 16 kHz, chunks of 1280 samples
    # (80 ms) — this is its native frame size.
    _FRAME_SAMPLES: int = 1280

    def __init__(
        self,
        model_name: str = config.WAKE_WORD_MODEL_NAME,
        threshold: float = config.WAKE_WORD_THRESHOLD,
    ) -> None:
        self._threshold = threshold
        self._detected = threading.Event()

        if not _OWW_AVAILABLE:
            logger.error("openwakeword unavailable — wake-word detector is a no-op.")
            self._model: Optional[OWWModel] = None
            return

        logger.info(f"Loading openwakeword model: '{model_name}' …")
        try:
            # inference_framework="onnx" gives the fastest CPU inference
            self._model = OWWModel(
                wakeword_models=[model_name],
                inference_framework="onnx",
            )
            logger.success("Wake-word model loaded.")
        except Exception as exc:
            logger.error(f"Failed to load wake-word model: {exc}")
            self._model = None

    # ──────────────────────────────────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────────────────────────────────

    def wait_for_wake_word(self) -> None:
        """
        Block until the wake phrase is confidently detected.

        Falls back to a simple keyboard-interrupt mechanism if openwakeword
        is unavailable (useful for development on machines without a mic).
        """
        if self._model is None:
            logger.warning(
                "openwakeword unavailable. Press ENTER to simulate wake-word."
            )
            input()
            return

        pa = pyaudio.PyAudio()
        stream = pa.open(
            rate=config.MIC_SAMPLE_RATE,
            channels=config.MIC_CHANNELS,
            format=pyaudio.paInt16,
            input=True,
            frames_per_buffer=self._FRAME_SAMPLES,
        )

        logger.info('Passive listening … say "Hey Pravaha" to activate.')
        self._detected.clear()

        try:
            while not self._detected.is_set():
                raw = stream.read(self._FRAME_SAMPLES, exception_on_overflow=False)
                audio_np = np.frombuffer(raw, dtype=np.int16)

                # openwakeword expects float32 in [-1, 1]
                audio_f32 = audio_np.astype(np.float32) / 32768.0

                prediction = self._model.predict(audio_f32)
                scores: dict[str, float] = prediction  # model_name -> score

                for model_label, score in scores.items():
                    if score >= self._threshold:
                        logger.success(
                            f"Wake word detected! [{model_label}={score:.3f}]"
                        )
                        self._detected.set()
                        break
        finally:
            stream.stop_stream()
            stream.close()
            pa.terminate()

    def reset(self) -> None:
        """Clear the detected event so the detector can be re-armed."""
        self._detected.clear()
        if self._model is not None:
            # Reset the internal sliding-window state
            try:
                self._model.reset()
            except AttributeError:
                pass  # older openwakeword versions don't expose reset()
