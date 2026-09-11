"""Memória de consequências da Atena.

Registra não apenas o que a Atena fez, mas o que aconteceu depois. O módulo é
append-oriented, idempotente e pode usar um SQLite separado para validação ou
o mesmo banco da memória episódica, sem alterar tabelas legadas.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Outcome = Literal["success", "partial", "failure", "unknown", "blocked"]
EvidenceKind = Literal["test", "user_feedback", "tool_result", "metric", "observation", "external"]


def _tokens(text: str) -> set[str]:
    return {token.casefold() for token in re.findall(r"[A-Za-zÀ-ÿ0-9_]+", text) if len(token) >= 3}


def _recency_score(updated_at: str) -> float:
    try:
        updated = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
        age_days = max(0.0, (datetime.now(timezone.utc) - updated).total_seconds() / 86400)
        return math.exp(-age_days / 90.0)
    except (TypeError, ValueError):
        return 0.0


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class ConsequenceEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: EvidenceKind
    claim: str = Field(min_length=1, max_length=2000)
    source: str | None = Field(default=None, max_length=1000)
    supports: bool = True
    independent: bool = False
    observed_at: str = Field(default_factory=utc_now)


class ActionRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    arguments_hash: str | None = Field(default=None, max_length=128)
    status: Literal["planned", "executed", "blocked", "failed", "skipped"] = "planned"
    side_effect: bool = False
    result_summary: str | None = Field(default=None, max_length=2000)
    duration_ms: float | None = Field(default=None, ge=0)


class ConsequenceFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source: Literal["user", "test", "tool", "system", "reviewer"]
    label: Literal["positive", "negative", "correction", "preference", "uncertain"]
    text: str = Field(min_length=1, max_length=4000)
    score: float | None = Field(default=None, ge=-1, le=1)
    created_at: str = Field(default_factory=utc_now)


class Lesson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lesson_id: str = Field(default_factory=lambda: f"lesson-{uuid.uuid4().hex[:16]}")
    statement: str = Field(min_length=1, max_length=3000)
    applicability: str = Field(min_length=1, max_length=2000)
    evidence_count: int = Field(default=0, ge=0)
    success_rate: float = Field(default=0, ge=0, le=1)
    confidence: float = Field(default=0, ge=0, le=1)
    status: Literal["candidate", "validated", "deprecated"] = "candidate"
    source_episode_ids: list[str] = Field(default_factory=list)
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)
    content_hash: str = ""


class ConsequenceEpisode(BaseModel):
    model_config = ConfigDict(extra="forbid")
    episode_id: str = Field(default_factory=lambda: f"conseq-{uuid.uuid4().hex[:20]}")
    task_id: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=4000)
    context_hash: str | None = Field(default=None, max_length=128)
    plan: list[str] = Field(default_factory=list, max_length=50)
    actions: list[ActionRecord] = Field(default_factory=list, max_length=100)
    outcome: Outcome = "unknown"
    outcome_summary: str = Field(default="", max_length=4000)
    evidence: list[ConsequenceEvidence] = Field(default_factory=list, max_length=100)
    feedback: list[ConsequenceFeedback] = Field(default_factory=list, max_length=100)
    lessons: list[Lesson] = Field(default_factory=list, max_length=20)
    used_lesson_ids: list[str] = Field(default_factory=list, max_length=50)
    generated_lessons: list[Lesson] = Field(default_factory=list, max_length=20)
    confidence_before: float = Field(default=0, ge=0, le=1)
    confidence_after: float = Field(default=0, ge=0, le=1)
    regression_checked: bool = False
    regression_score: float | None = Field(default=None, ge=0, le=1)
    created_at: str = Field(default_factory=utc_now)
    completed_at: str | None = None
    content_hash: str = ""

    @field_validator("plan")
    @classmethod
    def normalize_plan(cls, value: list[str]) -> list[str]:
        return [str(item).strip()[:1000] for item in value if str(item).strip()]

    def seal(self) -> "ConsequenceEpisode":
        data = self.model_dump(exclude={"content_hash"})
        self.content_hash = canonical_hash(data)
        return self


class ConsequenceMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid")
    total: int = 0
    completed: int = 0
    successes: int = 0
    partials: int = 0
    failures: int = 0
    blocked: int = 0
    unknown: int = 0
    success_rate: float = 0
    feedback_rate: float = 0
    evidence_rate: float = 0
    average_confidence_delta: float = 0
    regression_checked_rate: float = 0


class ConsequenceMemory:
    """Store SQLite para consequências, feedback e lições consolidadas."""

    def __init__(self, db_path: str | Path = "atena_evolution/consequences.sqlite3") -> None:
        self.db_path = str(db_path)
        if self.db_path != ":memory:":
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(self.db_path, timeout=30, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys=ON")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self._init_schema()

    def _init_schema(self) -> None:
        with self.connection:
            self.connection.executescript("""
            CREATE TABLE IF NOT EXISTS consequence_episodes (
                episode_id TEXT PRIMARY KEY,
                task_id TEXT NOT NULL,
                goal TEXT NOT NULL,
                outcome TEXT NOT NULL,
                outcome_summary TEXT NOT NULL,
                confidence_before REAL NOT NULL,
                confidence_after REAL NOT NULL,
                regression_checked INTEGER NOT NULL,
                regression_score REAL,
                created_at TEXT NOT NULL,
                completed_at TEXT,
                content_hash TEXT NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_consequence_task ON consequence_episodes(task_id);
            CREATE INDEX IF NOT EXISTS idx_consequence_outcome ON consequence_episodes(outcome);
            CREATE TABLE IF NOT EXISTS consequence_lessons (
                lesson_id TEXT PRIMARY KEY,
                statement TEXT NOT NULL,
                applicability TEXT NOT NULL,
                evidence_count INTEGER NOT NULL,
                success_rate REAL NOT NULL,
                confidence REAL NOT NULL,
                status TEXT NOT NULL,
                source_episode_ids_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                record_json TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS consequence_events (
                event_id TEXT PRIMARY KEY,
                episode_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                content_hash TEXT NOT NULL,
                FOREIGN KEY (episode_id) REFERENCES consequence_episodes(episode_id)
            );
            """)

    def close(self) -> None:
        self.connection.close()

    def __enter__(self) -> "ConsequenceMemory":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()

    def record_episode(self, episode: ConsequenceEpisode) -> str:
        episode.seal()
        payload = json.dumps(episode.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        with self.connection:
            self.connection.execute("""
                INSERT OR IGNORE INTO consequence_episodes(
                    episode_id, task_id, goal, outcome, outcome_summary,
                    confidence_before, confidence_after, regression_checked,
                    regression_score, created_at, completed_at, content_hash, record_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (episode.episode_id, episode.task_id, episode.goal, episode.outcome,
                  episode.outcome_summary, episode.confidence_before, episode.confidence_after,
                  int(episode.regression_checked), episode.regression_score, episode.created_at,
                  episode.completed_at, episode.content_hash, payload))
            self._event(episode.episode_id, "episode_recorded", {"content_hash": episode.content_hash})
        return episode.episode_id

    def append_feedback(self, episode_id: str, feedback: ConsequenceFeedback) -> None:
        episode = self.get_episode(episode_id)
        if episode is None:
            raise KeyError(f"episódio inexistente: {episode_id}")
        episode.feedback.append(feedback)
        episode.seal()
        self._replace_episode(episode)
        self._event(episode_id, "feedback_added", feedback.model_dump(mode="json"))

    def append_evidence(self, episode_id: str, evidence: ConsequenceEvidence) -> None:
        episode = self.get_episode(episode_id)
        if episode is None:
            raise KeyError(f"episódio inexistente: {episode_id}")
        episode.evidence.append(evidence)
        episode.seal()
        self._replace_episode(episode)
        self._event(episode_id, "evidence_added", evidence.model_dump(mode="json"))

    def get_episode(self, episode_id: str) -> ConsequenceEpisode | None:
        row = self.connection.execute("SELECT record_json FROM consequence_episodes WHERE episode_id=?", (episode_id,)).fetchone()
        return ConsequenceEpisode.model_validate(json.loads(row[0])) if row else None

    def recent(self, limit: int = 20, task_id: str | None = None) -> list[ConsequenceEpisode]:
        limit = max(1, min(int(limit), 500))
        if task_id:
            rows = self.connection.execute("SELECT record_json FROM consequence_episodes WHERE task_id=? ORDER BY created_at DESC LIMIT ?", (task_id, limit)).fetchall()
        else:
            rows = self.connection.execute("SELECT record_json FROM consequence_episodes ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [ConsequenceEpisode.model_validate(json.loads(row[0])) for row in rows]

    def consolidate_lessons(self, *, min_evidence: int = 2, min_confidence: float = 0.65) -> list[Lesson]:
        episodes = [self.get_episode(row[0]) for row in self.connection.execute("SELECT episode_id FROM consequence_episodes ORDER BY created_at ASC")]
        groups: dict[str, list[ConsequenceEpisode]] = {}
        for episode in episodes:
            if not episode:
                continue
            for candidate in episode.lessons:
                key = canonical_hash({"statement": candidate.statement.lower().strip(), "applicability": candidate.applicability.lower().strip()})
                groups.setdefault(key, []).append(episode)
        output: list[Lesson] = []
        for key, source_eps in groups.items():
            source_lessons = [lesson for ep in source_eps for lesson in ep.lessons if canonical_hash({"statement": lesson.statement.lower().strip(), "applicability": lesson.applicability.lower().strip()}) == key]
            if not source_lessons:
                continue
            successes = sum(ep.outcome == "success" for ep in source_eps)
            evidence_count = sum(len(ep.evidence) for ep in source_eps)
            confidence = min(1.0, (evidence_count / max(1, min_evidence)) * (successes / max(1, len(source_eps))))
            lesson = Lesson(statement=source_lessons[0].statement, applicability=source_lessons[0].applicability,
                            evidence_count=evidence_count, success_rate=successes / max(1, len(source_eps)),
                            confidence=confidence, status="validated" if evidence_count >= min_evidence and confidence >= min_confidence else "candidate",
                            source_episode_ids=[ep.episode_id for ep in source_eps])
            lesson.updated_at = utc_now()
            lesson.content_hash = canonical_hash(lesson.model_dump(exclude={"content_hash"}))
            payload = json.dumps(lesson.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
            with self.connection:
                self.connection.execute("""INSERT OR REPLACE INTO consequence_lessons
                    (lesson_id, statement, applicability, evidence_count, success_rate, confidence, status,
                     source_episode_ids_json, created_at, updated_at, content_hash, record_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", (lesson.lesson_id, lesson.statement, lesson.applicability,
                    lesson.evidence_count, lesson.success_rate, lesson.confidence, lesson.status,
                    json.dumps(lesson.source_episode_ids), lesson.created_at, lesson.updated_at, lesson.content_hash, payload))
            output.append(lesson)
        return output

    def search_validated_lessons(self, query: str, *, limit: int = 5, min_confidence: float = 0.65, applicability: str | None = None) -> list[dict[str, Any]]:
        """Busca lições validadas com ranking explicável e sem efeitos externos."""
        query_tokens = _tokens(query)
        candidates = self.lessons(limit=500, validated_only=True)
        ranked: list[dict[str, Any]] = []
        for lesson in candidates:
            if lesson.confidence < min_confidence:
                continue
            haystack = f"{lesson.statement} {lesson.applicability}"
            if applicability and applicability.casefold() not in haystack.casefold():
                continue
            lesson_tokens = _tokens(haystack)
            overlap = len(query_tokens & lesson_tokens) / max(1, len(query_tokens))
            recency = _recency_score(lesson.updated_at)
            evidence = min(1.0, lesson.evidence_count / 5.0)
            score = 0.40 * overlap + 0.25 * lesson.confidence + 0.20 * lesson.success_rate + 0.10 * evidence + 0.05 * recency
            ranked.append({"lesson": lesson.model_dump(mode="json"), "score": round(score, 6), "ranking": {
                "token_overlap": round(overlap, 6), "confidence": lesson.confidence,
                "success_rate": lesson.success_rate, "evidence": evidence, "recency": round(recency, 6)}})
        ranked.sort(key=lambda item: item["score"], reverse=True)
        return ranked[:max(1, min(int(limit), 20))]

    def export_json(self, path: str | Path) -> Path:
        """Exporta episódios e lições em JSON canônico para backup/análise."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": 1, "exported_at": utc_now(),
                   "episodes": [episode.model_dump(mode="json") for episode in self.recent(5000)],
                   "lessons": [lesson.model_dump(mode="json") for lesson in self.lessons(5000)]}
        payload["content_hash"] = canonical_hash(payload)
        target.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        return target

    def import_json(self, path: str | Path, *, replace: bool = False) -> int:
        """Importa backup JSON validado; por padrão é append/idempotente."""
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        if payload.get("schema_version") != 1:
            raise ValueError("schema de backup desconhecido")
        expected = payload.get("content_hash")
        check = dict(payload); check.pop("content_hash", None)
        if expected and expected != canonical_hash(check):
            raise ValueError("hash do backup inválido")
        if replace:
            with self.connection:
                self.connection.execute("DELETE FROM consequence_events")
                self.connection.execute("DELETE FROM consequence_episodes")
                self.connection.execute("DELETE FROM consequence_lessons")
        count = 0
        for raw in payload.get("episodes", []):
            self.record_episode(ConsequenceEpisode.model_validate(raw))
            count += 1
        return count

    def lessons(self, limit: int = 50, validated_only: bool = False) -> list[Lesson]:
        query = "SELECT record_json FROM consequence_lessons"
        args: tuple[Any, ...] = ()
        if validated_only:
            query += " WHERE status='validated'"
        query += " ORDER BY confidence DESC, updated_at DESC LIMIT ?"
        rows = self.connection.execute(query, (*args, max(1, min(int(limit), 500)))).fetchall()
        return [Lesson.model_validate(json.loads(row[0])) for row in rows]

    def metrics(self) -> ConsequenceMetrics:
        episodes = self.recent(500)
        total = len(episodes)
        completed = sum(ep.outcome != "unknown" for ep in episodes)
        successes = sum(ep.outcome == "success" for ep in episodes)
        feedback = sum(bool(ep.feedback) for ep in episodes)
        evidence = sum(bool(ep.evidence) for ep in episodes)
        checked = sum(ep.regression_checked for ep in episodes)
        return ConsequenceMetrics(total=total, completed=completed, successes=successes,
            partials=sum(ep.outcome == "partial" for ep in episodes), failures=sum(ep.outcome == "failure" for ep in episodes),
            blocked=sum(ep.outcome == "blocked" for ep in episodes), unknown=sum(ep.outcome == "unknown" for ep in episodes),
            success_rate=successes / max(1, completed), feedback_rate=feedback / max(1, total),
            evidence_rate=evidence / max(1, total),
            average_confidence_delta=sum(ep.confidence_after - ep.confidence_before for ep in episodes) / max(1, total),
            regression_checked_rate=checked / max(1, total))

    def verify_integrity(self) -> bool:
        rows = self.connection.execute("SELECT episode_id, record_json, content_hash FROM consequence_episodes ORDER BY created_at, episode_id").fetchall()
        for row in rows:
            record = ConsequenceEpisode.model_validate(json.loads(row[1]))
            expected = record.model_copy(update={"content_hash": ""}).seal().content_hash
            if expected != row[2] or expected != record.content_hash:
                return False
        return True

    def _replace_episode(self, episode: ConsequenceEpisode) -> None:
        payload = json.dumps(episode.model_dump(mode="json"), ensure_ascii=False, sort_keys=True)
        with self.connection:
            self.connection.execute("UPDATE consequence_episodes SET outcome=?, outcome_summary=?, confidence_before=?, confidence_after=?, regression_checked=?, regression_score=?, completed_at=?, content_hash=?, record_json=? WHERE episode_id=?",
                (episode.outcome, episode.outcome_summary, episode.confidence_before, episode.confidence_after, int(episode.regression_checked), episode.regression_score, episode.completed_at, episode.content_hash, payload, episode.episode_id))

    def _event(self, episode_id: str, event_type: str, payload: dict[str, Any]) -> None:
        data = {"episode_id": episode_id, "event_type": event_type, "payload": payload, "created_at": utc_now()}
        self.connection.execute("INSERT INTO consequence_events(event_id, episode_id, event_type, payload_json, created_at, content_hash) VALUES (?, ?, ?, ?, ?, ?)",
            (f"event-{uuid.uuid4().hex[:20]}", episode_id, event_type, json.dumps(payload, ensure_ascii=False, sort_keys=True), data["created_at"], canonical_hash(data)))
