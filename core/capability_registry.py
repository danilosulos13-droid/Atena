"""Registro seguro de capacidades da Atena.

A descoberta é estática: nenhum módulo é importado durante o boot. A execução
só ocorre por solicitação explícita e dentro das raízes permitidas.
"""
from __future__ import annotations

import ast
import importlib.util
import inspect
import os
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SEARCH_ROOTS = ("core", "modules", "scripts", "examples", "api", "dashboard", "consciousness", "plugins", "skills", "setup")
ROOT_FILE_SKIP = {"conftest.py"}
SKIP_PARTS = {"__pycache__", ".git", ".venv", ".venv_fix", "tests"}
ENTRYPOINT_NAMES = {"main", "run", "cli", "register", "create_app"}


@dataclass(frozen=True)
class Capability:
    name: str
    path: str
    area: str
    importable: bool
    entrypoints: tuple[str, ...]
    declared: bool
    status: str


def _safe_ast(path: Path) -> ast.Module | None:
    try:
        return ast.parse(path.read_text(encoding="utf-8", errors="ignore"), filename=str(path))
    except (OSError, SyntaxError):
        return None


def _metadata(path: Path) -> Capability:
    tree = _safe_ast(path)
    functions: set[str] = set()
    declared = False
    if tree:
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in ENTRYPOINT_NAMES:
                functions.add(node.name)
            if isinstance(node, ast.Assign):
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id == "ATENA_CAPABILITY":
                        declared = True
    rel = path.relative_to(ROOT).as_posix()
    area = rel.split("/", 1)[0] if "/" in rel else "root"
    importable = path.stem.isidentifier() and tree is not None
    status = "declared" if declared else ("runnable" if functions else "catalogued")
    return Capability(path.stem, rel, area, importable, tuple(sorted(functions)), declared, status)


def discover_capabilities() -> list[Capability]:
    result: list[Capability] = []
    seen: set[Path] = set()

    # Inclui scripts Python na raiz, exceto arquivos de configuração de testes.
    for path in sorted(ROOT.glob("*.py")):
        if path.name in ROOT_FILE_SKIP or path.name == "__init__.py":
            continue
        seen.add(path.resolve())
        result.append(_metadata(path))

    for root_name in SEARCH_ROOTS:
        root = ROOT / root_name
        if not root.exists():
            continue
        for path in sorted(root.rglob("*.py")):
            if path.resolve() in seen:
                continue
            if any(part in SKIP_PARTS for part in path.parts) or path.name == "__init__.py":
                continue
            seen.add(path.resolve())
            result.append(_metadata(path))
    return result


def catalog_dicts() -> list[dict[str, Any]]:
    return [asdict(item) for item in discover_capabilities()]


def _resolve(capability: Capability) -> Path:
    path = (ROOT / capability.path).resolve()
    allowed = tuple((ROOT / name).resolve() for name in SEARCH_ROOTS if (ROOT / name).exists())
    if not any(path == base or base in path.parents for base in allowed):
        raise ValueError("capacidade fora das raízes permitidas")
    return path


def _execution_allowlist() -> set[str]:
    raw = os.getenv("ATENA_CAPABILITY_ALLOWLIST", "")
    return {item.strip() for item in raw.split(",") if item.strip()}


def run_capability(name: str, args: list[str] | None = None) -> Any:
    matches = [item for item in discover_capabilities() if item.name == name]
    if len(matches) != 1:
        raise KeyError(f"capacidade não encontrada ou ambígua: {name}")
    allowlist = _execution_allowlist()
    if name not in allowlist:
        raise PermissionError(
            f"capacidade {name} bloqueada: defina ATENA_CAPABILITY_ALLOWLIST explicitamente"
        )
    capability = matches[0]
    if not capability.importable or not capability.entrypoints:
        raise ValueError(f"capacidade {name} não declara um ponto de entrada executável")
    path = _resolve(capability)
    module_name = f"_atena_capability_{name}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise ImportError(f"não foi possível carregar {capability.path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    argv = args or []
    for entrypoint in ("main", "run", "cli", "register", "create_app"):
        function = getattr(module, entrypoint, None)
        if not callable(function):
            continue
        result = function(argv) if entrypoint in {"main", "cli"} else function()
        if inspect.isawaitable(result):
            import asyncio
            return asyncio.run(result)
        return result
    raise RuntimeError(f"nenhum ponto de entrada executável em {capability.path}")


def main() -> int:
    print(json.dumps({"root": str(ROOT), "count": len(catalog_dicts()), "capabilities": catalog_dicts()}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


class CapabilityRegistry:
    """Fachada compatível para descoberta segura de capacidades."""
    def __init__(self, root: Path | str = ROOT):
        self.root = Path(root).resolve()

    def discover(self) -> list[Capability]:
        # O registro atual é deliberadamente somente-leitura e usa a raiz do
        # projeto; validar a raiz evita que o catálogo atravesse o repositório.
        if self.root != ROOT:
            raise ValueError("CapabilityRegistry deve apontar para a raiz da Atena")
        return discover_capabilities()

    def catalog(self) -> list[dict[str, Any]]:
        return [asdict(item) for item in self.discover()]
