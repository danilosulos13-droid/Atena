"""Consolidação segura da memória legada da Atena.

A rotina nunca apaga episódios brutos. Ela produz uma visão derivada para
contexto e análise, agrupando repetições por uma chave normalizada e mantendo
primeira ocorrência, última ocorrência, contagem e ciclos de origem.
"""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Iterable


def normalize_text(value: Any) -> str:
    text = unicodedata.normalize("NFKC", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip().casefold()
    return text


def item_key(kind: str, value: Any) -> str:
    normalized = normalize_text(value)
    digest = hashlib.sha256(f"{kind}\0{normalized}".encode("utf-8")).hexdigest()
    return f"{kind}:{digest[:24]}"


def _bucket() -> dict[str, dict[str, Any]]:
    return {}


def _add(bucket: dict[str, dict[str, Any]], kind: str, value: Any, cycle: dict[str, Any], index: int) -> None:
    text = str(value).strip()
    if not text:
        return
    key = item_key(kind, text)
    timestamp = cycle.get("timestamp")
    entry = bucket.get(key)
    if entry is None:
        bucket[key] = {
            "key": key,
            "kind": kind,
            "text": text,
            "first_seen": timestamp,
            "last_seen": timestamp,
            "seen_count": 1,
            "cycle_indexes": [index],
        }
    else:
        entry["last_seen"] = timestamp
        entry["seen_count"] += 1
        if index not in entry["cycle_indexes"]:
            entry["cycle_indexes"].append(index)


def consolidate_cycles(cycles: Iterable[dict[str, Any]]) -> dict[str, Any]:
    cycles = list(cycles)
    buckets = {kind: _bucket() for kind in ("insight", "risk", "next_cycle", "proposal")}
    proposal_files: dict[str, dict[str, Any]] = {}
    for index, cycle in enumerate(cycles):
        observations = cycle.get("observations", {}) if isinstance(cycle, dict) else {}
        for value in observations.get("insights", []):
            _add(buckets["insight"], "insight", value, cycle, index)
        for value in observations.get("risks", []):
            _add(buckets["risk"], "risk", value, cycle, index)
        for value in observations.get("next_cycle", []):
            _add(buckets["next_cycle"], "next_cycle", value, cycle, index)
        for proposal in observations.get("proposed_changes", []):
            if not isinstance(proposal, dict):
                continue
            filename = str(proposal.get("file", "")).strip()
            if not filename:
                continue
            normalized_file = normalize_text(filename)
            entry = proposal_files.get(normalized_file)
            if entry is None:
                entry = {
                    "key": item_key("proposal", normalized_file),
                    "kind": "proposal",
                    "file": filename,
                    "rationales": [],
                    "tests": [],
                    "first_seen": cycle.get("timestamp"),
                    "last_seen": cycle.get("timestamp"),
                    "seen_count": 0,
                    "cycle_indexes": [],
                }
                proposal_files[normalized_file] = entry
            entry["seen_count"] += 1
            entry["last_seen"] = cycle.get("timestamp")
            if index not in entry["cycle_indexes"]:
                entry["cycle_indexes"].append(index)
            rationale = str(proposal.get("rationale", "")).strip()
            if rationale and rationale not in entry["rationales"]:
                entry["rationales"].append(rationale)
            for test in proposal.get("tests", []):
                test = str(test).strip()
                if test and test not in entry["tests"]:
                    entry["tests"].append(test)

    generated = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": 1,
        "generated_at": generated,
        "source_cycle_count": len(cycles),
        "insights": sorted(buckets["insight"].values(), key=lambda x: (x["first_seen"] or "", x["key"])),
        "risks": sorted(buckets["risk"].values(), key=lambda x: (x["first_seen"] or "", x["key"])),
        "next_cycle": sorted(buckets["next_cycle"].values(), key=lambda x: (x["first_seen"] or "", x["key"])),
        "proposals": sorted(proposal_files.values(), key=lambda x: (x["first_seen"] or "", x["key"])),
    }


def compact_context(cycles: Iterable[dict[str, Any]], max_items: int = 30) -> dict[str, Any]:
    consolidated = consolidate_cycles(cycles)
    for key in ("insights", "risks", "next_cycle", "proposals"):
        values = consolidated[key]
        consolidated[key] = sorted(values, key=lambda item: (-int(item.get("seen_count", 0)), item.get("last_seen") or ""))[:max_items]
    return consolidated
