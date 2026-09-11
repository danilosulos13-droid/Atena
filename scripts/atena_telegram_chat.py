#!/usr/bin/env python3
"""Ponte Telegram ↔ Atena/Ollama para conversas autorizadas."""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

import aiohttp

from core.audio_gateway import AudioGateway, AudioGatewayError
from core.learning_audio import latest_learning_spoken_text
from core.memory_store import MemoryStore
from core.math_solver import MathSolverError, solve_and_verify, solve_math_image, solve_math_text
from core.google_calendar_client import GoogleCalendarClient, GoogleCalendarNotConfigured, format_event
from core.x_news_research import XNewsResearch, XNotConfigured
from core.robot_command_gateway import RobotCommand, RobotCommandGateway, load_registry, parse_robot_voice_intent
from core.tasker_client import TaskerClient, TaskerDispatchError, TaskerNotConfigured
from core.universal_task_router import TaskIntent, confirmation_prompt as task_confirmation_prompt, parse_task_intent
from core.video_analysis import (
    VideoAnalysisError,
    analyze_video_file,
    analyze_video_url_remote,
    build_consideration_prompt,
    extract_video_url,
)
from core.vision_analysis import VisionAnalysisError, analyze_image_with_ocr_fallback
from core.math_vision_pipeline import MathVisionError, format_math_solution, solve_math_image as solve_math_image_vision
from scripts.daily_news_digest import (
    _deduplicate_global,
    collect_public_search_fallback,
    collect_rss,
    collect_x,
    format_digest,
    normalize_items_to_portuguese,
)
from core.workspace_actions import (
    WorkspaceIntent,
    confirmation_prompt,
    is_cancellation,
    is_confirmation,
    parse_workspace_intent,
)
from core.human_feedback import record_feedback, record_interaction
from core.home_assistant_gateway import HomeAssistantError, HomeAssistantGateway

ROOT = Path(os.getenv("ATENA_ROOT", Path(__file__).resolve().parents[1]))
MEMORY_DB = Path(os.getenv("ATENA_MEMORY_DB", str(ROOT / "atena_evolution" / "memory.sqlite3")))
TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
OLLAMA_CHAT = os.getenv("ATENA_OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")
MODEL = os.getenv("ATENA_LOCAL_MODEL", "qwen2.5:3b-instruct")
SESSION_PATH = Path(os.getenv("ATENA_TELEGRAM_SESSION_PATH", str(ROOT / "data" / "telegram_sessions.json")))
VOICE_SETTINGS_PATH = Path(os.getenv("ATENA_TELEGRAM_VOICE_SETTINGS_PATH", str(ROOT / "data" / "telegram_voice_settings.json")))
MAX_HISTORY = 12
MAX_MESSAGE = 3900


def infer_task_type(text: str) -> str:
    lowered = text.casefold()
    if any(marker in lowered for marker in ("últimas notícias", "notícia", "pesquise", "fontes", "nasa", "atualmente", "hoje")):
        return "web_research"
    if any(marker in lowered for marker in ("código", "script", "python", "github", "pull request", "bug", "programar")):
        return "code"
    if any(marker in lowered for marker in ("privado", "senha", "e-mail da empresa", "email da empresa")):
        return "private"
    return "telegram"

logging.basicConfig(level=os.getenv("ATENA_TELEGRAM_LOG_LEVEL", "INFO"))
log = logging.getLogger("atena.telegram")


class TelegramError(RuntimeError):
    pass


def required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise TelegramError(f"variável ausente: {name}")
    return value


def allowed_chat(chat_id: int, configured: str) -> bool:
    return str(chat_id) in {item.strip() for item in configured.split(",") if item.strip()}


def clip(text: str, limit: int = MAX_MESSAGE) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[: limit - 1] + "…"


def load_sessions() -> dict[str, list[dict[str, str]]]:
    try:
        data = json.loads(SESSION_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_sessions(sessions: dict[str, list[dict[str, str]]]) -> None:
    SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
    SESSION_PATH.write_text(json.dumps(sessions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def load_voice_settings() -> set[str]:
    try:
        data = json.loads(VOICE_SETTINGS_PATH.read_text(encoding="utf-8"))
        return {str(item) for item in data if str(item).strip()} if isinstance(data, list) else set()
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()


def save_voice_settings(enabled: set[str]) -> None:
    VOICE_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    VOICE_SETTINGS_PATH.write_text(json.dumps(sorted(enabled), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class AtenaTelegramChat:
    def __init__(self, token: str, chat_allowlist: str, model: str = MODEL) -> None:
        self.token = token
        self.chat_allowlist = chat_allowlist
        self.model = model
        self.sessions = load_sessions()
        self.voice_enabled = load_voice_settings()
        self.pending_workspace: dict[str, Any] = {}
        self.pending_device: dict[str, Any] = {}
        self.pending_robot: dict[str, Any] = {}
        self.pending_home_assistant: dict[str, Any] = {}
        self.tasker = TaskerClient()
        self.robot_gateway = RobotCommandGateway(load_registry())
        self.audio = AudioGateway()
        self.home_assistant = HomeAssistantGateway()
        self.long_term_memory: Any | None = None
        self.offset = 0
        self.http: aiohttp.ClientSession | None = None

    async def api(self, method: str, payload: dict[str, Any] | None = None) -> Any:
        assert self.http is not None
        url = TELEGRAM_API.format(token=self.token, method=method)
        for attempt in range(3):
            try:
                async with self.http.post(url, json=payload or {}) as response:
                    body = await response.json(content_type=None)
                    if response.status != 200 or not body.get("ok"):
                        description = body.get("description", f"HTTP {response.status}")
                        raise TelegramError(f"Telegram {method}: {description}")
                    return body.get("result")
            except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
                if attempt == 2:
                    raise TelegramError(f"Telegram indisponível: {exc}") from exc
                await asyncio.sleep(2 ** attempt)
        raise TelegramError(f"Telegram {method} falhou")

    async def send(self, chat_id: int, text: str, *, feedback_id: str | None = None) -> None:
        payload: dict[str, Any] = {"chat_id": chat_id, "text": clip(text), "disable_web_page_preview": True}
        if feedback_id:
            payload["reply_markup"] = {
                "inline_keyboard": [[
                    {"text": "Aprovada", "callback_data": f"feedback:approved:{feedback_id}"},
                    {"text": "Rejeitada", "callback_data": f"feedback:rejected:{feedback_id}"},
                ]]
            }
        await self.api("sendMessage", payload)

    async def handle_feedback_callback(self, callback: dict[str, Any]) -> None:
        callback_id = str(callback.get("id", ""))
        data = str(callback.get("data", ""))
        parts = data.split(":")
        if len(parts) != 3 or parts[0] != "feedback" or parts[1] not in {"approved", "rejected"}:
            if callback_id:
                await self.api("answerCallbackQuery", {"callback_query_id": callback_id, "text": "Feedback inválido."})
            return
        message = callback.get("message") or {}
        chat_id = int((message.get("chat") or {}).get("id"))
        if not allowed_chat(chat_id, self.chat_allowlist):
            return
        record = await asyncio.to_thread(record_feedback, interaction_id=parts[2], label=parts[1], feedback_chat_id=chat_id)
        text = "Feedback registrado: resposta aprovada." if parts[1] == "approved" else "Feedback registrado: resposta rejeitada."
        if record is None:
            text = "Não encontrei a interação para registrar o feedback."
        if callback_id:
            await self.api("answerCallbackQuery", {"callback_query_id": callback_id, "text": text})

    async def send_voice(self, chat_id: int, audio_path: Path) -> None:
        assert self.http is not None
        url = TELEGRAM_API.format(token=self.token, method="sendVoice")
        data = aiohttp.FormData()
        data.add_field("chat_id", str(chat_id))
        data.add_field("voice", audio_path.read_bytes(), filename="atena.wav", content_type="audio/wav")
        async with self.http.post(url, data=data, timeout=aiohttp.ClientTimeout(total=60)) as response:
            body = await response.json(content_type=None)
            if response.status != 200 or not body.get("ok"):
                raise TelegramError(f"Telegram sendVoice: {body.get('description', response.status)}")

    async def download_file(self, file_id: str, suffix: str = ".ogg") -> tuple[bytes, str]:
        assert self.http is not None
        metadata = await self.api("getFile", {"file_id": file_id})
        file_path = str((metadata or {}).get("file_path", ""))
        if not file_path:
            raise TelegramError("Telegram não retornou o caminho do áudio")
        url = f"https://api.telegram.org/file/bot{self.token}/{file_path}"
        async with self.http.get(url, timeout=aiohttp.ClientTimeout(total=60)) as response:
            if response.status != 200:
                raise TelegramError(f"download de áudio HTTP {response.status}")
            data = await response.read()
        return data, suffix

    @staticmethod
    def needs_current_web(text: str) -> bool:
        markers = (
            "quando", "que dia", "qual dia", "horário", "hora", "próximo jogo",
            "joga", "jogar", "partida", "placar", "resultado", "hoje", "amanhã",
            "atualmente", "últimas notícias", "notícia", "cotação", "preço atual",
        )
        lowered = text.casefold()
        teams = ("santos", "palmeiras", "corinthians", "são paulo", "flamengo", "brasil")
        return any(marker in lowered for marker in markers) and any(team in lowered for team in teams) or any(marker in lowered for marker in ("hoje", "amanhã", "atualmente", "últimas notícias", "preço atual"))

    async def current_web_answer(self, chat_id: int, question: str) -> str:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from core.web_research import build_context, search_web
        from core.knowledge_base import KnowledgeBase

        evidence = await asyncio.to_thread(search_web, question, 8)
        context = build_context(question, evidence)
        # Toda pesquisa interativa também vira conhecimento recuperável, com URL e data.
        def persist() -> list[dict]:
            saved = []
            with KnowledgeBase(ROOT / "atena_evolution" / "memory.sqlite3") as kb:
                for item in evidence:
                    try:
                        doc_id, chunks, added = kb.add_document(
                            url=item.url, title=item.title, topic="pesquisa_interativa",
                            content=f"{item.title}\n{item.snippet}",
                            metadata={"query": question, "source": "web_research", "retrieved_at": __import__('datetime').datetime.now(__import__('datetime').timezone.utc).isoformat()},
                        )
                        saved.append({"id": doc_id, "chunks": chunks, "added": added, "url": item.url})
                    except Exception as exc:
                        log.warning("falha ao persistir fonte web: %s", exc)
            return saved
        saved = await asyncio.to_thread(persist)
        with KnowledgeBase(ROOT / "atena_evolution" / "memory.sqlite3") as kb:
            prior = kb.search(question, 6)
        prior_context = "\n\nConhecimento já salvo sobre o tema:\n" + json.dumps(prior, ensure_ascii=False)[:7000] if prior else ""
        legal_hint = (
            "Se for tema jurídico brasileiro, priorize legislação vigente e fontes oficiais (Planalto, STF, STJ, CNJ e tribunais), "
            "diferencie lei, jurisprudência, doutrina e opinião, e informe a data de consulta. Não apresente pesquisa como parecer jurídico."
            if any(x in question.casefold() for x in ("lei", "direito", "juríd", "advocacia", "processo", "contrato", "crime", "lgpd")) else ""
        )
        answer = await self.ollama(
            chat_id,
            "Responda diretamente à pergunta do usuário em português. A pesquisa foi fornecida pelo sistema. "
            "Use as fontes atuais e o conhecimento previamente salvo apenas quando houver suporte. Não invente fatos. "
            "Informe data/horário quando houver fonte suficiente e termine com 'Fontes:' e as URLs usadas. " + legal_hint + "\n\n" + context + prior_context,
            task_type="web_research",
        )
        return "ATENA — resposta atual\n\n" + answer

    async def ollama(self, chat_id: int, user_text: str, task_type: str | None = None) -> str:
        assert self.http is not None
        history = self.sessions.setdefault(str(chat_id), [])
        system = (
            "Você é a Atena, assistente técnica do projeto Atena-IA. "
            "Responda em português claro. Você pode explicar o repositório, "
            "as memórias e as propostas, mas não execute comandos, não revele "
            "segredos e não prometa que uma hipótese é aprendizagem comprovada. "
            "Quando uma ação exigir alteração, push, pagamento, exclusão ou produção, "
            "explique que é necessária confirmação e validação."
        )
        memory_context = ""
        if os.getenv("ATENA_ENABLE_VECTOR_MEMORY", "1").lower() not in {"0", "false", "no"}:
            try:
                if self.long_term_memory is None:
                    from core.long_term_memory import LongTermMemory
                    self.long_term_memory = await asyncio.to_thread(LongTermMemory)
                hits = await asyncio.to_thread(self.long_term_memory.recall, user_text, top_k=3)
                if hits:
                    memory_context = "\n\nMemórias semelhantes recuperadas; use apenas como contexto e não como prova:\n" + json.dumps(hits, ensure_ascii=False)[:7000]
            except Exception as exc:
                log.debug("memória vetorial indisponível nesta consulta: %s", type(exc).__name__)
        messages = [{"role": "system", "content": system}, *history[-MAX_HISTORY:], {"role": "user", "content": user_text + memory_context}]
        payload = {"model": self.model, "stream": False, "messages": messages, "options": {"temperature": 0.2, "num_predict": 550}}
        selected_task = task_type or infer_task_type(user_text)
        try:
            from core.atena_llm_router import get_router
            router = await get_router()
            routed = await router.generate(
                user_text,
                context="\n".join(f"{item['role']}: {item['content']}" for item in history[-MAX_HISTORY:]),
                task_type=selected_task,
                temperature=0.2,
                max_tokens=550,
            )
            answer = routed.content
        except Exception as exc:
            log.warning("roteador LLM indisponível; usando Ollama direto: %s", exc)
            async with self.http.post(OLLAMA_CHAT, json=payload, timeout=aiohttp.ClientTimeout(total=180)) as response:
                if response.status != 200:
                    raise TelegramError(f"Ollama HTTP {response.status}")
                data = await response.json(content_type=None)
                answer = str(data.get("message", {}).get("content", "Não consegui gerar uma resposta."))
        history.extend([{"role": "user", "content": clip(user_text, 1200)}, {"role": "assistant", "content": clip(answer, 1800)}])
        self.sessions[str(chat_id)] = history[-MAX_HISTORY:]
        save_sessions(self.sessions)
        return answer

    async def best_store_deals(self, minimum_discount: float = 50.0, limit: int = 10) -> str:
        """Consulta as melhores ofertas atuais sem enviar alertas duplicados."""
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from scripts.store_discount_alert import best_deals

        report = await asyncio.to_thread(
            best_deals,
            ["steam", "epic", "gog", "nuuvem", "humble"],
            minimum_discount,
            limit,
        )
        deals = report.get("deals", [])
        errors = report.get("errors", [])
        if not deals:
            suffix = "\n\nFalhas: " + "; ".join(errors) if errors else ""
            return "Não encontrei ofertas acima do limite informado agora." + suffix

        lines = [
            f"ATENA — melhores ofertas do dia (mínimo {minimum_discount:g}% OFF)",
            f"Consulta: {report.get('checked_at', '')}",
            "",
        ]
        for index, deal in enumerate(deals, 1):
            price = f" | {deal.get('current_price')}" if deal.get("current_price") else ""
            lines.append(
                f"{index}. [{deal.get('store', '').upper()}] {deal.get('title', 'Sem título')} — "
                f"{float(deal.get('discount_percent', 0)):g}% OFF{price}\n"
                f"{deal.get('product_url', '')}"
            )
        if errors:
            lines.extend(["", "Lojas com erro nesta consulta: " + "; ".join(errors)])
        return clip("\n".join(lines))

    async def analyze_video(self, chat_id: int, source: str, *, local_path: Path | None = None) -> str:
        """Analisa vídeo sem publicar, comentar ou executar ações externas."""
        try:
            if local_path is not None:
                result = await asyncio.to_thread(analyze_video_file, local_path, source_url=source)
            else:
                result = await asyncio.to_thread(analyze_video_url_remote, source)
            prompt = build_consideration_prompt(result)
            answer = await self.ollama(chat_id, prompt, task_type="video_analysis")
            header = "ATENA — análise de vídeo\n\n"
            source_line = f"Fonte: {result.source_url}\nDuração: {result.duration_seconds:.0f}s"
            warning = "\nAvisos: " + "; ".join(result.warnings) if result.warnings else ""
            return clip(header + source_line + warning + "\n\n" + answer)
        except VideoAnalysisError as exc:
            return f"ATENA — não consegui analisar este vídeo: {exc}."
        except Exception as exc:
            log.exception("falha na análise de vídeo")
            return f"ATENA — falha controlada na análise do vídeo: {type(exc).__name__}."

    async def main_news(self, topic: str = "") -> str:
        """Monta um briefing atual com RSS, fallback público e X opcional."""
        def collect() -> str:
            items, errors = collect_rss(limit_per_category=4)
            items, fallback_stats = collect_public_search_fallback(items, limit=12)
            errors.extend(
                f"search:{provider}:{metrics.get('errors', 0)} erros"
                for provider, metrics in fallback_stats.items()
                if metrics.get("errors", 0)
            )
            if os.getenv("ATENA_X_BEARER_TOKEN", "").strip():
                try:
                    items.extend(collect_x())
                except Exception as exc:
                    errors.append(f"X:{type(exc).__name__}")
            items = _deduplicate_global(items)
            if topic:
                terms = {word for word in topic.casefold().split() if len(word) > 2}
                filtered = [item for item in items if terms & set(item.title.casefold().split())]
                if filtered:
                    items = filtered
            items = normalize_items_to_portuguese(items, errors)
            return format_digest(items, errors, include_x=bool(os.getenv("ATENA_X_BEARER_TOKEN", "").strip()), max_items_per_category=3)
        return await asyncio.to_thread(collect)

    async def solve_math_image_message(self, path: Path) -> str:
        try:
            result = await asyncio.to_thread(solve_math_image, path)
            return result.format()
        except MathSolverError as exc:
            return f"ATENA — não consegui resolver a imagem: {exc}."

    async def send_learning_audio(self, chat_id: int) -> str:
        """Gera e envia um áudio curto do último relatório de aprendizagem."""
        spoken = latest_learning_spoken_text(ROOT)
        temporary: Path | None = None
        try:
            temporary = await asyncio.to_thread(self.audio.synthesize, spoken)
            await self.send_voice(chat_id, temporary)
            return "Enviei o áudio com o resumo do que pesquisei, aprendi e ainda preciso confirmar."
        except AudioGatewayError as exc:
            return f"Não consegui gerar o áudio da aprendizagem: {exc}. O resumo textual continua disponível em /aprendizagens."
        finally:
            AudioGateway.remove_file(temporary)

    def latest_proposal(self) -> dict[str, Any] | None:
        proposals = sorted((ROOT / "atena_evolution" / "proposals").glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not proposals:
            return None
        try:
            return json.loads(proposals[0].read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None

    async def command(self, chat_id: int, text: str) -> str | None:
        command = text.split()[0].lower().split("@", 1)[0]
        if command == "/start":
            return "Olá. Sou a ponte de conversa da Atena. Envie uma pergunta ou use /help."
        if command == "/help":
            return "Comandos: /status, /aprendizagens, /aprendizagens audio, /capabilities, /modelo, /reset, /voz on|off|status, /casa status|ligar|desligar, /matematica <conta ou equação>, /video <URL>, /noticias [tema], /pesquisar <tema>, /x <notícia>, /fila, /ofertas [mínimo%] [limite], /agenda, /agendar <evento>, /criar planilha <título>. Também aceito imagens para leitura de texto, códigos, diagramas e gráficos, URL pública de vídeo, abrir Spotify, tocar <música> de <artista>, pausar mídia, próxima música, status do celular. Ações sensíveis exigem confirmação."
        if command in {"/matematica", "/matemática", "/math"}:
            problem = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
            if not problem:
                return "Uso: /matematica <conta ou equação>. Exemplo: /matematica 2*(3+4) ou /matematica 2*x+1=7"
            try:
                return solve_and_verify(problem).format()
            except MathSolverError as exc:
                return f"ATENA — não consegui resolver: {exc}."
        if re.fullmatch(r"[0-9+\-*/%().,\s×÷^]+", text) or text.casefold().startswith(("calcule ", "resolva ", "quanto é ", "quanto e ")):
            try:
                return solve_and_verify(text).format()
            except MathSolverError:
                pass
        if command == "/video":
            url = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
            if not url:
                return "Uso: /video <URL pública do YouTube, Facebook, Instagram, Vimeo, TikTok ou Dailymotion>."
            return await self.analyze_video(chat_id, url)
        if command in {"/noticias", "/notícia", "/noticias-do-dia"}:
            topic = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
            return await self.main_news(topic)
        normalized_text = " ".join(text.casefold().split())
        if normalized_text in {"principais notícias", "principais notícias do dia", "principais notícias de hoje", "notícias do dia", "notícias de hoje"}:
            return await self.main_news()
        # Ações de workspace são sempre interpretadas antes do Ollama.
        workspace_intent = parse_workspace_intent(chat_id, text)
        if workspace_intent is not None:
            if workspace_intent.action == "calendar_list":
                if workspace_intent.provider == "microsoft":
                    return "A consulta Outlook ainda precisa do conector Microsoft Graph. O Google Calendar pode ser ativado com OAuth desktop."
                try:
                    events = await asyncio.to_thread(GoogleCalendarClient().upcoming, 10)
                except GoogleCalendarNotConfigured as exc:
                    return f"Google Calendar ainda não configurado: {exc}"
                except Exception as exc:
                    log.exception("falha ao listar eventos do Google Calendar")
                    return f"Não consegui consultar o Google Calendar: {type(exc).__name__}."
                if not events:
                    return "ATENA — agenda\n\nNenhum evento futuro encontrado."
                return clip("ATENA — agenda\n\n" + "\n".join(f"• {format_event(event)}" for event in events))
            if workspace_intent.requires_confirmation:
                self.pending_workspace[str(chat_id)] = workspace_intent.to_dict()
                return confirmation_prompt(workspace_intent)
        pending = self.pending_workspace.get(str(chat_id))
        if pending:
            pending_id = str(pending.get("id", ""))
            if is_confirmation(text, pending_id):
                self.pending_workspace.pop(str(chat_id), None)
                intent = WorkspaceIntent(**pending)
                if intent.action == "calendar_create":
                    if intent.provider == "microsoft":
                        return "Ação confirmada, mas o conector Outlook ainda não está configurado. Nenhum evento foi criado."
                    try:
                        event = await asyncio.to_thread(GoogleCalendarClient().create_event, intent.parameters)
                    except GoogleCalendarNotConfigured as exc:
                        return f"Confirmação recebida, mas o Google Calendar ainda não está configurado: {exc}"
                    except Exception as exc:
                        log.exception("falha ao criar evento no Google Calendar")
                        return f"Confirmação recebida, mas não consegui criar o evento: {type(exc).__name__}."
                    return f"ATENA — evento criado\n\n{format_event(event)}\n{event.get('htmlLink', '')}".strip()
                return "Confirmação registrada. O adaptador desta ação ainda precisa ser configurado; nenhuma alteração foi feita."
            if is_cancellation(text, pending_id):
                self.pending_workspace.pop(str(chat_id), None)
                return "Ação cancelada; nenhuma planilha ou evento foi alterado."
        robot_intent = parse_robot_voice_intent(text)
        if robot_intent is not None:
            try:
                robot_command = self.robot_gateway.build_command(robot_intent)
            except ValueError as exc:
                return f"Comando de robô não encaminhado: {exc}."
            if robot_command.requires_confirmation:
                self.pending_robot[str(chat_id)] = robot_command.to_dict()
                return (
                    f"Esta ação no robô exige confirmação: {robot_command.action}.\n"
                    f"Local: {robot_command.location}; robô: {robot_command.robot_id}.\n"
                    f"Responda CONFIRMAR {robot_command.command_id} ou CANCELAR {robot_command.command_id}."
                )
            result = self.robot_gateway.dispatch(robot_command)
            if result.get("status") == "simulated":
                return f"Comando de robô validado em modo simulado; nenhum dispositivo foi alterado. ID: {robot_command.command_id}"
            if not result.get("ok"):
                return f"Comando de robô não executado: {result.get('status', 'erro')}."
            return f"Comando de robô enviado: {robot_command.action}. ID: {robot_command.command_id}"
        pending_robot = self.pending_robot.get(str(chat_id))
        if pending_robot:
            pending_id = str(pending_robot.get("command_id", ""))
            if is_confirmation(text, pending_id):
                self.pending_robot.pop(str(chat_id), None)
                robot_command = RobotCommand(**pending_robot)
                result = self.robot_gateway.dispatch(robot_command, approved=True)
                if result.get("status") == "simulated":
                    return f"Comando confirmado e validado em modo simulado; nenhum dispositivo foi alterado. ID: {pending_id}"
                if not result.get("ok"):
                    return f"Comando confirmado, mas não executado: {result.get('status', 'erro')}."
                return f"Comando confirmado e enviado ao robô: {robot_command.action}. ID: {pending_id}"
            if is_cancellation(text, pending_id):
                self.pending_robot.pop(str(chat_id), None)
                return "Comando do robô cancelado; nenhum dispositivo foi alterado."
        pending_device = self.pending_device.get(str(chat_id))
        if pending_device:
            pending_id = str(pending_device.get("id", ""))
            normalized = " ".join(text.strip().split()).casefold()
            if normalized == f"confirmar {pending_id}".casefold():
                self.pending_device.pop(str(chat_id), None)
                try:
                    await self.tasker.approve(
                        approval_id=pending_id,
                        requester_chat_id=str(chat_id),
                        action=str(pending_device["action"]),
                        target=str(pending_device["target"]),
                        parameters=dict(pending_device.get("parameters", {})),
                        expires_in=120,
                    )
                    result = await self.tasker.dispatch(
                        action=str(pending_device["action"]),
                        target=str(pending_device["target"]),
                        parameters=dict(pending_device.get("parameters", {})),
                        command_id=pending_id,
                        approval_id=pending_id,
                    )
                except TaskerNotConfigured as exc:
                    return f"Confirmação recebida, mas o gateway Android ainda não está configurado: {exc}."
                except TaskerDispatchError as exc:
                    log.exception("falha ao aprovar/despachar ação sensível")
                    return f"Ação não executada: {exc}"
                return f"Ação sensível confirmada e enfileirada no Tasker. ID: {result.get('command_id', pending_id)}"
            if normalized == f"cancelar {pending_id}".casefold():
                self.pending_device.pop(str(chat_id), None)
                return "Ação Android cancelada; nenhum aplicativo ou arquivo foi alterado."

        pending_ha = self.pending_home_assistant.get(str(chat_id))
        if pending_ha:
            pending_id = str(pending_ha.get("id", ""))
            if is_confirmation(text, pending_id):
                self.pending_home_assistant.pop(str(chat_id), None)
                service = "turn_on" if pending_ha["action"] == "ligar" else "turn_off"
                try:
                    result = await asyncio.to_thread(
                        self.home_assistant.call_service,
                        "homeassistant",
                        service,
                        entity_id=pending_ha["entity_id"],
                        approved=True,
                    )
                except HomeAssistantError as exc:
                    return f"Ação confirmada, mas Home Assistant recusou: {exc}"
                return f"Home Assistant: {result.get('status', 'concluído')} — {pending_ha['entity_id']}"
            if is_cancellation(text, pending_id):
                self.pending_home_assistant.pop(str(chat_id), None)
                return "Ação Home Assistant cancelada; nenhum dispositivo foi alterado."

        task_intent = parse_task_intent(text)
        if task_intent is not None:
            if task_intent.requires_confirmation:
                self.pending_device[str(chat_id)] = {
                    "id": task_intent.id,
                    "action": task_intent.action,
                    "target": task_intent.target,
                    "parameters": task_intent.parameters,
                }
                return task_confirmation_prompt(task_intent)
            try:
                result = await self.tasker.dispatch(
                    action=task_intent.action,
                    target=task_intent.target,
                    parameters=task_intent.parameters,
                    command_id=task_intent.id,
                )
            except TaskerNotConfigured as exc:
                return f"Roteador Android ainda não configurado: {exc}."
            except TaskerDispatchError as exc:
                log.exception("falha ao despachar tarefa Android")
                return f"Não consegui entregar a tarefa ao Tasker: {exc}"
            return f"Tarefa Android enfileirada: {task_intent.action}\nID: {result.get('command_id', task_intent.id)}"

        if command == "/voz":
            option = text.split(maxsplit=1)[1].strip().lower() if len(text.split(maxsplit=1)) > 1 else "status"
            if option == "on":
                self.voice_enabled.add(str(chat_id))
                save_voice_settings(self.voice_enabled)
                return "Modo de voz ativado. Envie uma mensagem de voz para conversar com a Atena."
            if option == "off":
                self.voice_enabled.discard(str(chat_id))
                save_voice_settings(self.voice_enabled)
                return "Modo de voz desativado. Continuarei respondendo por texto."
            if option == "status":
                return "Modo de voz: " + ("ativado" if str(chat_id) in self.voice_enabled else "desativado")
            return "Uso: /voz on, /voz off ou /voz status."
        if command in {"/casa", "/home"}:
            parts = text.split()
            action = parts[1].casefold() if len(parts) > 1 else "status"
            entity_id = parts[2] if len(parts) > 2 else None
            if action == "status":
                try:
                    result = await asyncio.to_thread(self.home_assistant.states, entity_id)
                except HomeAssistantError as exc:
                    return f"Home Assistant indisponível: {exc}"
                return clip("Status Home Assistant:\n" + json.dumps(result, ensure_ascii=False, indent=2))
            if action not in {"ligar", "desligar"} or not entity_id:
                return "Uso: /casa status [entidade], /casa ligar <entidade> ou /casa desligar <entidade>."
            approval_id = "ha-" + uuid.uuid4().hex[:12]
            self.pending_home_assistant[str(chat_id)] = {"id": approval_id, "action": action, "entity_id": entity_id}
            return f"Ação física pendente: {action} {entity_id}. Responda CONFIRMAR {approval_id} ou CANCELAR {approval_id}."
        if command in {"/ofertas", "/oferta"}:
            parts = text.split()
            try:
                minimum_discount = float(parts[1]) if len(parts) > 1 else float(os.getenv("ATENA_MIN_DISCOUNT", "50"))
                limit = int(parts[2]) if len(parts) > 2 else 10
            except ValueError:
                return "Uso: /ofertas [desconto mínimo] [quantidade]. Exemplo: /ofertas 60 8"
            if not 0 <= minimum_discount <= 100 or not 1 <= limit <= 20:
                return "Use desconto entre 0 e 100 e quantidade entre 1 e 20."
            return await self.best_store_deals(minimum_discount, limit)
        if command in {"/x", "/noticiasx"}:
            query = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
            if not query:
                return "Uso: /x <tema>. Exemplo: /x últimas notícias sobre inteligência artificial"
            try:
                posts = await asyncio.to_thread(XNewsResearch().search, query, 10)
            except XNotConfigured as exc:
                return f"Pesquisa no X indisponível: {exc}"
            except Exception as exc:
                log.exception("falha na pesquisa do X")
                return f"Não consegui consultar o X agora: {type(exc).__name__}."
            if not posts:
                return "ATENA — X\n\nNenhum post recente encontrado para essa consulta."
            lines = ["ATENA — notícias recentes no X", ""]
            for post in posts[:10]:
                snippet = " ".join(post.text.split())[:240]
                lines.append(f"• {snippet}\n  {post.url}")
            return clip("\n".join(lines))
        if command == "/pesquisar":
            topic = text.split(maxsplit=1)[1].strip() if len(text.split(maxsplit=1)) > 1 else ""
            if not topic:
                return "Uso: /pesquisar <tema>. Exemplo: /pesquisar tecnologia quântica"
            with MemoryStore(MEMORY_DB) as store:
                intent_id = store.enqueue_research(chat_id, topic, f"Pesquisar fontes e evidências sobre {topic}.")
            return f"Pesquisa enfileirada para o próximo ciclo: {topic}\nID: {intent_id}"
        if command == "/fila":
            with MemoryStore(MEMORY_DB) as store:
                intents = [item for item in store.pending_research() if str(item.get("chat_id")) == str(chat_id)]
            if not intents:
                return "Não há pesquisas pendentes para este chat."
            return clip("Pesquisas pendentes:\n" + "\n".join(f"• {item['topic']} ({item['status']})" for item in intents[:10]))
        if command == "/modelo":
            return f"Modelo local ativo: {self.model}\nBackend: Ollama em {OLLAMA_CHAT}"
        if command == "/reset":
            self.sessions.pop(str(chat_id), None)
            save_sessions(self.sessions)
            return "Histórico desta conversa removido."
        if command == "/status":
            memory = ROOT / "atena_evolution" / "llm_learning_memory.json"
            proposal = self.latest_proposal()
            return f"Atena online. Memória: {'disponível' if memory.exists() else 'ausente'}. Última proposta: {'disponível' if proposal else 'ausente'}. Modelo: {self.model}."
        if command == "/aprendizagens":
            proposal = self.latest_proposal()
            if not proposal:
                return "Ainda não encontrei uma proposta de aprendizagem."
            obs = proposal.get("observations", {})
            insights = obs.get("insights", [])
            risks = obs.get("risks", [])
            return clip("Última aprendizagem:\n" + "\n".join(f"• {x}" for x in insights[:5]) + "\n\nRiscos:\n" + "\n".join(f"• {x}" for x in risks[:5]))
        if command == "/capabilities":
            try:
                from core.capability_registry import catalog_dicts
                items = catalog_dicts()
                runnable = sum(bool(item.get("entrypoints")) for item in items)
                return f"Catálogo: {len(items)} capacidades. Pontos executáveis descobertos: {runnable}. A execução de módulos continua sujeita a validação e autorização."
            except Exception as exc:
                return f"Não consegui ler o catálogo: {type(exc).__name__}."
        return None

    async def handle_update(self, update: dict[str, Any]) -> None:
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            await self.handle_feedback_callback(callback)
            return
        message = update.get("message") or update.get("edited_message")
        if not message:
            return
        chat = message.get("chat", {})
        chat_id = int(chat.get("id"))
        if not allowed_chat(chat_id, self.chat_allowlist):
            log.warning("mensagem ignorada de chat não autorizado: %s", chat_id)
            return
        text = str(message.get("text", "")).strip()
        voice = message.get("voice") or message.get("audio")
        telegram_video = message.get("video")
        photos = message.get("photo") or []
        temporary_audio: Path | None = None
        temporary_video: Path | None = None
        temporary_image: Path | None = None
        try:
            if photos and not text:
                largest = max(photos, key=lambda item: int(item.get("file_size", 0)))
                image_bytes, suffix = await self.download_file(str(largest.get("file_id", "")), ".jpg")
                with tempfile.NamedTemporaryFile(prefix="atena-math-", suffix=suffix, delete=False) as handle:
                    handle.write(image_bytes)
                    temporary_image = Path(handle.name)
                caption = str(message.get("caption", "")).strip()
                math_request = any(marker in caption.casefold() for marker in ("matem", "integral", "equação", "equacao", "resolva", "calcule"))
                if math_request:
                    memory = None
                    try:
                        from core.long_term_memory import LongTermMemory
                        memory = await asyncio.to_thread(LongTermMemory)
                    except Exception:
                        memory = None
                    result = await asyncio.to_thread(solve_math_image_vision, temporary_image, memory=memory)
                    answer = format_math_solution(result)
                else:
                    prompt = caption or "Descreva esta imagem com precisão. Leia códigos de erro, textos, diagramas e gráficos. Separe observações visíveis de inferências e indique incertezas."
                    answer = await asyncio.to_thread(analyze_image_with_ocr_fallback, temporary_image, prompt)
                await self.send(chat_id, answer)
                return
            if telegram_video and not text:
                file_id = str(telegram_video.get("file_id", ""))
                if not file_id:
                    raise VideoAnalysisError("vídeo do Telegram sem file_id")
                video_bytes, suffix = await self.download_file(file_id, ".mp4")
                with tempfile.NamedTemporaryFile(prefix="atena-video-", suffix=suffix, delete=False) as handle:
                    handle.write(video_bytes)
                    temporary_video = Path(handle.name)
                answer = await self.analyze_video(chat_id, "vídeo enviado pelo Telegram", local_path=temporary_video)
                await self.send(chat_id, answer)
                return
            if voice and not text:
                if str(chat_id) not in self.voice_enabled:
                    await self.send(chat_id, "Modo de voz desativado. Envie /voz on para ativá-lo.")
                    return
                file_id = str(voice.get("file_id", ""))
                if not file_id:
                    raise AudioGatewayError("mensagem de voz sem file_id")
                audio_bytes, suffix = await self.download_file(file_id)
                transcript = await asyncio.to_thread(self.audio.transcribe_bytes, audio_bytes, suffix)
                text = transcript["text"]
                await self.send(chat_id, f"Transcrição: {clip(text, 900)}")
            if not text:
                return
            video_url = extract_video_url(text)
            if video_url:
                answer = await self.analyze_video(chat_id, video_url)
                await self.send(chat_id, answer)
                return
            if " ".join(text.casefold().split()) in {"/aprendizagens audio", "/aprendizagem audio"}:
                await self.send(chat_id, await self.send_learning_audio(chat_id))
                return
            answer = await self.command(chat_id, text)
            if answer is None:
                if self.needs_current_web(text):
                    try:
                        answer = await self.current_web_answer(chat_id, text)
                    except Exception as exc:
                        log.warning("pesquisa web indisponível: %s", exc)
                        answer = "ATENA — resposta atual\n\nNão consegui confirmar essa informação em fontes públicas agora. Tente novamente em alguns instantes ou use /pesquisar para enfileirar uma investigação no próximo ciclo."
                else:
                    answer = await self.ollama(chat_id, text)
            interaction_id = await asyncio.to_thread(
                record_interaction,
                chat_id=chat_id,
                message_id=message.get("message_id", update.get("update_id", "")),
                prompt=text,
                response=answer,
            )
            await self.send(chat_id, answer, feedback_id=interaction_id)
            if voice and str(chat_id) in self.voice_enabled:
                temporary_audio = await asyncio.to_thread(self.audio.synthesize, answer)
                await self.send_voice(chat_id, temporary_audio)
        except (AudioGatewayError, TelegramError, VisionAnalysisError, MathVisionError) as exc:
            log.warning("falha controlada no áudio/Telegram: %s", exc)
            await self.send(chat_id, f"Não consegui processar o áudio agora: {exc}")
        except Exception as exc:
            log.exception("falha ao processar mensagem")
            await self.send(chat_id, f"Não consegui processar agora: {type(exc).__name__}. Verifique o log da Atena.")
        finally:
            AudioGateway.remove_file(temporary_audio)
            if temporary_video:
                temporary_video.unlink(missing_ok=True)
            if temporary_image:
                temporary_image.unlink(missing_ok=True)

    async def run(self, once: bool = False, poll_timeout: int = 25) -> None:
        # O long polling pode demorar ligeiramente além do timeout declarado pelo Telegram.
        # Um timeout transitório não deve encerrar a ponte e interromper as mensagens.
        client_timeout = aiohttp.ClientTimeout(total=poll_timeout + 60, connect=15, sock_read=poll_timeout + 45)
        async with aiohttp.ClientSession(timeout=client_timeout) as session:
            self.http = session
            await self.api("getMe")
            log.info("ponte Telegram iniciada; modelo=%s", self.model)
            while True:
                try:
                    updates = await self.api("getUpdates", {"offset": self.offset, "timeout": poll_timeout, "allowed_updates": ["message"]})
                except TelegramError as exc:
                    log.warning("polling Telegram temporariamente indisponível; tentando novamente: %s", exc)
                    if once:
                        raise
                    await asyncio.sleep(5)
                    continue
                for update in updates or []:
                    self.offset = max(self.offset, int(update["update_id"]) + 1)
                    await self.handle_update(update)
                if once:
                    return


def main() -> int:
    parser = argparse.ArgumentParser(description="Conversa Telegram com a Atena/Ollama")
    parser.add_argument("--once", action="store_true", help="faz uma consulta de updates e encerra")
    parser.add_argument("--poll-timeout", type=int, default=25)
    parser.add_argument("--model", default=MODEL)
    args = parser.parse_args()
    try:
        token = required_env("ATENA_TELEGRAM_BOT_TOKEN")
        chats = required_env("ATENA_TELEGRAM_CHAT_ID")
        asyncio.run(AtenaTelegramChat(token, chats, args.model).run(args.once, args.poll_timeout))
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        log.error("ponte encerrada: %s", exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
