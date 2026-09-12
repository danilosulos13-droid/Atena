from pathlib import Path

from core.general_tool_router import GeneralToolRouter


class FakeBrowser:
    def navigate(self, url):
        return {"url": url, "title": "fake"}

    def view(self, *, max_chars=20000):
        return {"text": "conteúdo", "elements": [], "max_chars": max_chars}

    def click(self, index):
        return {"clicked": index}

    def fill(self, index, text):
        return {"filled": index, "text": text}

    def screenshot(self, path):
        return {"path": path}

    def close(self):
        return None


def test_browser_navigation_is_allowlisted_and_audited(tmp_path: Path):
    router = GeneralToolRouter(browser=FakeBrowser(), audit_path=tmp_path / "tools.jsonl")
    result = router.dispatch("browser.navigate", {"url": "https://example.com"})
    assert result.status == "executed"
    assert result.result["title"] == "fake"
    assert (tmp_path / "tools.jsonl").read_text()


def test_browser_write_requires_confirmation():
    router = GeneralToolRouter(browser=FakeBrowser())
    result = router.dispatch("browser.fill", {"index": 0, "text": "hello"})
    assert result.status == "blocked"
    assert result.approval_required is True
    approved = router.dispatch("browser.fill", {"index": 0, "text": "hello"}, approval=True)
    assert approved.status == "executed"


def test_unknown_tool_is_rejected():
    result = GeneralToolRouter(browser=FakeBrowser()).dispatch("shell.exec", {"command": "id"})
    assert result.status == "invalid"
    assert result.error_code == "tool_not_allowlisted"


def test_browser_url_policy_rejects_non_web_urls():
    result = GeneralToolRouter(browser=FakeBrowser()).dispatch("browser.navigate", {"url": "file:///etc/passwd"})
    assert result.status == "tool_error"
    assert result.error_code == "ToolRouterError"
