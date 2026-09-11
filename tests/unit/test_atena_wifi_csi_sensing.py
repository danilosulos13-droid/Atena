from core.atena_wifi_csi_sensing import (
    CSIFrame,
    SensingPolicy,
    WifiCSISensingEngine,
    build_demo_report,
    generate_synthetic_csi_stream,
)


def test_wifi_csi_demo_detects_motion_with_privacy_warnings() -> None:
    payload = build_demo_report(motion=True)

    assert payload["capability"] == "wifi_csi_presence_sensing_lab"
    assert payload["status"] in {"motion", "possible_presence"}
    assert payload["frames"] == 6
    assert payload["average_confidence"] > 0
    assert "consentida" in payload["safety_note"]
    assert all("no_hidden_surveillance" in item["warnings"] for item in payload["results"])


def test_wifi_csi_policy_blocks_non_consented_frame() -> None:
    engine = WifiCSISensingEngine(SensingPolicy(consent_token="expected-token"))
    frame = CSIFrame(timestamp_ms=1, amplitudes=[1.0, 2.0], phases=[0.1, 0.2], consent_token="wrong")

    result = engine.analyze_frame(frame)

    assert result.status == "blocked_by_policy"
    assert result.confidence == 0.0
    assert "missing_or_invalid_consent" in result.warnings


def test_wifi_csi_stream_summary_clear_when_no_motion() -> None:
    engine = WifiCSISensingEngine()
    payload = engine.analyze_stream(generate_synthetic_csi_stream(frames=4, motion=False))

    assert payload["frames"] == 4
    assert payload["blocked_frames"] == 0
    assert payload["status"] in {"clear", "possible_presence"}
    assert payload["motion_frames"] == 0


def test_wifi_csi_phase_unwrap_is_centered() -> None:
    unwrapped = WifiCSISensingEngine.unwrap_phase([3.0, -3.1, -3.0, 3.12])

    assert len(unwrapped) == 4
    assert abs(sum(unwrapped)) < 1e-6
