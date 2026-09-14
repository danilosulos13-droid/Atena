#!/usr/bin/env python3
"""Teste local e determinístico de presença usando um payload CSI sintético.

Não acessa Wi-Fi, Telegram, câmera, microfone ou rede. Aceita um JSON com um
frame CSI ou uma lista em ``frames`` e executa o processador da Atena.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.atena_wifi_csi_sensing import CSIFrame, WifiCSISensingEngine


SAMPLE_PAYLOAD: dict[str, Any] = {
    "type": "wifi_csi",
    "timestamp_ms": 1800000000000,
    "amplitudes": [0.20, 1.80, 0.35, 1.65, 0.25, 1.90],
    "phases": [0.12, 2.10, -1.40, 1.80, -2.00, 2.40],
    "device_id": "synthetic-phone",
    "location_label": "local-test",
}


def _as_frames(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_frames = payload.get("frames")
    if raw_frames is None:
        raw_frames = [payload]
    if not isinstance(raw_frames, list) or not raw_frames:
        raise ValueError("o payload deve conter um frame ou uma lista não vazia em 'frames'")
    if not all(isinstance(item, dict) for item in raw_frames):
        raise ValueError("cada item de 'frames' deve ser um objeto JSON")
    return raw_frames


def _make_frame(item: dict[str, Any], index: int) -> CSIFrame:
    for field in ("timestamp_ms", "amplitudes", "phases"):
        if field not in item:
            raise ValueError(f"frame {index}: campo obrigatório ausente: {field}")
    return CSIFrame(
        timestamp_ms=int(item["timestamp_ms"]),
        amplitudes=item["amplitudes"],
        phases=item["phases"],
        device_id=str(item.get("device_id", "synthetic-device")),
        location_label=str(item.get("location_label", "local-test")),
        consent_token=item.get("consent_token"),
    )


def process_payload(payload: dict[str, Any]) -> dict[str, Any]:
    frames = [_make_frame(item, index) for index, item in enumerate(_as_frames(payload), 1)]
    engine = WifiCSISensingEngine(mode="presence_sensing")
    result = engine.analyze_stream(frames)
    return {
        "test": "synthetic_csi_presence",
        "input_type": payload.get("type", "wifi_csi"),
        "input_frames": len(frames),
        "detection": result,
        "interpretation": {
            "presence_detected": result["status"] in {"possible_presence", "motion"},
            "motion_detected": result["motion_frames"] > 0,
            "confidence": result["average_confidence"],
            "note": "Resultado experimental sobre CSI sintético; não identifica pessoas nem prova ocupação real.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, help="arquivo JSON; se omitido, usa payload sintético interno")
    parser.add_argument("--output", type=Path, help="salva o resultado JSON neste caminho")
    args = parser.parse_args()

    if args.input:
        payload = json.loads(args.input.read_text(encoding="utf-8"))
    else:
        payload = SAMPLE_PAYLOAD
    if not isinstance(payload, dict):
        raise SystemExit("o JSON de entrada precisa ser um objeto")

    result = process_payload(payload)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding="utf-8")
    print(text, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
