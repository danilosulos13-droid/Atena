from __future__ import annotations

import urllib.error

from core.atena_llm_router import AtenaLLMRouter, RouterConfig


def test_has_internet_true_on_http_error_with_status_code(monkeypatch):
    """
    Regressão: urllib.request.urlopen levanta HTTPError para respostas 4xx/5xx
    em vez de retornar um objeto de resposta. O código antigo só checava o
    status dentro do `with urlopen(...)`, então qualquer 4xx/5xx (ex: 403 de
    rate limit do GitHub) era capturado pelo `except Exception` genérico e
    interpretado como "sem internet" — mesmo que a conexão estivesse OK.
    """
    router = AtenaLLMRouter(
        config=RouterConfig(open_access_mode=True, allow_paid_providers=False)
    )

    def fake_urlopen(url, timeout=3):
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)

    monkeypatch.setattr("core.atena_llm_router.urllib.request.urlopen", fake_urlopen)

    assert router._has_internet() is True


def test_has_internet_false_on_connection_error(monkeypatch):
    router = AtenaLLMRouter(
        config=RouterConfig(open_access_mode=True, allow_paid_providers=False)
    )

    def fake_urlopen(url, timeout=3):
        raise urllib.error.URLError("Network is unreachable")

    monkeypatch.setattr("core.atena_llm_router.urllib.request.urlopen", fake_urlopen)

    assert router._has_internet() is False


def test_has_internet_true_on_2xx_response(monkeypatch):
    router = AtenaLLMRouter(
        config=RouterConfig(open_access_mode=True, allow_paid_providers=False)
    )

    class _FakeResp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def _fake_urlopen(url, timeout=3):
        return _FakeResp()

    monkeypatch.setattr("core.atena_llm_router.urllib.request.urlopen", _fake_urlopen)

    assert router._has_internet() is True
