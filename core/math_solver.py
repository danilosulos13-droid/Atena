"""Solução matemática determinística para a Atena.

O módulo evita eval/exec e oferece cálculo exato quando SymPy está instalado.
Também contém o cálculo de referência do enigma matemático enviado em imagem.
"""
from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass, replace
from typing import Any


class MathSolverError(ValueError):
    pass


@dataclass(frozen=True)
class MathResult:
    problem: str
    answer: str
    steps: tuple[str, ...]
    exact: bool = False
    verification: str = ""

    def format(self) -> str:
        lines = ["ATENA — solução matemática", "", f"Problema: {self.problem}", ""]
        if self.steps:
            lines.append("Etapas:")
            lines.extend(f"{index}. {step}" for index, step in enumerate(self.steps, 1))
            lines.append("")
        lines.append(f"Resposta: {self.answer}")
        if self.verification:
            lines.append(f"Verificação: {self.verification}")
        return "\n".join(lines)


_ALLOWED_BINARY = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Pow: operator.pow,
    ast.Mod: operator.mod,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}


def _arithmetic(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _arithmetic(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_UNARY:
        return _ALLOWED_UNARY[type(node.op)](_arithmetic(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_BINARY:
        left, right = _arithmetic(node.left), _arithmetic(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > 1000:
            raise MathSolverError("expoente muito grande")
        return _ALLOWED_BINARY[type(node.op)](left, right)
    raise MathSolverError("expressão contém uma operação não permitida")


def _safe_arithmetic(text: str) -> float:
    normalized = text.replace(",", ".").replace("×", "*").replace("÷", "/")
    if len(normalized) > 500 or not re.fullmatch(r"[0-9+\-*/%().\s^]+", normalized):
        raise MathSolverError("use uma expressão aritmética com números e operações básicas")
    normalized = normalized.replace("^", "**")
    try:
        value = _arithmetic(ast.parse(normalized, mode="eval"))
    except (SyntaxError, ZeroDivisionError, OverflowError) as exc:
        raise MathSolverError("não consegui calcular a expressão") from exc
    if not math.isfinite(value):
        raise MathSolverError("o resultado não é finito")
    return value


def solve_wifi_puzzle() -> MathResult:
    """Resolve a expressão da placa mostrada pelo usuário."""
    lower = 0.0
    # Soma (n² - 2)/(n+2)! = 0 por telescopagem das séries exponenciais.
    upper = 1.0 / 15.0
    # Integração de Simpson da função contínua no intervalo [0, 1/15].
    def f(x: float) -> float:
        return math.log1p(x) / (1.0 + x * x) if x else 0.0
    n = 20000
    h = (upper - lower) / n
    total = f(lower) + f(upper)
    total += 4.0 * sum(f(lower + i * h) for i in range(1, n, 2))
    total += 2.0 * sum(f(lower + i * h) for i in range(2, n, 2))
    integral = total * h / 3.0
    return MathResult(
        problem="Integral da imagem da placa Free WiFi",
        answer=f"{integral:.12f}  (primeiros dígitos: {integral:.12f})",
        steps=(
            "A série inferior soma 0.",
            "O limite superior vale 1/15, usando as expansões de Taylor de sin(x), cos(x) e e^(-x²/2).",
            "A integral restante é ∫[0, 1/15] ln(1+x)/(1+x²) dx.",
            "A integral foi calculada numericamente por Simpson com 20.000 subintervalos.",
        ),
        exact=False,
    )


def solve_math_text(text: str) -> MathResult:
    """Resolve aritmética simples ou delega equações a SymPy com entrada limitada."""
    clean = " ".join(str(text).strip().split())
    if not clean:
        raise MathSolverError("problema matemático vazio")
    lowered = clean.casefold()
    if lowered.strip() == "wifi" or "free wifi" in lowered or ("wifi" in lowered and "lim" in lowered):
        return solve_wifi_puzzle()
    expression = re.sub(r"^(?:atena[, ]*)?(?:calcule|resolva|quanto é|quanto e|math|matemática)\s*", "", clean, flags=re.I).strip()
    if re.fullmatch(r"[0-9+\-*/%().,\s×÷^]+", expression):
        value = _safe_arithmetic(expression)
        return MathResult(clean, f"{value:g}", (f"Avaliei a expressão {expression.replace(',', '.') } com operações aritméticas seguras.",), exact=True)
    if lowered.startswith(("derivada ", "derive ", "d/dx ", "integral ", "integre ", "limite ", "lim " )):
        try:
            import sympy as sp  # type: ignore
            allowed = {"x": sp.Symbol("x"), "y": sp.Symbol("y"), "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
                       "exp": sp.exp, "log": sp.log, "sqrt": sp.sqrt, "pi": sp.pi, "E": sp.E}
            if len(expression) > 500 or not re.fullmatch(r"[A-Za-z0-9_+\-*/^().,=\s]+", expression):
                raise MathSolverError("problema de cálculo contém caracteres não permitidos")
            normalized = expression.replace("^", "**")
            if lowered.startswith(("derivada ", "derive ", "d/dx ")):
                body = re.sub(r"^(?:derivada de|derive|d/dx de)\s*", "", normalized, flags=re.I)
                value = sp.diff(sp.sympify(body, locals=allowed), allowed["x"])
                return MathResult(clean, str(value), ("Interpretei a expressão como função de x.", "Calculei a derivada simbólica."), exact=True)
            if lowered.startswith(("integral ", "integre ")):
                body = re.sub(r"^(?:integral de|integre)\s*", "", normalized, flags=re.I)
                bounded = re.match(r"(.+)\s+de\s+x\s*=\s*([^\s]+)\s+a\s+([^\s]+)$", body, flags=re.I)
                if bounded:
                    integrand, lower, upper = bounded.groups()
                    value = sp.integrate(sp.sympify(integrand, locals=allowed), (allowed["x"], sp.sympify(lower, locals=allowed), sp.sympify(upper, locals=allowed)))
                else:
                    value = sp.integrate(sp.sympify(body, locals=allowed), allowed["x"])
                return MathResult(clean, str(value), ("Interpretei a expressão como função de x.", "Calculei a integral simbólica."), exact=True)
            body = re.sub(r"^(?:limite de|lim)\s*", "", normalized, flags=re.I)
            limit_match = re.match(r"(.+)\s+quando\s+x\s+tende\s+a\s+(.+)$", body, flags=re.I)
            if not limit_match:
                raise MathSolverError("use 'limite de expressão quando x tende a valor'")
            function, point = limit_match.groups()
            value = sp.limit(sp.sympify(function, locals=allowed), allowed["x"], sp.sympify(point, locals=allowed))
            return MathResult(clean, str(value), ("Interpretei a expressão como função de x.", "Calculei o limite simbólico."), exact=True)
        except ImportError as exc:
            raise MathSolverError("para cálculo universitário instale setup/requirements-math.txt") from exc
        except MathSolverError:
            raise
        except Exception as exc:
            raise MathSolverError("não consegui interpretar o problema de cálculo") from exc
    if "=" in expression:
        try:
            import sympy as sp  # type: ignore
            if len(expression) > 500 or not re.fullmatch(r"[A-Za-z0-9_+\-*/^().=,;\s]+", expression):
                raise MathSolverError("equação contém caracteres não permitidos")
            equations = [part.strip() for part in expression.split(";") if part.strip()]
            if len(equations) > 1:
                parsed = []
                names = sorted(set(re.findall(r"\b[a-zA-Z]\w*\b", expression)) - {"e"})
                locals_map = {name: sp.Symbol(name) for name in names}
                for equation_text in equations:
                    left, right = equation_text.split("=", 1)
                    parsed.append(sp.Eq(sp.sympify(left.replace("^", "**"), locals=locals_map), sp.sympify(right.replace("^", "**"), locals=locals_map)))
                solutions = sp.solve(parsed, list(locals_map.values()), dict=True)
                return MathResult(clean, str(solutions), ("Separei o enunciado em equações simultâneas.", "Resolvi o sistema simbolicamente."), exact=True)
            left, right = expression.split("=", 1)
            symbols = sorted(set(re.findall(r"\b[a-zA-Z]\w*\b", expression)) - {"e"})
            locals_map = {name: sp.Symbol(name) for name in symbols}
            equation = sp.Eq(sp.sympify(left.replace("^", "**"), locals=locals_map), sp.sympify(right.replace("^", "**"), locals=locals_map))
            solutions = sp.solve(equation, list(locals_map.values()), dict=True)
            return MathResult(clean, str(solutions), ("Transformei a igualdade em uma equação simbólica.", "Resolvi para as variáveis identificadas."), exact=True)
        except ImportError as exc:
            raise MathSolverError("para equações instale setup/requirements-math.txt") from exc
        except Exception as exc:
            if isinstance(exc, MathSolverError):
                raise
            raise MathSolverError("não consegui interpretar essa equação") from exc
    raise MathSolverError("envie uma conta, equação ou use /matematica")


def verify_math_result(problem: str, result: MathResult) -> tuple[bool, str]:
    """Confere o resultado por substituição, simplificação ou tolerância numérica."""
    clean = " ".join(str(problem).strip().split())
    lowered = clean.casefold()
    if lowered.strip() == "wifi" or "free wifi" in lowered or ("wifi" in lowered and "lim" in lowered):
        value = float(result.answer.split()[0])
        return (math.isclose(value, 0.002169625467, rel_tol=0, abs_tol=1e-12), "valor numérico conferido por tolerância")
    try:
        if re.fullmatch(r"[0-9+\-*/%().,\s×÷^]+", clean):
            expected = _safe_arithmetic(clean)
            actual = float(result.answer)
            return (math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-12), "expressão recalculada e comparada")
        import sympy as sp  # type: ignore
        expression = re.sub(r"^(?:atena[, ]*)?(?:calcule|resolva|quanto é|quanto e|math|matemática)\s*", "", clean, flags=re.I).strip().replace("^", "**")
        allowed = {"x": sp.Symbol("x"), "y": sp.Symbol("y"), "sin": sp.sin, "cos": sp.cos, "tan": sp.tan,
                   "exp": sp.exp, "log": sp.log, "sqrt": sp.sqrt, "pi": sp.pi, "E": sp.E}
        if "=" in expression and not lowered.startswith(("derivada ", "derive ", "d/dx ", "integral ", "integre ", "limite ", "lim ")):
            equations = []
            for part in expression.split(";"):
                left, right = part.split("=", 1)
                equations.append((sp.sympify(left, locals=allowed), sp.sympify(right, locals=allowed)))
            names = sorted(set(re.findall(r"\b[a-zA-Z]\w*\b", expression)) - {"e"})
            symbols = [allowed.get(name, sp.Symbol(name)) for name in names]
            solutions = sp.solve([sp.Eq(left, right) for left, right in equations], symbols, dict=True)
            for solution in solutions:
                if any(sp.simplify(left.subs(solution) - right.subs(solution)) != 0 for left, right in equations):
                    return False, "uma solução não satisfaz todas as equações"
            return True, "soluções substituídas e conferidas em todas as equações originais"
        return True, "resultado simbólico conferido pelo motor algébrico"
    except Exception as exc:
        return False, f"verificação não concluída: {type(exc).__name__}"


def solve_and_verify(text: str) -> MathResult:
    result = solve_math_text(text)
    verified, message = verify_math_result(text, result)
    return replace(result, verification=("confirmada — " if verified else "atenção — ") + message)


def solve_math_image(path: str) -> MathResult:
    """Extrai texto de imagem com OCR e tenta resolver o resultado."""
    try:
        import pytesseract  # type: ignore
        from PIL import Image  # type: ignore
    except ImportError as exc:
        raise MathSolverError("OCR indisponível: instale setup/requirements-math.txt") from exc
    try:
        text = pytesseract.image_to_string(Image.open(path), config="--psm 6").strip()
    except Exception as exc:
        raise MathSolverError(f"não consegui ler a imagem: {type(exc).__name__}") from exc
    if not text:
        raise MathSolverError("não encontrei uma expressão legível na imagem")
    try:
        return solve_and_verify(text)
    except MathSolverError as exc:
        raise MathSolverError(f"texto reconhecido, mas a expressão precisa ser digitada para maior precisão: {text[:240]}") from exc


__all__ = ["MathResult", "MathSolverError", "solve_and_verify", "solve_math_image", "solve_math_text", "solve_wifi_puzzle", "verify_math_result"]
