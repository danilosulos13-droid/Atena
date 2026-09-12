import asyncio
from pathlib import Path

from core.atena_runtime import PersistentRuntime


def test_runtime_persists_connector_without_secret(tmp_path: Path):
    runtime = PersistentRuntime(tmp_path / "runtime.sqlite3", browser_profile=tmp_path / "browser")
    try:
        item = runtime.register_connector(
            "telegram-main",
            "telegram",
            {"token": "super-secret", "chat_id_env": "ATENA_TELEGRAM_CHAT_ID"},
        )
        assert item["config"]["token"].startswith("[REDACTED")
        saved = runtime.list_connectors()
        assert saved[0]["name"] == "telegram-main"
        assert "super-secret" not in str(saved)
    finally:
        runtime.router.close()


def test_runtime_worker_executes_and_persists_task(tmp_path: Path):
    runtime = PersistentRuntime(tmp_path / "runtime.sqlite3", browser_profile=tmp_path / "browser")

    async def handler(payload):
        return {"answer": payload["value"] * 2}

    runtime.register_handler("double", handler)

    async def scenario():
        await runtime.start()
        task = runtime.enqueue("double", {"value": 21})
        for _ in range(50):
            current = runtime.get_task(task.task_id)
            if current and current.status == "succeeded":
                assert current.result == {"answer": 42}
                break
            await asyncio.sleep(0.02)
        else:
            raise AssertionError("task did not finish")
        await runtime.stop()

    asyncio.run(scenario())
