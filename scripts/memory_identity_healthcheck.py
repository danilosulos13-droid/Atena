"""Healthcheck seguro dos caminhos de memória e identidade da Atena."""
from __future__ import annotations

import argparse
import importlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

MODULES = (
    "core.episodic_memory",
    "core.memory_store",
    "core.memory_retrieval",
    "core.memory_consolidation",
    "core.identity_state",
    "core.sensemaking",
    "modules.graph_memory",
)


def run(root: Path = ROOT) -> dict[str, object]:
    imports: dict[str, str] = {}
    for name in MODULES:
        try:
            importlib.import_module(name)
            imports[name] = "ok"
        except Exception as exc:  # noqa: BLE001
            imports[name] = f"error:{type(exc).__name__}:{exc}"

    with tempfile.TemporaryDirectory(prefix="atena-memory-health-") as temp:
        from core.identity_state import IdentityStateStore
        from core.memory_store import MemoryStore

        memory_path = Path(temp) / "memory.sqlite3"
        with MemoryStore(memory_path) as store:
            episode_id = store.add_simple(
                output="healthcheck episódico",
                task_id="healthcheck",
                domain="memory",
                source_type="benchmark",
                source_id="memory_identity_healthcheck",
                system_version="healthcheck-1",
                confidence=0.8,
                status="supported",
            )
            integrity = store.verify_integrity()
        identity_path = Path(temp) / "identity.sqlite3"
        with IdentityStateStore(identity_path) as identity:
            snapshot = identity.upsert("healthcheck", current_state="ready")
            event_hash = identity.append_event("healthcheck", "healthcheck", {"ok": True})
            identity_chain = identity.verify_events("healthcheck")

    legacy_warning = False
    legacy_path = root / "atena_evolution" / "conversation_memory.json"
    if legacy_path.exists():
        try:
            data = json.loads(legacy_path.read_text(encoding="utf-8"))
            legacy_warning = any("<coroutine object" in str(item.get("assistant", "")) for item in data.get("history", []))
        except (OSError, json.JSONDecodeError):
            legacy_warning = True

    return {
        "imports": imports,
        "episodic": {"ok": bool(episode_id) and bool(integrity), "episode_id": episode_id, "chain_head": integrity},
        "identity": {"ok": bool(snapshot.content_hash) and event_hash == identity_chain, "version": snapshot.version, "chain_head": identity_chain},
        "legacy_conversation_warning": legacy_warning,
        "production_databases_modified": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    result = run(args.root)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if all(value == "ok" for value in result["imports"].values()) and result["episodic"]["ok"] and result["identity"]["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
