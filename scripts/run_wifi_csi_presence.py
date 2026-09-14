#!/usr/bin/env python3
"""Executa análise de presença Wi-Fi CSI com consentimento obrigatório.

O script não captura interfaces, não faz varredura de rede e não identifica
pessoas. Recebe frames CSI já autorizados em JSONL, valida o token em cada
frame e grava somente o resumo agregado.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atena_wifi_csi_sensing import CSIFrame, SensingPolicy, WifiCSISensingEngine, build_demo_report


def _frame(item: dict[str, Any]) -> CSIFrame:
    required = ("timestamp_ms", "amplitudes", "phases", "consent_token")
    missing = [key for key in required if key not in item]
    if missing:
        raise ValueError(f"frame sem campos obrigatórios: {', '.join(missing)}")
    return CSIFrame(
        timestamp_ms=int(item["timestamp_ms"]),
        amplitudes=item["amplitudes"],
        phases=item["phases"],
        device_id=str(item.get("device_id", "csi-node")),
        location_label=str(item.get("location_label", "authorized-lab")),
        consent_token=str(item["consent_token"]),
    )


def run_file(path: Path, consent_token: str, mode: str) -> dict[str, Any]:
    if not consent_token.strip():
        raise ValueError("token de consentimento obrigatório")
    frames = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"JSON inválido na linha {number}") from exc
        if not isinstance(item, dict):
            raise ValueError(f"frame inválido na linha {number}")
        frame = _frame(item)
        if frame.consent_token != consent_token:
            raise PermissionError(f"consentimento inválido na linha {number}; processamento abortado")
        frames.append(frame)
    engine = WifiCSISensingEngine(SensingPolicy(consent_token=consent_token, require_consent=True), mode=mode)
    result = engine.analyze_stream(frames)
    result["privacy_contract"] = {
        "consent_required": True,
        "raw_frames_persisted": False,
        "identity_inference": False,
        "hidden_surveillance": False,
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--input-jsonl", type=Path, help="frames CSI autorizados, um JSON por linha")
    source.add_argument("--demo", action="store_true", help="executa somente o demo sintético consentido")
    parser.add_argument("--consent-token", default=os.getenv("ATENA_WIFI_CSI_CONSENT_TOKEN", ""))
    parser.add_argument("--mode", default="presence_sensing", choices=("motion_detection", "presence_sensing", "occupancy_tracking", "activity_recognition", "environmental_monitoring"))
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.demo:
        result = build_demo_report(motion=True)
    else:
        result = run_file(args.input_jsonl, args.consent_token, args.mode)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
