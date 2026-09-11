from __future__ import annotations

from core.math_solver import solve_and_verify, verify_math_result


def test_arithmetic_is_recalculated() -> None:
    result = solve_and_verify("2*(3+4)")
    assert "confirmada" in result.verification
    assert "recalculada" in result.verification


def test_equation_solution_is_substituted() -> None:
    result = solve_and_verify("2*x + 1 = 7")
    assert "x: 3" in result.answer
    assert "substituídas" in result.verification


def test_system_solution_is_checked_in_all_equations() -> None:
    result = solve_and_verify("2*x + y = 7; x - y = 2")
    assert "x: 3" in result.answer and "y: 1" in result.answer
    assert "todas as equações" in result.verification


def test_wifi_value_is_checked_with_tolerance() -> None:
    result = solve_and_verify("wifi")
    ok, message = verify_math_result("wifi", result)
    assert ok
    assert "tolerância" in message
