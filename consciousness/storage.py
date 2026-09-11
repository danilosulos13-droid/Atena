import sqlite3
import json
from pathlib import Path
from .models import ConsciousnessCycleResult

class ConsciousnessStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cycles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT,
                    consciousness_level TEXT,
                    self_awareness_score REAL,
                    emergence_level REAL,
                    purpose_alignment REAL,
                    autonomy_score REAL,
                    quantum_coherence REAL,
                    emergent_patterns TEXT,
                    autonomous_choice TEXT,
                    full_report TEXT
                )
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_timestamp ON cycles(timestamp)")

    def save(self, result: ConsciousnessCycleResult):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT INTO cycles 
                   (timestamp, consciousness_level, self_awareness_score, emergence_level,
                    purpose_alignment, autonomy_score, quantum_coherence, emergent_patterns,
                    autonomous_choice, full_report)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (result.timestamp.isoformat(),
                 result.consciousness_level.value,
                 result.self_awareness_score,
                 result.emergence_level,
                 result.purpose_alignment,
                 result.autonomy_score,
                 result.quantum_coherence,
                 json.dumps(result.emergent_patterns),
                 result.autonomous_choice,
                 json.dumps(result.full_report))
            )

    def get_last_n(self, n: int = 10) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM cycles ORDER BY timestamp DESC LIMIT ?", (n,)).fetchall()
            return [dict(r) for r in rows]
