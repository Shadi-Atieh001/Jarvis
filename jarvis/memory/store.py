"""Long-term memory, kept in one SQLite file: <home>/memory.db.

Two things are stored:
  memories   short facts JARVIS was told or chose to keep: your preferences,
             people, projects. These are offered back to the model when they
             look relevant to what you just said.
  exchanges  each past request and JARVIS's reply, so it can look up "what
             did we decide about X last week".

Finding the relevant ones uses "embeddings": a small model, running on this
computer, turns each piece of text into a list of numbers such that texts
with similar meaning get similar numbers. If that library is not installed,
search falls back to matching words, which is cruder but still works.

Nothing here leaves the computer, except that memories relevant to a request
are included in what is sent to the model you have chosen.
"""

from __future__ import annotations

import re
import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from jarvis.core.actionlog import redact
from jarvis.core.config import Settings

KINDS = ("preference", "person", "project", "fact")
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"
RELEVANT = 0.5  # similarity (0-1) above which a memory is offered unasked
MAX_TEXT = 1000

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,
    text TEXT NOT NULL,
    created TEXT NOT NULL,
    embedding BLOB
);
CREATE TABLE IF NOT EXISTS exchanges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    time TEXT NOT NULL,
    user_text TEXT NOT NULL,
    reply_text TEXT NOT NULL,
    embedding BLOB
);
"""


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9']+", text.lower()) if len(w) > 2}


class MemoryStore:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.path: Path = settings.home / "memory.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.executescript(_SCHEMA)
        self._embedder = None
        self._embedder_failed = False

    # ---------------------------------------------------------- embeddings

    def _model(self):
        """The embedding model, or None if it cannot be loaded."""
        if self._embedder is None and not self._embedder_failed:
            try:
                from fastembed import TextEmbedding

                self._embedder = TextEmbedding(
                    EMBEDDING_MODEL, cache_dir=str(self.settings.home / "models" / "embeddings")
                )
            except Exception:
                self._embedder_failed = True  # not installed, or no model yet and offline
        return self._embedder

    @property
    def semantic(self) -> bool:
        return self._model() is not None

    def _embed(self, text: str, query: bool = False) -> bytes | None:
        model = self._model()
        if model is None:
            return None
        import numpy as np

        vector = next(iter(model.query_embed(text) if query else model.embed([text])))
        vector = np.asarray(vector, dtype=np.float32)
        return (vector / (np.linalg.norm(vector) or 1.0)).tobytes()

    def _score(self, query_text: str, query_vector: bytes | None, text: str, vector: bytes | None) -> float:
        if query_vector is not None and vector is not None:
            import numpy as np

            return float(np.frombuffer(query_vector, dtype=np.float32) @ np.frombuffer(vector, dtype=np.float32))
        # Fallback: share of the query's words that appear in the text.
        wanted = _words(query_text)
        return len(wanted & _words(text)) / len(wanted) if wanted else 0.0

    # ------------------------------------------------------------ memories

    def remember(self, text: str, kind: str = "fact") -> int:
        text = redact(" ".join(text.split()))[:MAX_TEXT]
        if not text:
            raise ValueError("There is nothing to remember.")
        if kind not in KINDS:
            kind = "fact"
        with self._lock:
            existing = self._db.execute("SELECT id FROM memories WHERE lower(text) = lower(?)", (text,)).fetchone()
            if existing:
                return existing[0]
            cursor = self._db.execute(
                "INSERT INTO memories (kind, text, created, embedding) VALUES (?, ?, ?, ?)",
                (kind, text, _now(), self._embed(text)),
            )
            self._db.commit()
            return cursor.lastrowid

    def all(self) -> list[dict]:
        with self._lock:
            rows = self._db.execute("SELECT id, kind, text, created FROM memories ORDER BY id").fetchall()
        return [dict(zip(("id", "kind", "text", "created"), row)) for row in rows]

    def forget(self, memory_id: int) -> bool:
        with self._lock:
            cursor = self._db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._db.commit()
            return cursor.rowcount > 0

    def forget_everything(self) -> int:
        """Deletes all memories and all past exchanges."""
        with self._lock:
            count = self._db.execute("DELETE FROM memories").rowcount
            self._db.execute("DELETE FROM exchanges")
            self._db.commit()
            self._db.execute("VACUUM")  # remove the deleted text from the file itself
        return count

    def search(self, query: str, limit: int = 6, minimum: float = 0.0) -> list[dict]:
        """Memories most related to the query, best first."""
        query_vector = self._embed(query, query=True)
        with self._lock:
            rows = self._db.execute("SELECT id, kind, text, created, embedding FROM memories").fetchall()
        scored = [
            {"id": r[0], "kind": r[1], "text": r[2], "created": r[3], "score": self._score(query, query_vector, r[2], r[4])}
            for r in rows
        ]
        scored = [m for m in scored if m["score"] >= minimum and m["score"] > 0]
        return sorted(scored, key=lambda m: m["score"], reverse=True)[:limit]

    def relevant(self, user_text: str, limit: int = 5) -> list[dict]:
        """What to offer the model, unasked, alongside a new request."""
        threshold = RELEVANT if self.semantic else 0.34
        return self.search(user_text, limit=limit, minimum=threshold)

    # ----------------------------------------------------------- exchanges

    def save_exchange(self, user_text: str, reply_text: str) -> None:
        user_text, reply_text = redact(user_text)[:4000], redact(reply_text)[:4000]
        if not user_text.strip() or not reply_text.strip():
            return
        with self._lock:
            self._db.execute(
                "INSERT INTO exchanges (time, user_text, reply_text, embedding) VALUES (?, ?, ?, ?)",
                (_now(), user_text, reply_text, self._embed(f"{user_text}\n{reply_text}"[:2000])),
            )
            self._db.commit()

    def search_exchanges(self, query: str, limit: int = 4) -> list[dict]:
        query_vector = self._embed(query, query=True)
        with self._lock:
            rows = self._db.execute("SELECT time, user_text, reply_text, embedding FROM exchanges").fetchall()
        scored = [
            {"time": r[0], "user_text": r[1], "reply_text": r[2], "score": self._score(query, query_vector, f"{r[1]} {r[2]}", r[3])}
            for r in rows
        ]
        scored = [e for e in scored if e["score"] > (0.4 if query_vector is not None else 0.0)]
        return sorted(scored, key=lambda e: e["score"], reverse=True)[:limit]

    def counts(self) -> tuple[int, int]:
        with self._lock:
            return (
                self._db.execute("SELECT count(*) FROM memories").fetchone()[0],
                self._db.execute("SELECT count(*) FROM exchanges").fetchone()[0],
            )


def format_memories(memories: list[dict]) -> str:
    if not memories:
        return "Nothing is remembered yet."
    return "\n".join(f"  #{m['id']:<4} [{m['kind']}] {m['text']}  ({m['created'][:10]})" for m in memories)
