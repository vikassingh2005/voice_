"""
tts.py — Real-time streaming Text-to-Speech using Kokoro-82M + sounddevice.

Architecture
────────────
The pipeline uses two threads and two queues:

  LLM stream → [sentence_queue] → SentenceWorker → [audio_queue] → PlayerWorker → speaker

• SentenceWorker pulls complete sentences from sentence_queue, synthesises
  audio via Kokoro, and pushes the resulting numpy arrays into audio_queue.
• PlayerWorker pulls audio chunks from audio_queue and plays them through
  sounddevice, blocking between chunks so timing is correct.

The orchestrator in main.py feeds tokens into TTSEngine.feed_token() and
calls TTSEngine.flush() when the LLM stream ends, then waits for playback to
finish with TTSEngine.wait_until_done().

Public API
──────────
TTSEngine.start()           Start background worker threads.
TTSEngine.stop()            Gracefully stop all threads.
TTSEngine.feed_token(tok)   Accept one LLM token; internally buffers and
                            enqueues complete sentences.
TTSEngine.flush()           Push any remaining partial sentence, then signal
                            end-of-stream.
TTSEngine.wait_until_done() Block until the audio queue is drained.
TTSEngine.on_speaking_change: Callable[[bool], None]
                            Set this to receive start/stop notifications
                            (used by AudioHandler for AEC).
"""

from __future__ import annotations

import queue
import re
import threading
from typing import Callable, Optional

import numpy as np
import sounddevice as sd
from loguru import logger

import config

# ─────────────────────────────────────────────────────────────────────────────
# Kokoro import
# ─────────────────────────────────────────────────────────────────────────────
try:
    from kokoro import KPipeline
    _KOKORO_AVAILABLE = True
except ImportError:
    _KOKORO_AVAILABLE = False
    logger.warning("kokoro not installed — TTS will print text only.")


# Sentinel object pushed into queues to signal end-of-stream
_STOP_SENTINEL = object()

# Regex to detect sentence-ending punctuation
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+|(?<=[.!?])$")


# ─────────────────────────────────────────────────────────────────────────────
# TTSEngine
# ─────────────────────────────────────────────────────────────────────────────

class TTSEngine:
    """
    Manages the two-stage TTS pipeline described at the top of this module.
    """

    def __init__(self) -> None:
        # Queues
        self._sentence_q: queue.Queue = queue.Queue(maxsize=20)
        self._audio_q: queue.Queue = queue.Queue(maxsize=10)

        # Token accumulation buffer
        self._token_buffer: str = ""

        # Threading
        self._synth_thread: Optional[threading.Thread] = None
        self._player_thread: Optional[threading.Thread] = None
        self._done_event = threading.Event()

        # AEC callback — set by main.py
        self.on_speaking_change: Optional[Callable[[bool], None]] = None

        # Load Kokoro pipeline
        if _KOKORO_AVAILABLE:
            logger.info(f"Loading Kokoro TTS (voice={config.KOKORO_VOICE}) …")
            self._pipeline = KPipeline(lang_code="a")  # 'a' = American English
            logger.success("Kokoro TTS ready.")
        else:
            self._pipeline = None

    # ──────────────────────────────────────────────────────────────────────────
    # Lifecycle
    # ──────────────────────────────────────────────────────────────────────────

    def start(self) -> None:
        """Spawn synthesis and player threads."""
        self._done_event.clear()

        self._synth_thread = threading.Thread(
            target=self._synthesis_worker, name="TTS-Synth", daemon=True
        )
        self._player_thread = threading.Thread(
            target=self._player_worker, name="TTS-Player", daemon=True
        )
        self._synth_thread.start()
        self._player_thread.start()
        logger.debug("TTS worker threads started.")

    def stop(self) -> None:
        """Signal both workers to exit and wait for them to finish."""
        # Drain the sentence queue and push a stop sentinel
        self._drain_queue(self._sentence_q)
        self._sentence_q.put(_STOP_SENTINEL)

        if self._synth_thread:
            self._synth_thread.join(timeout=5)

        # Drain audio queue and push stop sentinel
        self._drain_queue(self._audio_q)
        self._audio_q.put(_STOP_SENTINEL)

        if self._player_thread:
            self._player_thread.join(timeout=5)

        logger.debug("TTS worker threads stopped.")

    # ──────────────────────────────────────────────────────────────────────────
    # Token ingestion
    # ──────────────────────────────────────────────────────────────────────────

    def feed_token(self, token: str) -> None:
        """
        Accumulate one LLM output token.

        When a sentence-ending boundary is detected the accumulated text is
        pushed into the sentence queue immediately so synthesis can begin
        before the next sentence is generated.
        """
        self._token_buffer += token

        # Check for one or more sentence boundaries
        parts = _SENTENCE_END.split(self._token_buffer)

        # If there's more than one part, all but the last are complete sentences
        if len(parts) > 1:
            for sentence in parts[:-1]:
                sentence = sentence.strip()
                if sentence:
                    logger.debug(f"Sentence enqueued: {sentence!r}")
                    self._sentence_q.put(sentence)
            # Keep the trailing fragment for the next token
            self._token_buffer = parts[-1]

    def flush(self) -> None:
        """
        Push any remaining buffered text as the final sentence, then signal
        end-of-stream to the synthesis worker.
        """
        remaining = self._token_buffer.strip()
        if remaining:
            logger.debug(f"Flushing final fragment: {remaining!r}")
            self._sentence_q.put(remaining)
        self._token_buffer = ""
        self._sentence_q.put(_STOP_SENTINEL)

    def wait_until_done(self) -> None:
        """Block until all audio has been played."""
        self._done_event.wait()
        self._done_event.clear()

    # ──────────────────────────────────────────────────────────────────────────
    # Worker threads
    # ──────────────────────────────────────────────────────────────────────────

    def _synthesis_worker(self) -> None:
        """Pull sentences → synthesise → push audio arrays."""
        while True:
            try:
                item = self._sentence_q.get(timeout=30)
            except queue.Empty:
                continue

            if item is _STOP_SENTINEL:
                # Forward stop signal to the player
                self._audio_q.put(_STOP_SENTINEL)
                return

            sentence: str = item

            if self._pipeline is None:
                # Fallback: no TTS available — print and skip
                print(f"[Pravaha]: {sentence}")
                continue

            try:
                # Kokoro generator yields (graphemes, phonemes, audio_array)
                audio_chunks: list[np.ndarray] = []
                for _, _, audio in self._pipeline(
                    sentence,
                    voice=config.KOKORO_VOICE,
                    speed=config.KOKORO_SPEED,
                    split_pattern=None,   # we handle splitting ourselves
                ):
                    if audio is not None and len(audio) > 0:
                        audio_chunks.append(audio)

                if audio_chunks:
                    combined = np.concatenate(audio_chunks).astype(np.float32)
                    self._audio_q.put(combined)
                    logger.debug(
                        f"Synthesised {len(combined)/config.TTS_SAMPLE_RATE:.2f}s "
                        f"for: {sentence!r}"
                    )

            except Exception as exc:
                logger.error(f"Kokoro synthesis error: {exc}")

    def _player_worker(self) -> None:
        """Pull audio arrays → play through sounddevice."""
        first_chunk = True
        while True:
            try:
                item = self._audio_q.get(timeout=30)
            except queue.Empty:
                continue

            if item is _STOP_SENTINEL:
                # Notify AEC that speech has ended
                self._notify_speaking(False)
                self._done_event.set()
                return

            audio: np.ndarray = item

            # Notify AEC on first chunk of this response
            if first_chunk:
                self._notify_speaking(True)
                first_chunk = False

            try:
                sd.play(audio, samplerate=config.TTS_SAMPLE_RATE, blocking=True)
            except Exception as exc:
                logger.error(f"sounddevice playback error: {exc}")

    # ──────────────────────────────────────────────────────────────────────────
    # Helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _notify_speaking(self, speaking: bool) -> None:
        if self.on_speaking_change is not None:
            try:
                self.on_speaking_change(speaking)
            except Exception as exc:
                logger.error(f"on_speaking_change callback error: {exc}")

    @staticmethod
    def _drain_queue(q: queue.Queue) -> None:
        """Empty a queue without blocking."""
        while not q.empty():
            try:
                q.get_nowait()
            except queue.Empty:
                break
