"""Compatibilidade para o caminho histórico ``python -m scripts.python_script``."""
from core.atena_terminal_python_script import *  # noqa: F401,F403
from core.atena_terminal_python_script import main

if __name__ == "__main__":
    raise SystemExit(main())
