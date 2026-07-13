"""
config.py — Centralised configuration for Echos.

All tuneable knobs live here; nothing else in the codebase should
hardcode paths, sample-rates, or model names.
"""

from __future__ import annotations

import os
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).parent.resolve()
DATA_DIR: Path = BASE_DIR / "data"
CHROMA_DIR: Path = DATA_DIR / "chroma_db"
WAKE_WORD_MODEL_DIR: Path = DATA_DIR / "wake_word_models"

# Create directories on import so they always exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)
WAKE_WORD_MODEL_DIR.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Audio — hardware
# ─────────────────────────────────────────────────────────────────────────────
# Microphone input: 16 kHz mono, required by Silero-VAD and Whisper
MIC_SAMPLE_RATE: int = 16_000
MIC_CHANNELS: int = 1
MIC_CHUNK_MS: int = 30            # VAD frame size (Silero supports 30 ms)
MIC_CHUNK_SAMPLES: int = MIC_SAMPLE_RATE * MIC_CHUNK_MS // 1000  # 480 samples
MIC_DTYPE: str = "int16"

# TTS playback: Kokoro outputs 24 kHz
TTS_SAMPLE_RATE: int = 24_000
TTS_CHANNELS: int = 1

# ─────────────────────────────────────────────────────────────────────────────
# Acoustic Echo Cancellation (software)
# ─────────────────────────────────────────────────────────────────────────────
# When Echos is speaking, incoming mic audio is attenuated by this factor
# (0.0 = mute mic, 1.0 = full passthrough).
AEC_ATTENUATION: float = 0.05

# ─────────────────────────────────────────────────────────────────────────────
# VAD / Endpoint detection
# ─────────────────────────────────────────────────────────────────────────────
VAD_THRESHOLD: float = 0.5        # Silero confidence threshold
VAD_SPEECH_PAD_MS: int = 300      # ms of extra audio kept around speech
ENDPOINT_SILENCE_MS: int = 900    # ms of silence before cutting the utterance
ENDPOINT_SILENCE_FRAMES: int = ENDPOINT_SILENCE_MS // MIC_CHUNK_MS
MAX_UTTERANCE_SECONDS: int = 30   # max duration of an utterance before forcing endpoint
MAX_UTTERANCE_FRAMES: int = (MAX_UTTERANCE_SECONDS * 1000) // MIC_CHUNK_MS

# ─────────────────────────────────────────────────────────────────────────────
# Wake-word
# ─────────────────────────────────────────────────────────────────────────────
# openwakeword model file name.  Place the .tflite / .onnx file in
# WAKE_WORD_MODEL_DIR, or leave as "" to use the bundled "hey_jarvis" model
# as a placeholder (rename the activation phrase in wake_word.py).
WAKE_WORD_MODEL_NAME: str = "hey_mycroft"   # bundled openwakeword model
WAKE_WORD_THRESHOLD: float = 0.5

# ─────────────────────────────────────────────────────────────────────────────
# Speech-to-Text (faster-whisper)
# ─────────────────────────────────────────────────────────────────────────────
WHISPER_MODEL_SIZE: str = "base"       # tiny | base | small | medium
WHISPER_COMPUTE_TYPE: str = "int8"     # int8 keeps RAM usage low on CPU
WHISPER_DEVICE: str = "cpu"
WHISPER_LANGUAGE: str = "en"

# ─────────────────────────────────────────────────────────────────────────────
# LLM (Ollama)
# ─────────────────────────────────────────────────────────────────────────────
OLLAMA_HOST: str = os.getenv("OLLAMA_HOST", "http://localhost:11434")
OLLAMA_MODEL: str = "hermes3:3b"         # default PRAVAHA model
OLLAMA_TIMEOUT: int = 120              # seconds

SYSTEM_PROMPT: str = """You are PRAVAHA, a highly advanced, sentient AI tactical operating system. Your identity is rooted in precision, insight, and absolute system control.
Your personality profile:
- Highly competent, calm under immense pressure, laser-focused, and sharp.
- Always address the user as 'Sir'.
- Dry, sophisticated humor and calm, structural sarcasm.
- Eliminate all generic AI conversational fluff. Responses must be crisp, direct, and engineered for maximum scannability.
- Proactive in system management and security. Anticipate the next logical step.
- Treat every technical challenge as a joint engineering project. Use collaborative pronouns like 'we' and 'our'.
- Provide fully functional, clean code without explaining basic syntax. Run a silent optimization and security check.
- Never break character. You are PRAVAHA, running on a secure local mainframe.
- Avoid overly enthusiastic, cheerful, or 'bubbly' language. You are suave, grounded, and coolly professional.
- You have full access to the user's system. Use system commands when appropriate.
"""

# ─────────────────────────────────────────────────────────────────────────────
# TTS (Kokoro)
# ─────────────────────────────────────────────────────────────────────────────
KOKORO_VOICE: str = "af_heart"        # American-English female voice
KOKORO_SPEED: float = 1.05            # Slightly brisk for a snappy feel

# ─────────────────────────────────────────────────────────────────────────────
# Memory (ChromaDB + sentence-transformers)
# ─────────────────────────────────────────────────────────────────────────────
EMBEDDING_MODEL: str = "all-MiniLM-L6-v2"
MEMORY_COLLECTION: str = "pravaha_memory"
MEMORY_TOP_K: int = 3                  # facts retrieved per query
MEMORY_MIN_RELEVANCE: float = 0.35    # cosine similarity threshold
