"""Compatibilidade para o caminho histórico do avaliador de artefatos."""

from scripts.utils.evaluate_generated_artifacts import *  # noqa: F401,F403
from scripts.utils.evaluate_generated_artifacts import evaluate_artifact

__all__ = ["evaluate_artifact"]
