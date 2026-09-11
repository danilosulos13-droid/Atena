import threading

import modules.multi_agent_orchestrator as orchestrator_module
from modules.multi_agent_orchestrator import Agent, MultiAgentOrchestrator


class _RunningBridge:
    def is_paused(self) -> bool:
        return False


def test_failed_agent_task_requeued_once_per_attempt(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "AtenaControlBridge", lambda: _RunningBridge())

    orchestrator = MultiAgentOrchestrator()
    orchestrator.max_retries = 3

    def failing_handler(task):
        orchestrator._stop_event.set()
        raise RuntimeError("boom")

    orchestrator.register_agent(
        Agent(
            "failing-agent",
            "Tester",
            ["failure_test"],
            failing_handler,
        )
    )

    task = {
        "description": "exercise retry path",
        "required_capabilities": ["failure_test"],
    }
    orchestrator.submit_task(task)

    worker = threading.Thread(target=orchestrator._worker_loop)
    worker.start()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert task["_retries"] == 1
    assert orchestrator.task_queue.qsize() == 1
    assert orchestrator.task_queue.get_nowait() is task


def test_parent_bridge_ranks_api_for_structured_child_task(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "rank_api_candidates",
        lambda topic, limit=5: [
            {
                "name": "GitHub",
                "endpoint": "https://api.github.com",
                "category": "code",
                "score": 0.94,
            },
            {
                "name": "GitLab",
                "endpoint": "https://gitlab.com/api/v4",
                "category": "code",
                "score": 0.86,
            },
        ],
    )
    orchestrator = MultiAgentOrchestrator()
    captured = {}

    def handler(payload):
        captured.update(payload["atena_api_assignment"])
        orchestrator._stop_event.set()
        return {"ok": True}

    orchestrator.register_agent(Agent("child-code", "Coder", ["code"], handler))
    orchestrator.submit_task("buscar repo github", payload={}, required_capabilities=["code"])

    worker = threading.Thread(target=orchestrator._worker_loop)
    worker.start()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert captured["parent"] == "AtenaControlBridge"
    assert captured["validated"] is True
    assert captured["agent_id"] == "child-code"
    assert captured["selected_api"]["name"] == "GitHub"
    assert captured["alternatives"][0]["name"] == "GitLab"


def test_parent_bridge_ranks_api_for_legacy_child_task(monkeypatch):
    monkeypatch.setattr(
        orchestrator_module,
        "rank_api_candidates",
        lambda topic, limit=5: [
            {
                "name": "Open-Meteo",
                "endpoint": "https://api.open-meteo.com/v1/forecast",
                "category": "weather",
                "score": 0.91,
            }
        ],
    )
    orchestrator = MultiAgentOrchestrator()
    captured = {}

    def handler(task):
        captured.update(task["atena_api_assignment"])
        orchestrator._stop_event.set()
        return {"ok": True}

    orchestrator.register_agent(Agent("child-weather", "Researcher", ["weather"], handler))
    orchestrator.submit_task({"description": "prever clima", "required_capabilities": ["weather"]})

    worker = threading.Thread(target=orchestrator._worker_loop)
    worker.start()
    worker.join(timeout=2)

    assert not worker.is_alive()
    assert captured["validated"] is True
    assert captured["selected_api"]["name"] == "Open-Meteo"
    assert captured["agent_role"] == "Researcher"
