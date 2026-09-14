from __future__ import annotations

import json

import pytest

from scripts.run_wifi_csi_presence import run_file


def _write_frame(path, token: str) -> None:
    path.write_text(json.dumps({
        "timestamp_ms": 1,
        "amplitudes": [1.0, 1.1, 0.9],
        "phases": [0.1, 0.2, 0.0],
        "device_id": "lab-node",
        "location_label": "authorized-lab",
        "consent_token": token,
    }) + "\n", encoding="utf-8")


def test_cli_requires_matching_consent(tmp_path):
    source = tmp_path / "frames.jsonl"
    _write_frame(source, "valid-token")
    result = run_file(source, "valid-token", "presence_sensing")
    assert result["privacy_contract"]["consent_required"] is True
    assert result["privacy_contract"]["raw_frames_persisted"] is False


def test_cli_aborts_on_invalid_consent(tmp_path):
    source = tmp_path / "frames.jsonl"
    _write_frame(source, "wrong-token")
    with pytest.raises(PermissionError):
        run_file(source, "valid-token", "presence_sensing")
