#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Agent Orchestrator v3.0 - Enterprise-grade Agent Management System

Features:
- Dynamic agent lifecycle management
- Intelligent task routing with capability matching
- Priority-based task queues
- Load balancing and auto-scaling
- Circuit breaker for failing agents
- Distributed tracing
- Health monitoring and auto-recovery
- Event-driven architecture
- Plugin system for custom agents
"""

import asyncio
import json
import logging
import threading
import time
import uuid
import heapq
from collections import defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum, auto
from typing import Dict, List, Any, Callable, Optional, Set, Tuple, Union
from queue import Queue, PriorityQueue, Empty
from concurrent.futures import ThreadPoolExecutor, Future
import traceback
from functools import wraps
import random

from core.internet_challenge import rank_api_candidates

# Tentativa de importar módulos avançados
try:
    from rich.console import Console
    from rich.table import Table
    from rich.panel import Panel
    from rich.live import Live
    from rich.layout import Layout
    from rich.progress import Progress, SpinnerColumn, TextColumn
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False

# Configuração de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ========== ENUMS E MODELOS ==========

class AgentStatus(Enum):
    """Status dos agentes"""
    IDLE = "idle"
    WORKING = "working"
    PAUSED = "paused"
    ERROR = "error"
    DEGRADED = "degraded"
    RECOVERING = "recovering"
    OFFLINE = "offline"

class TaskPriority(Enum):
    """Prioridades de tarefas"""
    CRITICAL = 0
    HIGH = 1
    NORMAL = 2
    LOW = 3
    BACKGROUND = 4

class TaskStatus(Enum):
    """Status de execução de tarefas"""
    PENDING = "pending"
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"

@dataclass
class Task:
    """Estrutura completa de tarefa"""
    id: str
    description: str
    payload: Dict[str, Any]
    required_capabilities: List[str]
    priority: TaskPriority = TaskPriority.NORMAL
    timeout: int = 300  # segundos
    retries: int = 0
    max_retries: int = 3
    created_at: datetime = field(default_factory=datetime.now)
    status: TaskStatus = TaskStatus.PENDING
    assigned_agent: Optional[str] = None
    result: Any = None
    error: Optional[str] = None
    
    def to_dict(self) -> Dict:
        return {
            "id": self.id,
            "description": self.description,
            "priority": self.priority.value,
            "status": self.status.value,
            "assigned_agent": self.assigned_agent,
            "created_at": self.created_at.isoformat(),
            "retries": self.retries
        }
    
    def __lt__(self, other):
        # Para PriorityQueue (menor número = maior prioridade)
        return self.priority.value < other.priority.value

@dataclass
class AgentMetrics:
    """Métricas de performance do agente"""
    total_tasks: int = 0
    successful_tasks: int = 0
    failed_tasks: int = 0
    total_execution_time: float = 0.0
    avg_execution_time: float = 0.0
    last_task_time: Optional[datetime] = None
    last_error: Optional[str] = None
    consecutive_failures: int = 0
    
    def update(self, duration: float, success: bool, error: Optional[str] = None):
        self.total_tasks += 1
        if success:
            self.successful_tasks += 1
            self.consecutive_failures = 0
        else:
            self.failed_tasks += 1
            self.consecutive_failures += 1
            self.last_error = error
        
        self.total_execution_time += duration
        self.avg_execution_time = self.total_execution_time / self.total_tasks
        self.last_task_time = datetime.now()
    
    @property
    def success_rate(self) -> float:
        if self.total_tasks == 0:
            return 1.0
        return self.successful_tasks / self.total_tasks

@dataclass
class AgentConfig:
    """Configuração avançada do agente"""
    max_concurrent_tasks: int = 1
    health_check_interval: int = 30
    circuit_breaker_threshold: int = 5
    recovery_timeout: int = 60
    load_factor: float = 1.0

class Agent:
    """Agente inteligente com capacidades avançadas"""
    
    def __init__(
        self,
        agent_id: str,
        role: str,
        capabilities: List[str],
        task_handler: Callable[[Dict[str, Any]], Any],
        config: Optional[AgentConfig] = None
    ):
        self.agent_id = agent_id
        self.role = role
        self.capabilities = set(capabilities)
        self.task_handler = task_handler
        self.config = config or AgentConfig()
        
        # Estado
        self.status = AgentStatus.IDLE
        self.current_task: Optional[Task] = None
        self.metrics = AgentMetrics()
        self.created_at = datetime.now()
        self.last_health_check = datetime.now()
        
        # Threading
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=self.config.max_concurrent_tasks)
        
        # Circuit breaker
        self._circuit_open = False
        self._circuit_open_until: Optional[datetime] = None
        
        logger.info(
            f"Agent {self.agent_id} ({self.role}) created with capabilities: {', '.join(self.capabilities)}"
        )
    
    def can_handle_task(self, task: Task) -> bool:
        """Verifica se o agente pode executar a tarefa"""
        # Verifica circuit breaker
        if self._circuit_open:
            if self._circuit_open_until and datetime.now() > self._circuit_open_until:
                self._circuit_open = False
                self.status = AgentStatus.RECOVERING
                logger.info(f"Circuit breaker for {self.agent_id} closed")
            else:
                return False
        
        # Verifica status
        if self.status not in [AgentStatus.IDLE, AgentStatus.DEGRADED]:
            return False
        
        # Verifica capacidades
        required_caps = set(task.required_capabilities)
        if not required_caps.issubset(self.capabilities):
            return False
        
        # Verifica limite de concorrência
        if self.current_task is not None:
            return False
        
        return True
    
    def assign_task(self, task: Task) -> Any:
        """Atribui e executa uma tarefa"""
        with self._lock:
            if not self.can_handle_task(task):
                raise Exception(f"Agent {self.agent_id} cannot handle task {task.id}")
            
            self.current_task = task
            self.status = AgentStatus.WORKING
            task.status = TaskStatus.RUNNING
            task.assigned_agent = self.agent_id
        
        start_time = time.time()
        
        try:
            logger.info(f"Agent {self.agent_id} executing task: {task.description}")
            
            # Executa com timeout
            future = self._executor.submit(self.task_handler, task.payload)
            result = future.result(timeout=task.timeout)
            
            # Sucesso
            duration = time.time() - start_time
            self.metrics.update(duration, True)
            
            task.status = TaskStatus.COMPLETED
            task.result = result
            
            return result
            
        except Exception as e:
            duration = time.time() - start_time
            self.metrics.update(duration, False, str(e))
            
            task.status = TaskStatus.FAILED
            task.error = str(e)
            
            # Circuit breaker
            if self.metrics.consecutive_failures >= self.config.circuit_breaker_threshold:
                self._circuit_open = True
                self._circuit_open_until = datetime.now() + timedelta(seconds=self.config.recovery_timeout)
                self.status = AgentStatus.ERROR
                logger.error(
                    f"Circuit breaker opened for {self.agent_id} after {self.metrics.consecutive_failures} failures"
                )
            
            raise
            
        finally:
            with self._lock:
                self.current_task = None
                if self.status == AgentStatus.WORKING:
                    self.status = AgentStatus.IDLE
    
    def health_check(self) -> Dict[str, Any]:
        """Verifica saúde do agente"""
        now = datetime.now()
        self.last_health_check = now
        
        health_status = {
            "agent_id": self.agent_id,
            "status": self.status.value,
            "circuit_open": self._circuit_open,
            "current_task": self.current_task.id if self.current_task else None,
            "metrics": {
                "total_tasks": self.metrics.total_tasks,
                "success_rate": f"{self.metrics.success_rate * 100:.1f}%",
                "avg_execution_time": f"{self.metrics.avg_execution_time:.2f}s"
            }
        }
        
        # Auto-recovery para agentes degradados
        if self.status == AgentStatus.ERROR and self._circuit_open_until:
            if datetime.now() > self._circuit_open_until:
                self._circuit_open = False
                self.status = AgentStatus.IDLE
                logger.info(f"Agent {self.agent_id} recovered automatically")
        
        return health_status
    
    def get_status_info(self) -> Dict:
        """Retorna informações detalhadas do agente"""
        return {
            "id": self.agent_id,
            "role": self.role,
            "status": self.status.value,
            "capabilities": list(self.capabilities),
            "metrics": {
                "total_tasks": self.metrics.total_tasks,
                "successful": self.metrics.successful_tasks,
                "failed": self.metrics.failed_tasks,
                "success_rate": f"{self.metrics.success_rate * 100:.1f}%",
                "avg_time": f"{self.metrics.avg_execution_time:.2f}s"
            },
            "current_task": self.current_task.id if self.current_task else None,
            "circuit_breaker_open": self._circuit_open
        }


# ========== EVENT SYSTEM ==========

class EventType(Enum):
    """Tipos de eventos do sistema"""
    AGENT_REGISTERED = auto()
    AGENT_UNREGISTERED = auto()
    AGENT_STATUS_CHANGED = auto()
    TASK_SUBMITTED = auto()
    TASK_STARTED = auto()
    TASK_COMPLETED = auto()
    TASK_FAILED = auto()
    ORCHESTRATOR_STARTED = auto()
    ORCHESTRATOR_STOPPED = auto()
    HEALTH_CHECK = auto()

@dataclass
class Event:
    """Estrutura de evento"""
    type: EventType
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=datetime.now)


# ========== MULTI-AGENT ORCHESTRATOR ==========

class AtenaControlBridge:
    """Parent control bridge used by tests and external supervisors.

    Besides pause control, this acts as Atena's validating parent: before a
    child agent executes a task, the bridge ranks public API candidates for the
    task/agent context and approves the best viable option.
    """

    def __init__(self, min_api_score: float = 0.5):
        self.min_api_score = min_api_score

    def is_paused(self) -> bool:
        return False

    def rank_apis_for_task(self, task_context: Dict[str, Any], agent: Agent, limit: int = 5) -> List[Dict[str, Any]]:
        topic_parts = [
            str(task_context.get("description", "")),
            " ".join(str(cap) for cap in task_context.get("required_capabilities", [])),
            agent.role,
            " ".join(sorted(agent.capabilities)),
        ]
        topic = " ".join(part for part in topic_parts if part).strip() or "general api"
        return rank_api_candidates(topic, limit=limit)

    def validate_api_assignment(
        self,
        task_context: Dict[str, Any],
        agent: Agent,
        candidates: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        selected = candidates[0] if candidates else None
        score = float(selected.get("score", 0.0)) if selected else 0.0
        validated = bool(selected and selected.get("endpoint") and score >= self.min_api_score)
        return {
            "parent": "AtenaControlBridge",
            "validated": validated,
            "agent_id": agent.agent_id,
            "agent_role": agent.role,
            "task_id": task_context.get("id"),
            "task_description": task_context.get("description", ""),
            "selected_api": selected,
            "alternatives": candidates[1:],
            "reason": "approved" if validated else "no_candidate_above_threshold",
        }


class MultiAgentOrchestrator:
    """Orquestrador enterprise de multi-agentes"""
    
    def __init__(
        self,
        max_workers: int = 10,
        enable_metrics: bool = True,
        enable_events: bool = True
    ):
        self.agents: Dict[str, Agent] = {}
        self.task_queue = PriorityQueue()
        self._stop_event = threading.Event()
        self._worker_threads: List[threading.Thread] = []
        self._health_thread: Optional[threading.Thread] = None
        
        # Configuração
        self.max_workers = max_workers
        self.enable_metrics = enable_metrics
        self.enable_events = enable_events
        
        # Métricas e estado
        self.metrics: Dict[str, AgentMetrics] = defaultdict(AgentMetrics)
        self.task_history: List[Task] = []
        self.event_handlers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._lock = threading.Lock()
        
        # Task tracking
        self._pending_tasks: Dict[str, Task] = {}
        self._completed_tasks: Dict[str, Task] = {}
        
        # Performance
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self.control_bridge = AtenaControlBridge()
        
        logger.info(f"MultiAgentOrchestrator initialized with {max_workers} workers")
    
    def register_agent(self, agent: Agent):
        """Registra um novo agente no orquestrador"""
        with self._lock:
            if agent.agent_id in self.agents:
                logger.warning(f"Agent {agent.agent_id} already registered, overwriting")
            
            self.agents[agent.agent_id] = agent
            self._emit_event(EventType.AGENT_REGISTERED, {"agent_id": agent.agent_id})
            
            logger.info(
                f"Agent {agent.agent_id} registered. "
                f"Total agents: {len(self.agents)}"
            )
    
    def unregister_agent(self, agent_id: str):
        """Remove um agente do orquestrador"""
        with self._lock:
            if agent_id in self.agents:
                del self.agents[agent_id]
                self._emit_event(EventType.AGENT_UNREGISTERED, {"agent_id": agent_id})
                logger.info(f"Agent {agent_id} unregistered")
    
    def submit_task(
        self,
        description: str | Dict[str, Any],
        payload: Optional[Dict[str, Any]] = None,
        required_capabilities: Optional[List[str]] = None,
        priority: TaskPriority = TaskPriority.NORMAL,
        timeout: int = 300,
        max_retries: int = 3
    ) -> str:
        """Submete uma nova tarefa para execução.

        Accepts the current structured signature and the legacy dict payload
        used by lightweight retry tests.
        """
        if isinstance(description, dict) and payload is None:
            legacy_task = description
            legacy_task.setdefault("_retries", 0)
            legacy_task.setdefault("_max_retries", getattr(self, "max_retries", max_retries))
            legacy_task.setdefault("id", str(uuid.uuid4()))
            with self._lock:
                self.task_queue.put(legacy_task)
            return str(legacy_task["id"])

        payload = payload or {}
        required_capabilities = required_capabilities or []
        task = Task(
            id=str(uuid.uuid4()),
            description=str(description),
            payload=payload,
            required_capabilities=required_capabilities,
            priority=priority,
            timeout=timeout,
            max_retries=max_retries
        )
        
        with self._lock:
            self._pending_tasks[task.id] = task
            self.task_queue.put((task.priority.value, task))
            self._emit_event(EventType.TASK_SUBMITTED, {"task": task.to_dict()})
        
        logger.info(
            f"Task submitted: {description} "
            f"(priority={priority.name}, capabilities={required_capabilities})"
        )
        
        return task.id
    
    def get_task_status(self, task_id: str) -> Optional[Dict]:
        """Retorna status de uma tarefa"""
        with self._lock:
            if task_id in self._pending_tasks:
                return self._pending_tasks[task_id].to_dict()
            elif task_id in self._completed_tasks:
                return self._completed_tasks[task_id].to_dict()
        
        return None

    def _attach_parent_validated_api(self, task: Task | Dict[str, Any], agent: Agent) -> Dict[str, Any]:
        """Rank and attach the API that a child agent should use for this task."""
        if not (
            hasattr(self.control_bridge, "rank_apis_for_task")
            and hasattr(self.control_bridge, "validate_api_assignment")
        ):
            return {
                "parent": type(self.control_bridge).__name__,
                "validated": False,
                "agent_id": agent.agent_id,
                "selected_api": None,
                "alternatives": [],
                "reason": "bridge_without_api_validation",
            }

        if isinstance(task, Task):
            task_context: Dict[str, Any] = {
                "id": task.id,
                "description": task.description,
                "required_capabilities": task.required_capabilities,
                "payload": task.payload,
            }
            candidates = self.control_bridge.rank_apis_for_task(task_context, agent)
            assignment = self.control_bridge.validate_api_assignment(task_context, agent, candidates)
            task.payload["atena_api_assignment"] = assignment
            return assignment

        task_context = {
            "id": task.get("id"),
            "description": task.get("description", ""),
            "required_capabilities": task.get("required_capabilities", []),
            "payload": task,
        }
        candidates = self.control_bridge.rank_apis_for_task(task_context, agent)
        assignment = self.control_bridge.validate_api_assignment(task_context, agent, candidates)
        task["atena_api_assignment"] = assignment
        return assignment


    def _process_legacy_task(self, task: Dict[str, Any]) -> None:
        """Process a legacy dict task and requeue immediately on first failures."""
        if self.control_bridge.is_paused():
            self.task_queue.put(task)
            return

        required = set(task.get("required_capabilities", []))
        agent = next((a for a in self.agents.values() if required.issubset(a.capabilities)), None)
        if agent is None:
            task["_retries"] = task.get("_retries", 0) + 1
            if task["_retries"] <= task.get("_max_retries", getattr(self, "max_retries", 3)):
                self.task_queue.put(task)
            return

        try:
            self._attach_parent_validated_api(task, agent)
            agent.task_handler(task)
        except Exception:
            task["_retries"] = task.get("_retries", 0) + 1
            if task["_retries"] <= task.get("_max_retries", getattr(self, "max_retries", 3)):
                self.task_queue.put(task)
            return

    def _worker_loop(self):
        """Worker loop para processamento de tarefas"""
        while not self._stop_event.is_set():
            try:
                # Pega tarefa da fila com timeout
                queue_item = self.task_queue.get(timeout=1)
                if isinstance(queue_item, dict):
                    self._process_legacy_task(queue_item)
                    self.task_queue.task_done()
                    continue
                priority, task = queue_item
                
                with self._lock:
                    if task.id not in self._pending_tasks:
                        continue
                    
                    task.status = TaskStatus.QUEUED
                
                # Encontra agente adequado
                assigned = False
                
                # Ordena agentes por carga e taxa de sucesso
                available_agents = [
                    (agent, agent.metrics.success_rate)
                    for agent in self.agents.values()
                    if agent.can_handle_task(task)
                ]
                
                # Ordena por melhor taxa de sucesso
                available_agents.sort(key=lambda x: x[1], reverse=True)
                
                for agent, _ in available_agents:
                    try:
                        self._attach_parent_validated_api(task, agent)
                        # Executa tarefa no pool de threads
                        future = self._executor.submit(agent.assign_task, task)
                        result = future.result(timeout=task.timeout + 10)
                        
                        assigned = True
                        
                        # Atualiza métricas
                        self.metrics[agent.agent_id].update(
                            task.metrics.total_execution_time if hasattr(task, 'metrics') else 0,
                            True
                        )
                        
                        # Move para completados
                        with self._lock:
                            task.status = TaskStatus.COMPLETED
                            self._completed_tasks[task.id] = task
                            if task.id in self._pending_tasks:
                                del self._pending_tasks[task.id]
                            
                            self._emit_event(EventType.TASK_COMPLETED, {
                                "task": task.to_dict(),
                                "result": str(result)[:200]
                            })
                        
                        logger.info(
                            f"Task {task.id} completed by agent {agent.agent_id} "
                            f"in {task.metrics.total_execution_time:.2f}s"
                        )
                        break
                        
                    except Exception as e:
                        logger.warning(f"Agent {agent.agent_id} failed task {task.id}: {e}")
                        
                        # Prepara para retry
                        task.retries += 1
                        
                        if task.retries <= task.max_retries:
                            task.status = TaskStatus.RETRYING
                            # Recoloca na fila com backoff exponencial
                            delay = 2 ** task.retries
                            logger.info(
                                f"Retrying task {task.id} "
                                f"(attempt {task.retries}/{task.max_retries}) in {delay}s"
                            )
                            
                            # Usa threading timer para recolocar na fila
                            threading.Timer(delay, lambda: self.task_queue.put((priority, task))).start()
                        else:
                            with self._lock:
                                task.status = TaskStatus.FAILED
                                self._completed_tasks[task.id] = task
                                if task.id in self._pending_tasks:
                                    del self._pending_tasks[task.id]
                                
                                self._emit_event(EventType.TASK_FAILED, {
                                    "task": task.to_dict(),
                                    "error": str(e)
                                })
                            
                            logger.error(f"Task {task.id} failed after {task.retries} retries: {e}")
                        
                        assigned = True
                        break
                
                if not assigned:
                    # Nenhum agente disponível, recoloca na fila com delay
                    task.retries += 1
                    
                    if task.retries <= task.max_retries:
                        delay = min(60, 2 ** task.retries)
                        logger.warning(
                            f"No agent available for task {task.id}, "
                            f"retry {task.retries}/{task.max_retries} in {delay}s"
                        )
                        threading.Timer(delay, lambda: self.task_queue.put((priority, task))).start()
                    else:
                        with self._lock:
                            task.status = TaskStatus.FAILED
                            self._completed_tasks[task.id] = task
                            if task.id in self._pending_tasks:
                                del self._pending_tasks[task.id]
                        
                        logger.error(f"Task {task.id} discarded: no suitable agent available")
                
                self.task_queue.task_done()
                
            except Empty:
                continue
            except Exception as e:
                logger.exception(f"Unexpected error in worker loop: {e}")
    
    def _health_monitor_loop(self):
        """Loop de monitoramento de saúde dos agentes"""
        while not self._stop_event.is_set():
            try:
                time.sleep(10)  # Check a cada 10 segundos
                
                with self._lock:
                    for agent_id, agent in self.agents.items():
                        health = agent.health_check()
                        
                        # Verifica agentes inativos
                        if agent.status == AgentStatus.ERROR:
                            # Tenta recuperar
                            if agent.metrics.consecutive_failures > agent.config.circuit_breaker_threshold:
                                logger.warning(f"Agent {agent_id} in error state, attempting recovery")
                                # Reset do agente
                                agent.status = AgentStatus.RECOVERING
                                agent._circuit_open = False
                        
                        self._emit_event(EventType.HEALTH_CHECK, health)
                
                # Limpa histórico antigo (mantém últimos 1000)
                if len(self.task_history) > 1000:
                    self.task_history = self.task_history[-1000:]
                
            except Exception as e:
                logger.exception(f"Health monitor error: {e}")
    
    def start(self):
        """Inicia o orquestrador"""
        if self._worker_threads:
            logger.warning("Orchestrator already running")
            return
        
        self._stop_event.clear()
        
        # Inicia workers
        for i in range(self.max_workers):
            worker = threading.Thread(
                target=self._worker_loop,
                name=f"Worker-{i}",
                daemon=True
            )
            worker.start()
            self._worker_threads.append(worker)
        
        # Inicia health monitor
        self._health_thread = threading.Thread(
            target=self._health_monitor_loop,
            name="HealthMonitor",
            daemon=True
        )
        self._health_thread.start()
        
        self._emit_event(EventType.ORCHESTRATOR_STARTED, {"workers": self.max_workers})
        logger.info(f"MultiAgentOrchestrator started with {self.max_workers} workers")
    
    def stop(self, timeout: int = 10):
        """Para o orquestrador gracefulmente"""
        logger.info("Stopping MultiAgentOrchestrator...")
        
        self._stop_event.set()
        
        # Aguarda workers terminarem
        for worker in self._worker_threads:
            worker.join(timeout=timeout)
        
        if self._health_thread:
            self._health_thread.join(timeout=timeout)
        
        self._executor.shutdown(wait=True)
        
        self._emit_event(EventType.ORCHESTRATOR_STOPPED, {})
        logger.info("MultiAgentOrchestrator stopped")
    
    def get_agents_status(self) -> List[Dict]:
        """Retorna status de todos os agentes"""
        with self._lock:
            return [agent.get_status_info() for agent in self.agents.values()]
    
    def get_queue_size(self) -> int:
        """Retorna tamanho da fila de tarefas"""
        return self.task_queue.qsize()
    
    def get_statistics(self) -> Dict[str, Any]:
        """Retorna estatísticas detalhadas do sistema"""
        with self._lock:
            total_tasks = sum(m.total_tasks for m in self.metrics.values())
            successful_tasks = sum(m.successful_tasks for m in self.metrics.values())
            
            return {
                "agents": {
                    "total": len(self.agents),
                    "by_status": defaultdict(int)
                },
                "tasks": {
                    "pending": len(self._pending_tasks),
                    "completed": len(self._completed_tasks),
                    "total_processed": total_tasks,
                    "success_rate": (successful_tasks / total_tasks * 100) if total_tasks > 0 else 0
                },
                "queue_size": self.task_queue.qsize(),
                "workers": self.max_workers
            }
    
    def on_event(self, event_type: EventType, handler: Callable):
        """Registra handler para eventos"""
        self.event_handlers[event_type].append(handler)
    
    def _emit_event(self, event_type: EventType, data: Dict[str, Any]):
        """Emite evento para handlers registrados"""
        if not self.enable_events:
            return
        
        event = Event(type=event_type, data=data)
        
        for handler in self.event_handlers.get(event_type, []):
            try:
                handler(event)
            except Exception as e:
                logger.error(f"Event handler error: {e}")
    
    def render_dashboard(self):
        """Renderiza dashboard no console (se Rich disponível)"""
        if not RICH_AVAILABLE:
            print("Rich library not available for dashboard")
            return
        
        console = Console()
        
        with Live(refresh_per_second=2) as live:
            while not self._stop_event.is_set():
                # Cria layout do dashboard
                layout = Layout()
                
                # Header
                header = Panel(
                    f"[bold cyan]Multi-Agent Orchestrator v3.0[/bold cyan]\n"
                    f"[dim]Agents: {len(self.agents)} | Queue: {self.get_queue_size()} | "
                    f"Time: {datetime.now().strftime('%H:%M:%S')}[/dim]",
                    border_style="cyan"
                )
                layout.split_column(header)
                
                # Tabela de agentes
                agent_table = Table(title="Agent Status", show_header=True, header_style="bold green")
                agent_table.add_column("ID", style="cyan")
                agent_table.add_column("Role", style="yellow")
                agent_table.add_column("Status", style="white")
                agent_table.add_column("Tasks", justify="right")
                agent_table.add_column("Success Rate", justify="right")
                agent_table.add_column("Current Task", style="dim")
                
                for agent in self.agents.values():
                    status_color = {
                        AgentStatus.IDLE: "green",
                        AgentStatus.WORKING: "yellow",
                        AgentStatus.ERROR: "red",
                        AgentStatus.DEGRADED: "orange"
                    }.get(agent.status, "white")
                    
                    agent_table.add_row(
                        agent.agent_id[:15],
                        agent.role,
                        f"[{status_color}]{agent.status.value}[/{status_color}]",
                        str(agent.metrics.total_tasks),
                        f"{agent.metrics.success_rate * 100:.1f}%",
                        (agent.current_task.description[:20] if agent.current_task else "-") + "..."
                    )
                
                layout.split_row(agent_table)
                
                # Atualiza display
                live.update(layout)
                time.sleep(2)


# ========== EXAMPLE AGENTS ==========

def create_code_agent():
    """Cria agente especializado em geração de código"""
    def handler(task: Dict[str, Any]) -> str:
        prompt = task.get("prompt", "No prompt provided")
        language = task.get("language", "python")
        
        # Simula processamento
        time.sleep(random.uniform(0.5, 1.5))
        
        return f"Generated {language} code for: {prompt}"
    
    return Agent(
        agent_id="code_agent_001",
        role="Developer",
        capabilities=["code_generation", "python", "javascript", "code_review"],
        task_handler=handler
    )

def create_data_agent():
    """Cria agente especializado em análise de dados"""
    def handler(task: Dict[str, Any]) -> Dict[str, Any]:
        data = task.get("data", [])
        analysis_type = task.get("type", "basic")
        
        # Simula análise
        time.sleep(random.uniform(0.3, 1.0))
        
        return {
            "analysis_type": analysis_type,
            "data_points": len(data),
            "result": f"Analysis of {len(data)} points completed"
        }
    
    return Agent(
        agent_id="data_agent_001",
        role="Data Scientist",
        capabilities=["data_analysis", "statistics", "machine_learning", "visualization"],
        task_handler=handler
    )

def create_security_agent():
    """Cria agente especializado em segurança"""
    def handler(task: Dict[str, Any]) -> Dict[str, Any]:
        scan_type = task.get("scan_type", "vulnerability")
        target = task.get("target", "localhost")
        
        # Simula scan de segurança
        time.sleep(random.uniform(1.0, 3.0))
        
        return {
            "scan_type": scan_type,
            "target": target,
            "vulnerabilities_found": random.randint(0, 5),
            "status": "completed"
        }
    
    return Agent(
        agent_id="security_agent_001",
        role="Security Analyst",
        capabilities=["security_scan", "vulnerability_assessment", "penetration_testing"],
        task_handler=handler
    )

def create_monitoring_agent():
    """Cria agente especializado em monitoramento"""
    def handler(task: Dict[str, Any]) -> Dict[str, Any]:
        resource = task.get("resource", "system")
        
        # Simula coleta de métricas
        time.sleep(random.uniform(0.2, 0.8))
        
        if PSUTIL_AVAILABLE:
            return {
                "resource": resource,
                "cpu": psutil.cpu_percent(),
                "memory": psutil.virtual_memory().percent,
                "disk": psutil.disk_usage('/').percent
            }
        else:
            return {
                "resource": resource,
                "status": "healthy",
                "metrics": {"cpu": 45, "memory": 60}
            }
    
    return Agent(
        agent_id="monitoring_agent_001",
        role="Monitor",
        capabilities=["monitoring", "metrics_collection", "health_check"],
        task_handler=handler
    )


# ========== MAIN DEMO ==========

def demo():
    """Demonstração do sistema multi-agente"""
    print("=" * 70)
    print("🤖 MULTI-AGENT ORCHESTRATOR v3.0 - Enterprise Demo")
    print("=" * 70)
    
    # Cria orquestrador
    orchestrator = MultiAgentOrchestrator(max_workers=4, enable_events=True)
    
    # Registra handlers de eventos
    def on_task_completed(event: Event):
        task_data = event.data.get("task", {})
        print(f"✅ Task completed: {task_data.get('description', 'Unknown')[:50]}")
    
    def on_task_failed(event: Event):
        task_data = event.data.get("task", {})
        error = event.data.get("error", "Unknown error")
        print(f"❌ Task failed: {task_data.get('description', 'Unknown')[:50]} - {error[:50]}")
    
    orchestrator.on_event(EventType.TASK_COMPLETED, on_task_completed)
    orchestrator.on_event(EventType.TASK_FAILED, on_task_failed)
    
    # Cria agentes
    code_agent = create_code_agent()
    data_agent = create_data_agent()
    security_agent = create_security_agent()
    monitoring_agent = create_monitoring_agent()
    
    # Registra agentes
    orchestrator.register_agent(code_agent)
    orchestrator.register_agent(data_agent)
    orchestrator.register_agent(security_agent)
    orchestrator.register_agent(monitoring_agent)
    
    # Inicia orquestrador
    orchestrator.start()
    
    # Submete tarefas variadas
    tasks = [
        {
            "description": "Generate Python monitoring script",
            "payload": {"prompt": "monitoring system", "language": "python"},
            "capabilities": ["code_generation", "python"]
        },
        {
            "description": "Analyze system metrics",
            "payload": {"data": list(range(100)), "type": "statistical"},
            "capabilities": ["data_analysis", "statistics"]
        },
        {
            "description": "Run security scan",
            "payload": {"scan_type": "vulnerability", "target": "localhost"},
            "capabilities": ["security_scan"]
        },
        {
            "description": "Collect system metrics",
            "payload": {"resource": "system"},
            "capabilities": ["monitoring", "metrics_collection"]
        },
        {
            "description": "Generate JavaScript web interface",
            "payload": {"prompt": "dashboard UI", "language": "javascript"},
            "capabilities": ["code_generation", "javascript"]
        }
    ]
    
    print("\n📋 Submitting tasks...\n")
    
    task_ids = []
    for task in tasks:
        task_id = orchestrator.submit_task(
            description=task["description"],
            payload=task["payload"],
            required_capabilities=task["capabilities"],
            priority=TaskPriority.NORMAL if "analyze" not in task["description"] else TaskPriority.HIGH
        )
        task_ids.append(task_id)
        print(f"  ✓ {task['description']} (ID: {task_id[:8]}...)")
    
    # Aguarda processamento
    print("\n⏳ Processing tasks...\n")
    time.sleep(10)
    
    # Exibe status final
    print("\n" + "=" * 70)
    print("📊 FINAL STATUS")
    print("=" * 70)
    
    # Status dos agentes
    print("\n🤖 Agent Status:")
    for agent_status in orchestrator.get_agents_status():
        print(f"  • {agent_status['id']} ({agent_status['role']}) - {agent_status['status']}")
        print(f"    Tasks: {agent_status['metrics']['total_tasks']} | "
              f"Success Rate: {agent_status['metrics']['success_rate']}")
    
    # Estatísticas do sistema
    stats = orchestrator.get_statistics()
    print(f"\n📈 System Statistics:")
    print(f"  • Total tasks processed: {stats['tasks']['total_processed']}")
    print(f"  • Success rate: {stats['tasks']['success_rate']:.1f}%")
    print(f"  • Queue size: {stats['queue_size']}")
    print(f"  • Active agents: {stats['agents']['total']}")
    
    # Status individual das tarefas
    print(f"\n📝 Task Status:")
    for task_id in task_ids:
        status = orchestrator.get_task_status(task_id)
        if status:
            print(f"  • {status['description'][:40]:40} - {status['status']}")
    
    # Para o orquestrador
    orchestrator.stop()
    
    print("\n✅ Demo completed successfully!")


if __name__ == "__main__":
    demo()
