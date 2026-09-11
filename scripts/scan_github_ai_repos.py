"""Compatibilidade para o caminho histórico do scanner GitHub."""
from scripts.utils import scan_github_ai_repos as _impl
from scripts.utils.scan_github_ai_repos import *  # noqa: F401,F403

WATCHLIST_PATH = _impl.WATCHLIST_PATH
DELTA_CACHE_PATH = _impl.DELTA_CACHE_PATH


def write_watchlist(*args, **kwargs):
    """Encaminha a escrita preservando overrides feitos no módulo legado."""
    _impl.WATCHLIST_PATH = WATCHLIST_PATH
    _impl.DELTA_CACHE_PATH = DELTA_CACHE_PATH
    return _impl.write_watchlist(*args, **kwargs)
