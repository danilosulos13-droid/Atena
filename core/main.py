#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Shim de compatibilidade: re-exporta símbolos do main.py raiz."""
from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_MODULES_DIR = str(_ROOT / "modules")
if _MODULES_DIR not in sys.path:
    sys.path.insert(0, _MODULES_DIR)
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

if __name__ == "__main__":
    # O launcher executa este shim como processo filho. Nesse caminho, apenas
    # importar o main.py raiz não aciona seu bloco CLI e fazia `./atena --auto`
    # terminar sem executar nenhum ciclo autônomo.
    runpy.run_path(str(_ROOT / "main.py"), run_name="__main__")
else:
    _spec = importlib.util.spec_from_file_location("_atena_root_main", _ROOT / "main.py")
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["_atena_root_main"] = _mod

    try:
        _spec.loader.exec_module(_mod)
    except SystemExit:
        pass
    except Exception:
        pass

    globals().update({k: v for k, v in vars(_mod).items() if not k.startswith("__")})
    __all__ = [k for k in vars(_mod) if not k.startswith("_")]
