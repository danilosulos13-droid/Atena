from __future__ import annotations

import math

import pytest

from core.math_solver import MathSolverError, solve_math_text, solve_wifi_puzzle


def test_safe_arithmetic() -> None:
    result = solve_math_text("2*(3+4)")
    assert result.answer == "14"
    assert result.exact


def test_rejects_code() -> None:
    with pytest.raises(MathSolverError):
        solve_math_text("__import__('os').system('id')")


def test_wifi_puzzle_reference_value() -> None:
    result = solve_wifi_puzzle()
    value = float(result.answer.split()[0])
    assert math.isclose(value, 0.002169625467, rel_tol=0, abs_tol=1e-12)
    assert "A série inferior soma 0" in result.format()
