#!/usr/bin/env python3
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("ATENA_LOCAL_LLM_MODEL", "qwen2.5:3b-instruct")
os.environ.setdefault("ATENA_LLM_TIMEOUT_S", "300")

from core.atena_llm_router import AtenaLLMRouterAdvanced


async def main() -> None:
    router = AtenaLLMRouterAdvanced()
    ok, detail = router.prepare_free_local_model()
    response = await router.generate(
        "Explique em duas frases o que significa medir melhoria cognitiva sem confundir correção do avaliador com aprendizagem.",
        prefer_provider="local",
        temperature=0.2,
        max_tokens=180,
    )
    print(json.dumps({"prepared": ok, "detail": detail, "backend": router.current(), "provider": response.provider, "model": response.model, "response": response.content, "latency_ms": response.latency_ms}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
