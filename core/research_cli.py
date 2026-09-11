"""CLI para pesquisa web profunda da Atena."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.research_orchestrator import ResearchError, format_terminal_result, run_deep_research


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="atena research",
        description="Pesquisa a internet, sintetiza evidências e salva um relatório auditável.",
    )
    parser.add_argument("question", nargs="+", help="Pergunta ou tema a pesquisar")
    parser.add_argument("--topic", default=None, help="Domínio opcional: tecnologia, ciência, saúde, direito ou finanças")
    parser.add_argument("--limit-per-query", type=int, default=5, help="Máximo de resultados por subconsulta")
    parser.add_argument("--max-sources", type=int, default=12, help="Máximo de fontes no relatório")
    parser.add_argument("--no-llm", action="store_true", help="Entrega somente síntese baseada nos trechos recuperados")
    parser.add_argument("--json", action="store_true", help="Imprime o resultado estruturado em JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = run_deep_research(
            " ".join(args.question),
            topic=args.topic,
            limit_per_query=args.limit_per_query,
            max_sources=args.max_sources,
            use_llm=not args.no_llm,
        )
    except ResearchError as exc:
        print(f"Erro de pesquisa: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("Pesquisa interrompida.", file=sys.stderr)
        return 130

    if args.json:
        import json

        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(format_terminal_result(result))
    return 0 if result.get("status") == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
