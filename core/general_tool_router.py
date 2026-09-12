"""Roteador geral de ferramentas da Atena.

A camada centraliza allowlist, validação de argumentos, confirmação para ações
com efeitos externos e auditoria. O backend de browser é opcional: quando
Playwright não está instalado, a ferramenta falha de forma explícita e segura.
"""
from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


class ToolRouterError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolPolicy:
    name: str
    risk: str
    confirmation: bool
    description: str


@dataclass
class ToolExecution:
    tool_call_id: str
    name: str
    status: str
    result: dict[str, Any]
    error_code: str | None = None
    approval_required: bool = False
    elapsed_ms: float = 0.0
    side_effect: bool = False


class PlaywrightBrowser:
    """Sessão persistente de navegação para sites públicos.

    A sessão é criada sob demanda. Login, submissão de formulários e ações
    que alterem dados nunca são aprovados implicitamente pelo roteador.
    """

    def __init__(self, *, headless: bool = True, timeout_ms: int = 20_000) -> None:
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._playwright = None
        self._browser = None
        self._page = None

    def _page_or_start(self):
        if self._page is not None:
            return self._page
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise ToolRouterError("playwright_not_installed") from exc
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        context = self._browser.new_context()
        self._page = context.new_page()
        self._page.set_default_timeout(self.timeout_ms)
        return self._page

    @staticmethod
    def _safe_url(url: str) -> str:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ToolRouterError("only_http_https_urls_allowed")
        return url

    def navigate(self, url: str) -> dict[str, Any]:
        page = self._page_or_start()
        target = self._safe_url(url)
        response = page.goto(target, wait_until="domcontentloaded")
        return {"url": page.url, "title": page.title(), "status_code": response.status if response else None}

    def view(self, *, max_chars: int = 20_000) -> dict[str, Any]:
        page = self._page_or_start()
        text = page.locator("body").inner_text(timeout=self.timeout_ms)
        elements = []
        locator = page.locator("a,button,input,textarea,select")
        for index in range(min(locator.count(), 80)):
            item = locator.nth(index)
            try:
                elements.append({"index": index, "tag": item.evaluate("el => el.tagName.toLowerCase()"), "text": (item.inner_text() or item.get_attribute("aria-label") or item.get_attribute("name") or "")[:240]})
            except Exception:
                continue
        return {"url": page.url, "title": page.title(), "text": text[:max_chars], "elements": elements}

    def click(self, index: int) -> dict[str, Any]:
        page = self._page_or_start()
        page.locator("a,button,input,textarea,select").nth(index).click()
        return {"url": page.url, "title": page.title()}

    def fill(self, index: int, text: str) -> dict[str, Any]:
        page = self._page_or_start()
        page.locator("a,button,input,textarea,select").nth(index).fill(text)
        return {"url": page.url, "title": page.title(), "filled_index": index}

    def screenshot(self, path: str) -> dict[str, Any]:
        page = self._page_or_start()
        output = Path(path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(output), full_page=True)
        return {"path": str(output), "url": page.url}

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._playwright:
            self._playwright.stop()
        self._browser = self._playwright = self._page = None


class GeneralToolRouter:
    """Allowlist extensível para ferramentas de pesquisa, código e browser."""

    POLICIES = {
        "browser.navigate": ToolPolicy("browser.navigate", "read_only", False, "abrir uma URL pública"),
        "browser.view": ToolPolicy("browser.view", "read_only", False, "ler a página atual"),
        "browser.screenshot": ToolPolicy("browser.screenshot", "read_only", False, "capturar página atual"),
        "browser.click": ToolPolicy("browser.click", "write_scoped", True, "clicar em elemento de página"),
        "browser.fill": ToolPolicy("browser.fill", "write_scoped", True, "preencher campo de página"),
        "web.search": ToolPolicy("web.search", "read_only", False, "pesquisar fontes públicas"),
        "memory.search": ToolPolicy("memory.search", "read_only", False, "consultar memória"),
        "code.run_tests": ToolPolicy("code.run_tests", "sandbox_compute", False, "executar testes em sandbox"),
    }

    def __init__(self, *, browser: PlaywrightBrowser | None = None, audit_path: Path | None = None, executors: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] | None = None) -> None:
        self.browser = browser or PlaywrightBrowser()
        self.audit_path = audit_path
        self.executors = executors or {}

    def dispatch(self, name: str, arguments: dict[str, Any] | None = None, *, approval: bool = False) -> ToolExecution:
        started = time.perf_counter()
        args = arguments or {}
        policy = self.POLICIES.get(name)
        call_id = f"tool-{uuid.uuid4().hex}"
        if policy is None:
            return self._finish(call_id, name, "invalid", {}, "tool_not_allowlisted", started)
        if policy.confirmation and not approval:
            return self._finish(call_id, name, "blocked", {}, "explicit_confirmation_required", started, approval_required=True)
        try:
            result = self._execute(name, args)
            return self._finish(call_id, name, "executed", result, None, started, side_effect=policy.risk not in {"read_only", "sandbox_compute"})
        except Exception as exc:
            return self._finish(call_id, name, "tool_error", {}, type(exc).__name__, started)

    def _execute(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        if name == "browser.navigate":
            url = args.get("url")
            if not isinstance(url, str) or len(url) > 2_000:
                raise ToolRouterError("invalid_url")
            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ToolRouterError("only_http_https_urls_allowed")
            return self.browser.navigate(url)
        if name == "browser.view":
            return self.browser.view(max_chars=min(int(args.get("max_chars", 20_000)), 50_000))
        if name == "browser.screenshot":
            return self.browser.screenshot(str(args.get("path", "/tmp/atena-browser.png")))
        if name == "browser.click":
            return self.browser.click(int(args["index"]))
        if name == "browser.fill":
            text = str(args.get("text", ""))
            if len(text) > 10_000:
                raise ToolRouterError("input_too_large")
            return self.browser.fill(int(args["index"]), text)
        executor = self.executors.get(name)
        if executor is None:
            raise ToolRouterError("executor_not_configured")
        return executor(args)

    def _finish(self, call_id: str, name: str, status: str, result: dict[str, Any], error: str | None, started: float, *, approval_required: bool = False, side_effect: bool = False) -> ToolExecution:
        event = ToolExecution(call_id, name, status, result, error, approval_required, (time.perf_counter() - started) * 1000, side_effect)
        if self.audit_path:
            self.audit_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"timestamp": time.time(), "call": {"id": call_id, "name": name}, "result": event.__dict__}, ensure_ascii=False) + "\n")
        return event

    def close(self) -> None:
        self.browser.close()


__all__ = ["GeneralToolRouter", "PlaywrightBrowser", "ToolExecution", "ToolPolicy", "ToolRouterError"]
