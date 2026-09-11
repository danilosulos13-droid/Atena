"""Small programming-specialist demonstration generated for ATENA validation."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    value: int | None = None
    error: str | None = None


def parse_positive_int(value: Any) -> ValidationResult:
    """Parse a positive integer without leaking conversion exceptions."""
    try:
        if isinstance(value, bool):
            raise ValueError("boolean is not an integer input")
        number = int(value)
    except (TypeError, ValueError):
        return ValidationResult(False, error="value must be an integer")
    if number <= 0:
        return ValidationResult(False, error="value must be positive")
    return ValidationResult(True, value=number)


def bounded_percentage(value: Any) -> float:
    """Validate a percentage in the inclusive [0, 100] interval."""
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("percentage must be numeric") from exc
    if not 0 <= number <= 100:
        raise ValueError("percentage must be between 0 and 100")
    return number


if __name__ == "__main__":
    assert parse_positive_int("8").value == 8
    assert not parse_positive_int(-1).valid
    assert bounded_percentage("42.5") == 42.5
    print("programming-specialist-demo: OK")
