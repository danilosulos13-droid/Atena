"""Avaliação segura de candidatos LoRA e promoção/rollback.

O avaliador usa um holdout congelado derivado do dataset SFT. Nunca substitui o
modelo base: um candidato só pode ser marcado como promovível quando melhora a
perda no holdout por uma margem mínima e não apresenta regressão mensurável.
A promoção efetiva é feita apenas trocando o ponteiro para o adapter aprovado.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
EVOLUTION = ROOT / "atena_evolution"
DATASET = EVOLUTION / "training" / "sft.jsonl"
MODELS = EVOLUTION / "models"
STATE = EVOLUTION / "model_promotion_state.json"
ACTIVE = MODELS / "active"


@dataclass(frozen=True)
class ModelMetrics:
    model: str
    examples: int
    loss: float
    perplexity: float


@dataclass(frozen=True)
class PromotionResult:
    decision: str
    reason: str
    baseline: dict[str, Any] | None
    candidate: dict[str, Any] | None
    improvement: float
    active_path: str | None = None


def _load_rows(limit: int = 256) -> list[dict[str, Any]]:
    if not DATASET.exists():
        return []
    rows = []
    for line in DATASET.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict) and row.get("messages"):
            rows.append(row)
    # Deterministic ordering avoids evaluation drift caused by append order.
    rows.sort(key=lambda r: hashlib.sha256(str(r.get("id", "")).encode()).hexdigest())
    return rows[:limit]


def build_holdout(rows: list[dict[str, Any]], fraction: float = 0.2) -> list[dict[str, Any]]:
    if len(rows) < 5:
        return []
    holdout = [r for r in rows if int(hashlib.sha256(str(r.get("id", "")).encode()).hexdigest()[:8], 16) % 10 < max(1, round(fraction * 10))]
    if not holdout:
        holdout = rows[-max(1, len(rows) // 5):]
    return holdout


def _render(row: dict[str, Any]) -> str:
    return "\n".join(f"{m.get('role', 'user')}: {m.get('content', '')}" for m in row.get("messages", []))


def evaluate_model(model_name: str, rows: list[dict[str, Any]], *, adapter: str | None = None, max_length: int = 1024) -> ModelMetrics:
    """Calcula NLL médio em CPU/GPU usando Transformers; dependências são opcionais."""
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer

    tokenizer = AutoTokenizer.from_pretrained(model_name, use_fast=True)
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token
    model = AutoModelForCausalLM.from_pretrained(model_name, torch_dtype="auto")
    if adapter:
        from peft import PeftModel
        model = PeftModel.from_pretrained(model, adapter)
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model.to(device)
    model.eval()

    total_loss = 0.0
    total_tokens = 0
    with torch.no_grad():
        for row in rows:
            enc = tokenizer(_render(row), truncation=True, max_length=max_length, return_tensors="pt")
            input_ids = enc["input_ids"].to(device)
            attention = enc.get("attention_mask")
            if attention is not None:
                attention = attention.to(device)
            labels = input_ids.clone()
            if attention is not None:
                labels[attention == 0] = -100
            out = model(input_ids=input_ids, attention_mask=attention, labels=labels)
            valid = int((labels != -100).sum().item())
            total_loss += float(out.loss.item()) * max(valid, 1)
            total_tokens += max(valid, 1)
    loss = total_loss / max(total_tokens, 1)
    return ModelMetrics(model_name + (f"+{adapter}" if adapter else ""), len(rows), loss, math.exp(min(loss, 20)))


def promote_candidate(candidate_path: Path, *, base_model: str, metrics: PromotionResult) -> Path:
    """Promove somente o adapter aprovado, preservando candidatos anteriores."""
    ACTIVE.parent.mkdir(parents=True, exist_ok=True)
    backup = MODELS / "previous_active"
    if ACTIVE.exists():
        if backup.exists():
            shutil.rmtree(backup)
        ACTIVE.rename(backup)
    shutil.copytree(candidate_path, ACTIVE)
    # O estado persistido precisa apontar para o adapter efetivamente publicado.
    # Use um caminho relativo para continuar válido fora do runner do CI.
    active_path = str(Path(EVOLUTION.name) / "models" / ACTIVE.name)
    state = {
        "status": "active",
        "base_model": base_model,
        "promoted_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
        "evaluation": {**asdict(metrics), "active_path": active_path},
        "rollback_path": str(backup) if backup.exists() else None,
    }
    STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return ACTIVE


def evaluate_and_maybe_promote(*, base_model: str, candidate_path: Path = MODELS / "candidate", min_improvement: float | None = None, max_holdout: int = 256) -> PromotionResult:
    rows = _load_rows(max_holdout)
    holdout = build_holdout(rows)
    if len(holdout) < 5:
        return PromotionResult("blocked", "holdout insuficiente (mínimo 5 exemplos)", None, None, 0.0)
    if not candidate_path.exists():
        return PromotionResult("blocked", "candidato inexistente", None, None, 0.0)

    threshold = float(os.getenv("ATENA_MIN_EVAL_IMPROVEMENT", "0.02")) if min_improvement is None else min_improvement
    baseline = evaluate_model(base_model, holdout, max_length=int(os.getenv("ATENA_EVAL_MAX_LENGTH", "1024")))
    candidate = evaluate_model(base_model, holdout, adapter=str(candidate_path), max_length=int(os.getenv("ATENA_EVAL_MAX_LENGTH", "1024")))
    improvement = (baseline.loss - candidate.loss) / max(abs(baseline.loss), 1e-9)
    if not math.isfinite(improvement) or improvement < threshold:
        return PromotionResult("blocked", f"melhoria insuficiente: {improvement:.2%} < {threshold:.2%}", asdict(baseline), asdict(candidate), improvement)

    result = PromotionResult("promote", f"melhoria no holdout: {improvement:.2%}", asdict(baseline), asdict(candidate), improvement)
    active = promote_candidate(candidate_path, base_model=base_model, metrics=result)
    return PromotionResult(result.decision, result.reason, result.baseline, result.candidate, result.improvement, str(active))
