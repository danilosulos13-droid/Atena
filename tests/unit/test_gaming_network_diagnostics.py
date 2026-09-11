from scripts.gaming_network_diagnostics import PingResult, recommendations


def test_recommendations_flag_packet_loss_and_high_latency():
    result = PingResult("1.1.1.1", 5, 4, 20.0, 40.0, 120.0, 220.0)
    suggestions = recommendations(result, {"error": None}, {"available": True})
    assert any("perda de pacotes" in item for item in suggestions)
    assert any("latência média" in item for item in suggestions)
    assert any("jitter" in item for item in suggestions)


def test_recommendations_are_safe_when_connection_is_stable():
    result = PingResult("1.1.1.1", 5, 5, 0.0, 12.0, 18.0, 24.0)
    suggestions = recommendations(result, {"error": None}, {"available": True})
    assert suggestions == ["A conexão parece estável neste teste; não há ajuste automático recomendado."]
