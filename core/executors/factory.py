"""Composição explícita do broker com executores reais de produção."""
from __future__ import annotations

import os
from pathlib import Path

from core.agent_plan_loop import PlannerExecutorCritic, ToolRegistry, ToolSpec
from core.tool_broker import ToolBroker
from core.tool_broker import BrokerToolAdapter
from core.executors.memory import MemorySearchExecutor
from core.executors.web import WebSearchExecutor
from core.executors.sandbox import RootlessContainerTestExecutor, SandboxedTestExecutor


def build_production_broker(
    db_path: str | Path,
    *,
    audit_path: str | Path | None = None,
    sources_config: str | Path | None = None,
    workspace: str | Path | None = None,
    sandbox_mode: str | None = None,
) -> ToolBroker:
    """Cria um broker real somente para ferramentas de leitura.

    A função não habilita ferramentas de escrita. Isso deve ser uma decisão
    explícita de uma camada de aprovação separada.
    """
    broker = ToolBroker(Path(audit_path) if audit_path else None)
    broker.register_executor("memory_search_production", MemorySearchExecutor(db_path))
    broker.register_executor("web_search_production", WebSearchExecutor(sources_config))
    mode = sandbox_mode or os.getenv("ATENA_SANDBOX_MODE", "process").strip().lower()
    if mode not in {"process", "container"}:
        raise ValueError("sandbox_mode deve ser 'process' ou 'container'")
    if workspace is None:
        configured_workspace = os.getenv("ATENA_SANDBOX_WORKSPACE", "").strip()
        workspace = configured_workspace or None
    if mode == "container" and workspace is None:
        raise ValueError("sandbox_mode=container exige workspace explícito")
    if workspace is not None and mode == "container":
        broker.register_executor("run_tests_rootless", RootlessContainerTestExecutor(
            workspace,
            image=os.getenv("ATENA_SANDBOX_IMAGE", "atena-sandbox-test:latest"),
        ))
    elif workspace is not None:
        broker.register_executor("run_tests_sandbox", SandboxedTestExecutor(workspace))
    broker.bind_tool("memory.search", "memory_search_production", sandbox_mode="temporary_fs")
    broker.bind_tool("web.search", "web_search_production", sandbox_mode="temporary_fs")
    if workspace is not None:
        executor_name = "run_tests_rootless" if mode == "container" else "run_tests_sandbox"
        broker.bind_tool("code.run_tests", executor_name, sandbox_mode="temporary_fs")
    return broker


def build_production_planner(
    broker: ToolBroker,
    *,
    allowed_tools: tuple[str, ...] | None = None,
) -> PlannerExecutorCritic:
    """Conecta ao planner somente as ferramentas do especialista selecionado."""
    selected = allowed_tools or ("memory.search", "web.search")
    aliases = {
        "memory.search": "memory_search",
        "web.search": "web_search",
        "code.run_tests": "code_run_tests",
    }
    registry = ToolRegistry()
    purposes = {
        "memory.search": "recuperar memória do ciclo",
        "web.search": "coletar evidência web do ciclo",
        "code.run_tests": "validar código em sandbox",
    }
    for tool_name in selected:
        alias = aliases.get(tool_name)
        if alias is None or tool_name not in broker.policies:
            continue
        registry.register(ToolSpec(
            alias,
            BrokerToolAdapter(broker, tool_name, purpose=purposes.get(tool_name, "executar ferramenta do especialista")),
        ))
    if not registry.names():
        raise ValueError("especialista não possui ferramentas disponíveis no broker")
    return PlannerExecutorCritic(registry, max_steps=8)
