from __future__ import annotations

import sympy as sp

from core.math_solver import solve_math_text


EXAM = [
    ("Derivada: d/dx de x^3 + 2*x^2 - 5*x", "3*x**2 + 4*x - 5"),
    ("Integral indefinida: integral de 2*x + 1", "x**2 + x"),
    ("Integral definida: integral de x^2 de x = 0 a 1", "1/3"),
    ("Limite: limite de sin(x)/x quando x tende a 0", "1"),
    ("Equação quadrática: x^2 - 5*x + 6 = 0", "[{x: 2}, {x: 3}]"),
    ("Sistema: 2*x + y = 7; x - y = 2", "[{x: 3, y: 1}]"),
]


def normalize(value: str) -> str:
    return value.replace(" ", "").replace("**", "^")


def main() -> int:
    passed = 0
    print("ATENA — prova universitária de matemática")
    print("=" * 60)
    for label, expected in EXAM:
        problem = label.split(": ", 1)[1]
        result = solve_math_text(problem)
        actual = result.answer
        # A comparação simbólica é independente da formatação textual do SymPy.
        if "x:" in expected or "y:" in expected:
            ok = normalize(actual) == normalize(expected)
        else:
            try:
                ok = sp.simplify(sp.sympify(actual) - sp.sympify(expected)) == 0
            except Exception:
                ok = normalize(actual) == normalize(expected)
        status = "PASSOU" if ok else "FALHOU"
        passed += int(ok)
        print(f"{label} -> {actual} [{status}]")
    print("=" * 60)
    print(f"Resultado: {passed}/{len(EXAM)} questões corretas")
    return 0 if passed == len(EXAM) else 1


if __name__ == "__main__":
    raise SystemExit(main())
