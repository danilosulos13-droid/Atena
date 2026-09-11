from __future__ import annotations

import math

import pytest

from core.math_solver import MathSolverError, solve_math_text, solve_wifi_puzzle


@pytest.mark.parametrize(
    ("problem", "expected"),
    [
        ("0", 0.0),
        ("2+2", 4.0),
        ("10-3*2", 4.0),
        ("(10-3)*2", 14.0),
        ("144/12", 12.0),
        ("2^10", 1024.0),
        ("17%5", 2.0),
        ("-3.5 + 2", -1.5),
        ("2 × 3 ÷ 4", 1.5),
        ("1,25 + 2,75", 4.0),
    ],
)
def test_arithmetic_cases(problem: str, expected: float) -> None:
    result = solve_math_text(problem)
    assert math.isclose(float(result.answer), expected, rel_tol=0, abs_tol=1e-12)
    assert result.exact
    assert result.steps


@pytest.mark.parametrize("problem", [
    "__import__('os')",
    "open('/tmp/file')",
    "2**1001",
    "2/0",
    "2 + segredo",
    "",
])
def test_invalid_or_unsafe_cases_are_rejected(problem: str) -> None:
    with pytest.raises(MathSolverError):
        solve_math_text(problem)


def test_equation_when_sympy_is_available() -> None:
    pytest.importorskip("sympy")
    result = solve_math_text("2*x + 1 = 7")
    assert "x" in result.answer
    assert "3" in result.answer
    assert result.exact


def test_multi_variable_equation_when_sympy_is_available() -> None:
    pytest.importorskip("sympy")
    result = solve_math_text("x + y = 10")
    assert "x" in result.answer and "y" in result.answer


def test_wifi_solution_is_stable_and_has_explanation() -> None:
    result = solve_wifi_puzzle()
    value = float(result.answer.split()[0])
    assert math.isclose(value, 0.002169625467, rel_tol=0, abs_tol=1e-12)
    assert len(result.steps) == 4
    assert "1/15" in " ".join(result.steps)


def test_natural_language_prefixes() -> None:
    assert solve_math_text("Calcule 8*8").answer == "64"
    assert solve_math_text("quanto é 81/9").answer == "9"
