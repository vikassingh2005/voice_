"""
memory.py — Persistent local long-term memory backed by ChromaDB +
sentence-transformers.

Before every LLM call, the orchestrator queries this store with the user's
latest utterance to retrieve the most relevant historical facts and inject
them into the system prompt.  New facts can be added programmatically or
derived from conversation summaries.

Public API
──────────
MemoryStore.query(text: str) -> list[str]
    Return the top-K relevant memory snippets for the given query.

MemoryStore.add(text: str, metadata: dict | None) -> None
    Store a new fact or memory snippet.

MemoryStore.build_context_block(query: str) -> str
    Convenience wrapper that formats retrieved memories as a prompt suffix.
"""

from __future__ import annotations

import hashlib
import time
from typing import Optional

import chromadb
from chromadb.config import Settings
from loguru import logger
from sentence_transformers import SentenceTransformer

import config


class MemoryStore:
    """
    Wraps ChromaDB with a sentence-transformer embedding function for
    semantic similarity search.
    """

    def __init__(self) -> None:
        logger.info(f"Loading embedding model '{config.EMBEDDING_MODEL}' …")
        self._embedder = SentenceTransformer(config.EMBEDDING_MODEL)
        logger.success("Embedding model loaded.")

        # Persistent ChromaDB client — data lives in CHROMA_DIR between sessions
        self._client = chromadb.PersistentClient(
            path=str(config.CHROMA_DIR),
            settings=Settings(anonymized_telemetry=False),
        )
        self._collection = self._client.get_or_create_collection(
            name=config.MEMORY_COLLECTION,
            metadata={"hnsw:space": "cosine"},
        )
        logger.info(
            f"Memory store ready — {self._collection.count()} facts on record."
        )

    # ──────────────────────────────────────────────────────────────────────────
    # Private helpers
    # ──────────────────────────────────────────────────────────────────────────

    def _embed(self, text: str) -> list[float]:
        """Return the normalised sentence embedding as a plain Python list."""
        return self._embedder.encode(text, normalize_embeddings=True).tolist()

    @staticmethod
    def _make_id(text: str) -> str:
        """Deterministic ID so exact duplicate facts are never double-stored."""
        return hashlib.sha256(text.encode()).hexdigest()[:16]

    # ──────────────────────────────────────────────────────────────────────────
    # Public interface
    # ──────────────────────────────────────────────────────────────────────────

    def add(self, text: str, metadata: Optional[dict] = None) -> None:
        """
        Persist a new memory snippet.

        Parameters
        ----------
        text:
            A concise factual statement, e.g.
            "The user prefers metric units."
        metadata:
            Arbitrary key-value pairs stored alongside the embedding
            (e.g. {"source": "conversation", "timestamp": "…"}).
        """
        doc_id = self._make_id(text)
        meta = metadata or {}
        meta.setdefault("timestamp", str(time.time()))
        meta.setdefault("text", text)

        self._collection.upsert(
            ids=[doc_id],
            documents=[text],
            embeddings=[self._embed(text)],
            metadatas=[meta],
        )
        logger.debug(f"Memory stored [{doc_id}]: {text!r}")

    def query(self, text: str, top_k: int = config.MEMORY_TOP_K) -> list[str]:
        """
        Retrieve the top-K semantically similar memory snippets.

        Returns an empty list if the collection is empty or no results
        exceed the relevance threshold.
        """
        if self._collection.count() == 0:
            return []

        results = self._collection.query(
            query_embeddings=[self._embed(text)],
            n_results=min(top_k, self._collection.count()),
            include=["documents", "distances"],
        )

        snippets: list[str] = []
        docs: list[str] = results.get("documents", [[]])[0]
        distances: list[float] = results.get("distances", [[]])[0]

        for doc, dist in zip(docs, distances):
            # ChromaDB cosine distance: 0 = identical, 2 = opposite.
            # Convert to similarity: sim = 1 - dist/2
            similarity = 1.0 - dist / 2.0
            if similarity >= config.MEMORY_MIN_RELEVANCE:
                snippets.append(doc)
                logger.debug(f"Memory hit (sim={similarity:.3f}): {doc!r}")

        return snippets

    def build_context_block(self, query: str) -> str:
        """
        Return a formatted string ready to be appended to the system prompt.
        Empty string if no relevant memories exist.
        """
        snippets = self.query(query)
        if not snippets:
            return ""
        lines = "\n".join(f"- {s}" for s in snippets)
        return (
            "\n\n[Relevant facts about this user from long-term memory:]\n" + lines
        )

    def seed_demo_memories(self) -> None:
        """
        Populate a handful of demo facts so the system is useful out-of-the-box.
        Safe to call every startup — upsert is idempotent.
        """
        facts = [
            "The user's name is Alex.",
            "Alex prefers to be addressed informally.",
            "Alex lives in a two-bedroom apartment in San Francisco.",
            "Alex's favourite music genre is jazz.",
            "Alex has a standing desk and uses it for long work sessions.",
            "The living room light is a Philips Hue bulb.",
            "Alex uses metric units for measurements.",
        ]
        for fact in facts:
            self.add(fact, metadata={"source": "seed"})
        logger.info(f"Seeded {len(facts)} demo memories.")
