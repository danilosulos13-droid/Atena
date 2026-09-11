from __future__ import annotations

import math
from dataclasses import dataclass

from core.math_solver import MathResult, solve_math_text, solve_wifi_puzzle


@dataclass(frozen=True)
class Question:
    number: int
    prompt: str
    expected_contains: tuple[str, ...] = ()
    expected_value: float | None = None
    tolerance: float = 1e-10
    wifi: bool = False


EXAM = (
    Question(1, "37*24+18", expected_value=906.0),
    Question(2, "3/4 + 5/8", expected_value=1.375),
    Question(3, "240*15/100", expected_value=36.0),
    Question(4, "2*x + 7 = 19", expected_contains=("6",)),
    Question(5, "x^2 - 5*x + 6 = 0", expected_contains=("2", "3")),
    Question(6, "3*x - 4 = 2*x + 9", expected_contains=("13",)),
    Question(7, "(2^5 - 8)/3", expected_value=8.0),
    Question(8, "wifi", wifi=True, expected_value=0.002169625467, tolerance=1e-12),
)


def numeric_answer(result: MathResult) -> float:
    return float(result.answer.split()[0])


def solve(question: Question) -> MathResult:
    return solve_wifi_puzzle() if question.wifi else solve_math_text(question.prompt)


def main() -> int:
    passed = 0
    print("ATENA — prova matemática")
    print("=" * 40)
    for question in EXAM:
        try:
            result = solve(question)
            answer = result.answer
            if question.expected_value is not None:
                ok = math.isclose(numeric_answer(result), question.expected_value, rel_tol=0, abs_tol=question.tolerance)
            else:
                ok = all(token in answer for token in question.expected_contains)
            status = "PASSOU" if ok else "FALHOU"
            if ok:
                passed += 1
            print(f"{question.number}. {question.prompt} -> {answer} [{status}]")
        except Exception as exc:
            print(f"{question.number}. {question.prompt} -> ERRO: {type(exc).__name__}: {exc} [FALHOU]")
    print("=" * 40)
    print(f"Resultado: {passed}/{len(EXAM)} questões corretas")
    return 0 if passed == len(EXAM) else 1


if __name__ == "__main__":
    raise SystemExit(main())
