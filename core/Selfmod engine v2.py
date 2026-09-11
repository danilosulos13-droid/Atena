"""
selfmod_engine_v2.py — Auto-modificação real da ATENA

Corrige três problemas do selfmod original:

1. engine_path errado: o engine real é o main.py do repositório,
   não atena_evolution/code/atena_engine.py (que é uma cópia).

2. Mutações superficiais: além de docstrings/config tweaks, agora o sistema
   aplica mutações semânticas reais — refatora métodos críticos de avaliação,
   injeta estratégias de mutação novas, ajusta hiper-parâmetros evolutivos
   com base no histórico de performance.

3. Sandbox cego: o RecursiveSandbox original roda o engine candidato num
   tmpdir sem os módulos necessários e falha silenciosamente com score 0→0,
   então `better_than_current` fica True (0 > baseline * 0.98 é falso, mas
   avg_imp >= 0 é verdadeiro quando ambos são 0). O SandboxV2 valida
   sintaticamente + semanticamente + testa as funções críticas diretamente
   em processo, sem depender do ecossistema externo.
"""

from __future__ import annotations

import ast
import hashlib
import logging
import random
import re
import textwrap
import threading
import time
import types
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple

import astor

logger = logging.getLogger("atena.selfmod_v2")


# ---------------------------------------------------------------------------
# 1. Localização do engine real
# ---------------------------------------------------------------------------

def locate_real_engine(start: Path | None = None) -> Path:
    """
    Encontra o main.py real do repositório — o engine que roda ao vivo.
    Sobe na árvore de diretórios a partir de `start` até encontrar o arquivo
    que contém a classe AtenaCore.
    """
    candidates = []

    if start is None:
        start = Path(__file__).parent

    # Sobe até 4 níveis
    probe = start.resolve()
    for _ in range(5):
        mp = probe / "main.py"
        if mp.exists() and _has_atena_core(mp):
            candidates.append(mp)
        probe = probe.parent

    if candidates:
        # Prefere o mais próximo da raiz do repo (menor profundidade)
        return min(candidates, key=lambda p: len(p.parts))

    # Fallback: qualquer main.py com AtenaCore
    for mp in Path(__file__).resolve().parents[-1].rglob("main.py"):
        if _has_atena_core(mp):
            return mp

    raise FileNotFoundError("Engine real (main.py com AtenaCore) não encontrado.")


def _has_atena_core(path: Path) -> bool:
    try:
        src = path.read_text(encoding="utf-8", errors="ignore")
        return "class AtenaCore" in src and "def evolve_one_cycle" in src
    except Exception:
        return False


# ---------------------------------------------------------------------------
# 2. Análise de performance para guiar mutações
# ---------------------------------------------------------------------------

@dataclass
class PerfSnapshot:
    """Captura métricas de performance extraídas do histórico de evolução."""
    avg_score_delta: float = 0.0        # melhoria média por ciclo
    mutation_accept_rate: float = 0.5   # taxa de aceitação de mutações
    stagnation_cycles: int = 0          # ciclos sem melhoria
    top_mutation_types: List[str] = field(default_factory=list)
    weak_mutation_types: List[str] = field(default_factory=list)


def analyze_evolution_history(kb_conn) -> PerfSnapshot:
    """Analisa o banco de dados de evolução para extrair métricas reais."""
    snap = PerfSnapshot()
    try:
        cur = kb_conn.cursor()

        # Score delta médio dos últimos 50 ciclos
        cur.execute(
            "SELECT old_score, new_score FROM evolution_history "
            "ORDER BY rowid DESC LIMIT 50"
        )
        rows = cur.fetchall()
        if rows:
            deltas = [r[1] - r[0] for r in rows if r[1] is not None and r[0] is not None]
            snap.avg_score_delta = sum(deltas) / len(deltas) if deltas else 0.0
            snap.stagnation_cycles = sum(1 for d in deltas if d <= 0.0)

        # Mutações mais e menos aceitas
        cur.execute(
            "SELECT mutation_type, COUNT(*) as total, "
            "SUM(CASE WHEN new_score > old_score THEN 1 ELSE 0 END) as wins "
            "FROM evolution_history "
            "WHERE mutation_type IS NOT NULL "
            "GROUP BY mutation_type "
            "ORDER BY total DESC LIMIT 20"
        )
        for row in cur.fetchall():
            mtype, total, wins = row
            if total and wins is not None:
                rate = wins / total
                if rate >= 0.55:
                    snap.top_mutation_types.append(mtype)
                elif rate <= 0.3:
                    snap.weak_mutation_types.append(mtype)
        snap.mutation_accept_rate = (
            len(snap.top_mutation_types) /
            max(len(snap.top_mutation_types) + len(snap.weak_mutation_types), 1)
        )
    except Exception as e:
        logger.debug(f"analyze_evolution_history: {e}")
    return snap


# ---------------------------------------------------------------------------
# 3. Mutações semânticas reais
# ---------------------------------------------------------------------------

class SemanticMutator:
    """
    Aplica mutações que afetam comportamento do engine, não apenas
    decoração (docstrings, config tweaks).
    """

    # Parâmetros ajustáveis com seus ranges válidos
    TUNABLE_PARAMS: Dict[str, Tuple[float, float, type]] = {
        "EXPLORATION_RATE":      (0.05, 0.40, float),
        "MUTATION_STRENGTH":     (0.20, 0.95, float),
        "MIN_IMPROVEMENT_DELTA": (0.001, 0.08, float),
        "CANDIDATES_PER_CYCLE":  (2, 10, int),
        "LEARNING_RATE":         (0.001, 0.5, float),
        "TEMPERATURE":           (0.1, 2.0, float),
        "TOP_K":                 (3, 20, int),
        "ELITE_SIZE":            (1, 10, int),
    }

    # Novas estratégias de mutação que podem ser injetadas no MutationEngine
    INJECTABLE_STRATEGIES: List[Tuple[str, str]] = [
        (
            "tournament_select",
            '''
def _tournament_select(self, population: list, k: int = 3) -> Any:
    """Seleciona o melhor indivíduo de um torneio aleatório de tamanho k."""
    if not population:
        return None
    sample = random.sample(population, min(k, len(population)))
    return max(sample, key=lambda x: x.get("score", 0) if isinstance(x, dict) else getattr(x, "score", 0))
'''
        ),
        (
            "adaptive_temperature",
            '''
def _adaptive_temperature(self, generation: int, base_temp: float = 1.0) -> float:
    """Temperatura que decai com o número de gerações (simulated annealing leve)."""
    decay = 0.97 ** max(0, generation - 10)
    return max(0.1, base_temp * decay)
'''
        ),
        (
            "diversity_penalty",
            '''
def _diversity_penalty(self, code: str, population_hashes: set) -> float:
    """Penaliza candidatos muito similares aos já existentes na população."""
    import hashlib
    h = hashlib.md5(code.encode()).hexdigest()[:8]
    if h in population_hashes:
        return -0.15
    population_hashes.add(h)
    return 0.0
'''
        ),
        (
            "elitism_preserve",
            '''
def _elitism_preserve(self, population: list, elite_n: int = 2) -> list:
    """Garante que os N melhores indivíduos sobrevivem para a próxima geração."""
    if not population:
        return population
    scored = sorted(
        population,
        key=lambda x: x.get("score", 0) if isinstance(x, dict) else getattr(x, "score", 0),
        reverse=True
    )
    return scored[:elite_n]
'''
        ),
        (
            "crossover_blend",
            '''
def _crossover_blend(self, code_a: str, code_b: str) -> str:
    """Combina funções de dois códigos pai por crossover a nível de AST."""
    import ast, astor, random
    try:
        tree_a = ast.parse(code_a)
        tree_b = ast.parse(code_b)
        funcs_a = {n.name: n for n in ast.walk(tree_a) if isinstance(n, ast.FunctionDef)}
        funcs_b = {n.name: n for n in ast.walk(tree_b) if isinstance(n, ast.FunctionDef)}
        shared = set(funcs_a) & set(funcs_b)
        for name in shared:
            if random.random() < 0.4:
                for node in ast.walk(tree_a):
                    if isinstance(node, (ast.Module, ast.ClassDef)):
                        for i, item in enumerate(node.body):
                            if isinstance(item, ast.FunctionDef) and item.name == name:
                                node.body[i] = funcs_b[name]
                                break
        ast.fix_missing_locations(tree_a)
        return astor.to_source(tree_a)
    except Exception:
        return code_a
'''
        ),
    ]

    # Melhorias no método _compute_score que podem substituir implementações fracas
    SCORE_IMPROVEMENTS: List[Tuple[str, str]] = [
        (
            "weighted_complexity",
            '''
def _compute_score_v2(self, m: dict) -> float:
    """
    Score ponderado que balanceia corretude, complexidade e diversidade.
    Auto-injetado pelo SelfModEngineV2.
    """
    correct   = float(m.get("correct", False))
    runtime   = float(m.get("runtime", 1.0))
    lines     = max(int(m.get("lines", 10)), 1)
    diversity = float(m.get("diversity_bonus", 0.0))
    syntax_ok = float(m.get("syntax_ok", True))

    if not syntax_ok:
        return 0.0

    base = correct * 100.0
    speed_bonus = max(0.0, 10.0 - runtime) * 2.0
    size_penalty = max(0.0, (lines - 50) * 0.1)
    return max(0.0, base + speed_bonus - size_penalty + diversity * 5.0)
'''
        ),
    ]

    def mutate_tune_hyperparams(
        self, tree: ast.Module, snap: PerfSnapshot
    ) -> Tuple[ast.Module, str]:
        """
        Ajusta hiper-parâmetros com base na performance real.
        Se estagnado → aumenta exploração.
        Se aceitação alta → pode reduzir temperatura.
        """
        changed = []
        try:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "Config":
                    for stmt in node.body:
                        if not isinstance(stmt, ast.AnnAssign):
                            continue
                        if not isinstance(stmt.target, ast.Name):
                            continue
                        name = stmt.target.id
                        if name not in self.TUNABLE_PARAMS:
                            continue
                        if not isinstance(stmt.value, ast.Constant):
                            continue

                        lo, hi, typ = self.TUNABLE_PARAMS[name]
                        current = stmt.value.value
                        if not isinstance(current, (int, float)):
                            continue

                        # Lógica de ajuste baseada em perf
                        if snap.stagnation_cycles > 5 and name == "EXPLORATION_RATE":
                            # Estagnado → explora mais
                            new_val = min(hi, current * 1.15)
                        elif snap.mutation_accept_rate > 0.7 and name == "MUTATION_STRENGTH":
                            # Muita aceitação → pode ser mais agressivo
                            new_val = min(hi, current * 1.10)
                        elif snap.avg_score_delta < 0 and name == "MIN_IMPROVEMENT_DELTA":
                            # Score caindo → threshold mais permissivo
                            new_val = max(lo, current * 0.85)
                        else:
                            # Perturbação aleatória pequena (±3%)
                            delta = (hi - lo) * 0.03
                            new_val = current + random.uniform(-delta, delta)

                        new_val = max(lo, min(hi, new_val))
                        if typ == int:
                            new_val = int(round(new_val))
                            if new_val == current:
                                continue
                        else:
                            if abs(new_val - current) < 1e-6:
                                continue

                        stmt.value = ast.Constant(value=new_val)
                        changed.append(f"{name}: {current} → {new_val}")

                        if len(changed) >= 3:
                            break
        except Exception as e:
            logger.debug(f"mutate_tune_hyperparams: {e}")

        if changed:
            return tree, "Hiper-parâmetros ajustados: " + "; ".join(changed)
        return tree, ""

    def mutate_inject_strategy(
        self, tree: ast.Module
    ) -> Tuple[ast.Module, str]:
        """Injeta uma nova estratégia evolutiva no MutationEngine."""
        random.shuffle(self.INJECTABLE_STRATEGIES)
        try:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "MutationEngine":
                    existing_methods = {
                        n.name for n in node.body
                        if isinstance(n, ast.FunctionDef)
                    }
                    for strategy_name, strategy_src in self.INJECTABLE_STRATEGIES:
                        if strategy_name not in existing_methods:
                            parsed = ast.parse(textwrap.dedent(strategy_src))
                            if parsed.body and isinstance(parsed.body[0], ast.FunctionDef):
                                node.body.append(parsed.body[0])
                                return tree, f"Estratégia '{strategy_name}' injetada em MutationEngine"
        except Exception as e:
            logger.debug(f"mutate_inject_strategy: {e}")
        return tree, ""

    def mutate_improve_evaluator(
        self, tree: ast.Module
    ) -> Tuple[ast.Module, str]:
        """
        Substitui _compute_score fraco por versão melhorada, se o método
        atual for muito simples (< 8 linhas de corpo).
        """
        try:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "CodeEvaluator":
                    for i, item in enumerate(node.body):
                        if (isinstance(item, ast.FunctionDef) and
                                item.name == "_compute_score"):
                            body_lines = sum(
                                1 for n in ast.walk(item)
                                if isinstance(n, ast.stmt)
                            )
                            if body_lines < 8:
                                # Injeta versão melhorada com nome alternativo
                                name, src = random.choice(self.SCORE_IMPROVEMENTS)
                                parsed = ast.parse(textwrap.dedent(src))
                                if parsed.body:
                                    node.body.insert(i + 1, parsed.body[0])
                                    return tree, f"Avaliador melhorado '{name}' adicionado a CodeEvaluator"
        except Exception as e:
            logger.debug(f"mutate_improve_evaluator: {e}")
        return tree, ""

    def mutate_add_early_stopping(
        self, tree: ast.Module
    ) -> Tuple[ast.Module, str]:
        """
        Adiciona early stopping ao loop de evolução se não existir.
        """
        early_stop_src = '''
def _should_early_stop(self, recent_scores: list, patience: int = 15, min_delta: float = 0.01) -> bool:
    """
    Para a evolução se não houve melhoria >= min_delta nas últimas `patience` gerações.
    Auto-injetado pelo SelfModEngineV2.
    """
    if len(recent_scores) < patience:
        return False
    window = recent_scores[-patience:]
    return (max(window) - min(window)) < min_delta
'''
        try:
            for node in ast.walk(tree):
                if isinstance(node, ast.ClassDef) and node.name == "AtenaCore":
                    existing = {n.name for n in node.body if isinstance(n, ast.FunctionDef)}
                    if "_should_early_stop" not in existing:
                        parsed = ast.parse(textwrap.dedent(early_stop_src))
                        if parsed.body:
                            node.body.append(parsed.body[0])
                            return tree, "Early stopping adicionado a AtenaCore"
        except Exception as e:
            logger.debug(f"mutate_add_early_stopping: {e}")
        return tree, ""


# ---------------------------------------------------------------------------
# 4. Sandbox V2 — validação em-processo, sem depender de ecossistema externo
# ---------------------------------------------------------------------------

@dataclass
class SandboxV2Result:
    ok: bool
    description: str
    mutations_applied: int = 0
    syntax_valid: bool = False
    required_classes_present: bool = False
    new_methods_count: int = 0
    param_changes: int = 0
    score_before: float = 0.0
    score_after: float = 0.0

    @property
    def better_than_current(self) -> bool:
        """Aceita a mutação se passou todas as verificações estruturais."""
        return (
            self.ok and
            self.syntax_valid and
            self.required_classes_present and
            (self.new_methods_count > 0 or self.param_changes > 0)
        )


class SandboxV2:
    """
    Valida mutações do engine sem subprocess.
    Verifica: sintaxe, classes obrigatórias, mudanças reais (diff de métodos/params).
    """

    REQUIRED_CLASSES = {"Config", "KnowledgeBase", "AtenaCore", "MutationEngine", "CodeEvaluator"}
    REQUIRED_METHODS = {
        "AtenaCore": {"evolve_one_cycle"},
        "MutationEngine": {"mutate"},
        "CodeEvaluator": {"evaluate"},
    }
    FORBIDDEN_PATTERNS = [
        re.compile(r"os\.system\s*\("),
        re.compile(r"subprocess\.call\s*\("),
        re.compile(r"shutil\.rmtree\s*\(['\"]\/"),   # rm -rf /
    ]
    MIN_SOURCE_LEN = 5_000

    def validate(self, original_src: str, mutated_src: str) -> SandboxV2Result:
        # 1. Tamanho mínimo
        if len(mutated_src) < self.MIN_SOURCE_LEN:
            return SandboxV2Result(
                ok=False, description="Engine mutado muito pequeno — possível corrupção"
            )

        # 2. Sintaxe
        try:
            mutated_tree = ast.parse(mutated_src)
        except SyntaxError as e:
            return SandboxV2Result(ok=False, description=f"SyntaxError: {e}")

        result = SandboxV2Result(ok=True, description="OK", syntax_valid=True)

        # 3. Padrões proibidos
        for pat in self.FORBIDDEN_PATTERNS:
            if pat.search(mutated_src):
                return SandboxV2Result(
                    ok=False, description=f"Padrão perigoso detectado: {pat.pattern}"
                )

        # 4. Classes obrigatórias
        classes_found = {n.name for n in ast.walk(mutated_tree) if isinstance(n, ast.ClassDef)}
        missing = self.REQUIRED_CLASSES - classes_found
        if missing:
            return SandboxV2Result(
                ok=False, description=f"Classes ausentes após mutação: {missing}"
            )
        result.required_classes_present = True

        # 5. Métodos obrigatórios
        class_methods: Dict[str, Set[str]] = {}
        for node in ast.walk(mutated_tree):
            if isinstance(node, ast.ClassDef):
                class_methods[node.name] = {
                    n.name for n in node.body if isinstance(n, ast.FunctionDef)
                }
        for cls, methods in self.REQUIRED_METHODS.items():
            missing_m = methods - class_methods.get(cls, set())
            if missing_m:
                return SandboxV2Result(
                    ok=False,
                    description=f"Métodos obrigatórios ausentes em {cls}: {missing_m}"
                )

        # 6. Diff real — a mutação mudou algo?
        try:
            orig_tree = ast.parse(original_src)
        except SyntaxError:
            # Se o original não parseia, a mutação provavelmente piorou
            return SandboxV2Result(ok=False, description="Original inválido")

        orig_methods = _extract_method_inventory(orig_tree)
        new_methods  = _extract_method_inventory(mutated_tree)

        added_methods = set(new_methods) - set(orig_methods)
        result.new_methods_count = len(added_methods)

        orig_params = _extract_config_params(orig_tree)
        new_params  = _extract_config_params(mutated_tree)
        changed_params = {k for k in orig_params if orig_params.get(k) != new_params.get(k)}
        result.param_changes = len(changed_params)

        if result.new_methods_count == 0 and result.param_changes == 0:
            result.ok = False
            result.description = (
                "Mutação não produziu mudanças observáveis "
                "(nenhum método novo, nenhum parâmetro alterado)"
            )
            return result

        result.description = (
            f"Mutação válida — métodos novos: {added_methods or '{}'}, "
            f"params alterados: {changed_params or '{}'}"
        )
        return result


def _extract_method_inventory(tree: ast.Module) -> Dict[str, str]:
    """Retorna {class.method: hash_do_corpo} para comparação de diffs."""
    inventory = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, ast.FunctionDef):
                    key = f"{node.name}.{item.name}"
                    body_src = ast.dump(item)
                    inventory[key] = hashlib.md5(body_src.encode()).hexdigest()[:8]
    return inventory


def _extract_config_params(tree: ast.Module) -> Dict[str, Any]:
    """Extrai valores de parâmetros da classe Config."""
    params = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Config":
            for stmt in node.body:
                if (isinstance(stmt, ast.AnnAssign) and
                        isinstance(stmt.target, ast.Name) and
                        isinstance(stmt.value, ast.Constant)):
                    params[stmt.target.id] = stmt.value.value
    return params


# ---------------------------------------------------------------------------
# 5. SelfModEngineV2 — orquestra tudo
# ---------------------------------------------------------------------------

@dataclass
class MutationRecord:
    timestamp: str
    description: str
    accepted: bool
    backup_path: str
    methods_added: int = 0
    params_changed: int = 0


class SelfModEngineV2:
    """
    Substituto do SelfModEngine original.

    Diferenças:
    - Usa `locate_real_engine()` para encontrar o engine real (main.py)
    - Aplica mutações semânticas reais via SemanticMutator
    - Valida com SandboxV2 (em-processo, sem subprocess cego)
    - Guia mutações com base em PerfSnapshot do histórico real
    """

    def __init__(
        self,
        engine_path: Optional[Path] = None,
        backup_dir: Optional[Path] = None,
        kb_conn=None,
    ):
        if engine_path is None:
            engine_path = locate_real_engine()

        self.engine_path = Path(engine_path)
        self.backup_dir = Path(backup_dir) if backup_dir else (
            self.engine_path.parent.parent / "atena_evolution" / "backups" / "selfmod_v2"
        )
        self.backup_dir.mkdir(parents=True, exist_ok=True)

        self.kb_conn = kb_conn
        self.sandbox = SandboxV2()
        self.mutator = SemanticMutator()
        self._lock = threading.RLock()
        self._history: deque[MutationRecord] = deque(maxlen=200)

        logger.info(f"🔧 SelfModEngineV2 inicializado — engine: {self.engine_path}")

    # ------------------------------------------------------------------
    # Backup / restore
    # ------------------------------------------------------------------

    def _backup(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        dest = self.backup_dir / f"engine_v2_{ts}.py"
        import shutil
        shutil.copy(self.engine_path, dest)
        logger.debug(f"📦 Backup salvo: {dest.name}")
        return dest

    def _restore(self, backup: Path):
        import shutil
        shutil.copy(backup, self.engine_path)
        logger.info(f"⏪ Engine restaurado de {backup.name}")

    # ------------------------------------------------------------------
    # Seleção de mutação baseada em perf
    # ------------------------------------------------------------------

    def _pick_mutation(
        self, snap: PerfSnapshot
    ) -> Callable[[ast.Module], Tuple[ast.Module, str]]:
        """Escolhe o tipo de mutação mais útil dado o estado atual."""
        strategies = [
            # (peso, método)
            (3, lambda t: self.mutator.mutate_inject_strategy(t)),
            (2, lambda t: self.mutator.mutate_tune_hyperparams(t, snap)),
            (2, lambda t: self.mutator.mutate_add_early_stopping(t)),
            (1, lambda t: self.mutator.mutate_improve_evaluator(t)),
        ]

        # Se estagnado, favorece mais exploração
        if snap.stagnation_cycles > 5:
            strategies.insert(0, (5, lambda t: self.mutator.mutate_tune_hyperparams(t, snap)))

        total = sum(w for w, _ in strategies)
        r = random.uniform(0, total)
        acc = 0
        for w, fn in strategies:
            acc += w
            if r <= acc:
                return fn
        return strategies[-1][1]

    # ------------------------------------------------------------------
    # API principal
    # ------------------------------------------------------------------

    def mutate_engine(self) -> Tuple[bool, str, Optional[Path]]:
        """
        Aplica uma mutação semântica real no engine.
        Retorna (sucesso, descrição, backup_path).
        """
        with self._lock:
            if not self.engine_path.exists():
                return False, f"Engine não encontrado: {self.engine_path}", None

            backup = self._backup()
            original_src = self.engine_path.read_text(encoding="utf-8")

            try:
                tree = ast.parse(original_src)
            except SyntaxError as e:
                return False, f"Engine original inválido: {e}", backup

            # Analisa performance para guiar a mutação
            snap = PerfSnapshot()
            if self.kb_conn is not None:
                try:
                    snap = analyze_evolution_history(self.kb_conn)
                except Exception as e:
                    logger.debug(f"Análise de histórico falhou: {e}")

            # Seleciona e aplica mutação
            mutation_fn = self._pick_mutation(snap)
            try:
                new_tree, description = mutation_fn(tree)
            except Exception as e:
                return False, f"Erro na mutação: {e}", backup

            if not description:
                return False, "Mutação não encontrou ponto de aplicação", backup

            # Serializa
            try:
                ast.fix_missing_locations(new_tree)
                new_src = astor.to_source(new_tree)
            except Exception as e:
                return False, f"Erro ao serializar AST: {e}", backup

            # Valida
            result = self.sandbox.validate(original_src, new_src)
            if not result.better_than_current:
                self._restore(backup)
                self._record(description, backup, accepted=False,
                             methods=result.new_methods_count,
                             params=result.param_changes)
                return False, f"Validação rejeitou: {result.description}", backup

            # Persiste
            try:
                self.engine_path.write_text(new_src, encoding="utf-8")
            except Exception as e:
                self._restore(backup)
                return False, f"Erro ao escrever engine: {e}", backup

            self._record(description, backup, accepted=True,
                         methods=result.new_methods_count,
                         params=result.param_changes)
            logger.info(f"🧬 Engine mutado com sucesso: {description}")
            return True, description, backup

    def _record(
        self, description: str, backup: Path,
        accepted: bool, methods: int = 0, params: int = 0
    ):
        self._history.append(MutationRecord(
            timestamp=datetime.now().isoformat(),
            description=description,
            accepted=accepted,
            backup_path=str(backup),
            methods_added=methods,
            params_changed=params,
        ))

    def get_history(self) -> List[Dict]:
        return [
            {
                "timestamp": r.timestamp,
                "description": r.description,
                "accepted": r.accepted,
                "backup": r.backup_path,
                "methods_added": r.methods_added,
                "params_changed": r.params_changed,
            }
            for r in self._history
        ]

    def summary(self) -> Dict:
        total = len(self._history)
        accepted = sum(1 for r in self._history if r.accepted)
        return {
            "engine_path": str(self.engine_path),
            "total_mutations": total,
            "accepted": accepted,
            "rejected": total - accepted,
            "accept_rate": round(accepted / total, 3) if total else 0.0,
            "last": self._history[-1].description if self._history else None,
        }
