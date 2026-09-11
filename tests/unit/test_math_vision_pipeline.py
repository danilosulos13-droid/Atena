import json
from pathlib import Path

from core.math_vision_pipeline import format_math_solution


def test_format_math_solution_includes_answer_and_checks():
    text = format_math_solution({
        "transcription": "integral",
        "interpretation": "limites",
        "solution": "passos",
        "numeric_answer": "0.25",
        "first_digits": "025",
        "checks": ["verificação independente"],
        "memory_hits": [{"id": "x"}],
    })
    assert "0.25" in text
    assert "025" in text
    assert "verificação independente" in text
    assert "resolução(ões) semelhante(s)" in text
