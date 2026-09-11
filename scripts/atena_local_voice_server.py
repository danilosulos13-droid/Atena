#!/usr/bin/env python3
"""Servidor local de voz da Atena.

Pipeline: microfone -> openWakeWord -> Silero VAD -> faster-whisper -> Ollama -> Piper -> Telegram.
O script mantém modelos carregados, usa uma máquina de estados simples e grava métricas JSONL.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import math
import os
import queue
import statistics
import tempfile
import time
import wave
from collections import defaultdict, deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import requests
import sounddevice as sd
from openwakeword.model import Model as WakeWordModel
from silero_vad import VADIterator, load_silero_vad

from core.audio_gateway import AudioGateway, AudioGatewayError

LOG = logging.getLogger("atena.local_voice")
SAMPLE_RATE = 16_000
FRAME_MS = 80
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


@dataclass(frozen=True)
class Config:
    wake_model: str = os.getenv("ATENA_WAKE_MODEL", "models/wakewords/atena.tflite")
    wake_name: str = os.getenv("ATENA_WAKE_NAME", "atena")
    wake_threshold: float = float(os.getenv("ATENA_WAKE_THRESHOLD", "0.80"))
    vad_threshold: float = float(os.getenv("ATENA_VAD_THRESHOLD", "0.50"))
    listen_timeout: float = float(os.getenv("ATENA_LISTEN_TIMEOUT", "10"))
    max_command_seconds: float = float(os.getenv("ATENA_MAX_COMMAND_SECONDS", "15"))
    silence_ms: int = int(os.getenv("ATENA_VAD_SILENCE_MS", "500"))
    speech_pad_ms: int = int(os.getenv("ATENA_VAD_SPEECH_PAD_MS", "120"))
    ollama_url: str = os.getenv("ATENA_OLLAMA_CHAT_URL", "http://127.0.0.1:11434/api/chat")
    ollama_model: str = os.getenv("ATENA_LOCAL_MODEL", "qwen2.5:3b")
    ollama_timeout: float = float(os.getenv("ATENA_OLLAMA_TIMEOUT", "90"))
    telegram_token: str = os.getenv("ATENA_TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("ATENA_TELEGRAM_CHAT_ID", "")
    metrics_path: Path = Path(os.getenv("ATENA_VOICE_METRICS", "atena_evolution/voice_metrics.jsonl"))
    metrics_window: int = int(os.getenv("ATENA_METRICS_WINDOW", "500"))
    metrics_interval: float = float(os.getenv("ATENA_METRICS_INTERVAL", "60"))


class Metrics:
    def __init__(self, path: Path, window: int = 500) -> None:
        self.path = path
        self.window = window
        self.values: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=window))
        self.lock = asyncio.Lock()

    @staticmethod
    def percentile(values: list[float], percentile: float) -> float | None:
        if not values:
            return None
        ordered = sorted(values)
        index = (len(ordered) - 1) * percentile / 100
        lower = math.floor(index)
        upper = math.ceil(index)
        if lower == upper:
            return round(ordered[lower], 4)
        return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (index - lower), 4)

    async def record(self, event: str, values: dict[str, float], extra: dict[str, Any] | None = None) -> None:
        async with self.lock:
            for key, value in values.items():
                self.values[key].append(float(value))
            record = {
                "ts": time.time(),
                "event": event,
                "values_ms": {key: round(value * 1000, 2) for key, value in values.items()},
                "summary": self.summary_locked(),
            }
            if extra:
                record.update(extra)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self.path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")

    def summary_locked(self) -> dict[str, Any]:
        summary: dict[str, Any] = {}
        for key, values in self.values.items():
            current = list(values)
            summary[key] = {
                "count": len(current),
                "p50_ms": self.percentile(current, 50),
                "p95_ms": self.percentile(current, 95),
                "mean_ms": round(statistics.fmean(current) * 1000, 2) if current else None,
            }
        return summary

    async def summary(self) -> dict[str, Any]:
        async with self.lock:
            return self.summary_locked()


class AtenaLocalVoiceServer:
    def __init__(self, config: Config) -> None:
        self.config = config
        self.frames: queue.Queue[np.ndarray] = queue.Queue(maxsize=100)
        self.audio = AudioGateway()
        self.metrics = Metrics(config.metrics_path, config.metrics_window)
        self.wake = WakeWordModel(wakeword_models=[config.wake_model])
        self.vad_model = load_silero_vad()
        self.vad = VADIterator(
            self.vad_model,
            threshold=config.vad_threshold,
            sampling_rate=SAMPLE_RATE,
            min_silence_duration_ms=config.silence_ms,
            speech_pad_ms=config.speech_pad_ms,
        )
        self.last_metrics_log = time.monotonic()
        self.last_activity = time.monotonic()

    def audio_callback(self, indata: np.ndarray, frames: int, time_info: Any, status: Any) -> None:
        if status:
            LOG.warning("status do dispositivo de áudio: %s", status)
        try:
            self.frames.put_nowait(np.asarray(indata[:, 0], dtype=np.int16).copy())
        except queue.Full:
            LOG.warning("fila de áudio cheia; descartando frame atrasado")

    def reset_vad(self) -> None:
        self.vad.reset_states()

    def pcm_to_wav(self, pcm: np.ndarray) -> bytes:
        with tempfile.NamedTemporaryFile(suffix=".wav") as temp:
            with wave.open(temp.name, "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(SAMPLE_RATE)
                wav.writeframes(pcm.astype(np.int16).tobytes())
            return Path(temp.name).read_bytes()

    def wake_score(self, pcm: np.ndarray) -> float:
        result = self.wake.predict(pcm)
        if self.config.wake_name in result:
            return float(result[self.config.wake_name])
        # Permite descobrir o nome real do output durante a primeira execução.
        if result:
            key, value = max(result.items(), key=lambda item: float(item[1]))
            LOG.debug("wake outputs=%s selecionado=%s", list(result), key)
            return float(value) if key == self.config.wake_name else 0.0
        return 0.0

    def ollama(self, text: str) -> str:
        system = (
            "Você é Atena, uma assistente técnica em português brasileiro. "
            "Responda de forma curta para uso por voz. Separe fatos de hipóteses. "
            "Não invente ações realizadas, fontes ou resultados."
        )
        payload = {
            "model": self.config.ollama_model,
            "keep_alive": "30m",
            "stream": False,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text},
            ],
            "options": {"temperature": 0.2, "num_predict": 300},
        }
        response = requests.post(self.config.ollama_url, json=payload, timeout=self.config.ollama_timeout)
        response.raise_for_status()
        data = response.json()
        return str(data.get("message", {}).get("content", "Não consegui responder agora.")).strip()

    def send_telegram(self, text: str) -> None:
        if not self.config.telegram_token or not self.config.telegram_chat_id:
            LOG.info("Telegram não configurado; resposta local: %s", text)
            return
        url = f"https://api.telegram.org/bot{self.config.telegram_token}/sendMessage"
        response = requests.post(
            url,
            data={"chat_id": self.config.telegram_chat_id, "text": text[:3900]},
            timeout=20,
        )
        response.raise_for_status()

    def send_voice_telegram(self, audio_path: Path) -> None:
        if not self.config.telegram_token or not self.config.telegram_chat_id:
            return
        url = f"https://api.telegram.org/bot{self.config.telegram_token}/sendVoice"
        with audio_path.open("rb") as audio:
            response = requests.post(
                url,
                data={"chat_id": self.config.telegram_chat_id},
                files={"voice": ("atena.wav", audio, "audio/wav")},
                timeout=60,
            )
        response.raise_for_status()

    async def process_speech(self, chunks: list[np.ndarray], wake_at: float) -> None:
        if not chunks:
            return
        started = time.perf_counter()
        pcm = np.concatenate(chunks).astype(np.int16)
        wav_bytes = self.pcm_to_wav(pcm)
        stt_start = time.perf_counter()
        transcript = await asyncio.to_thread(self.audio.transcribe_bytes, wav_bytes, ".wav")
        stt_end = time.perf_counter()
        llm_start = time.perf_counter()
        answer = await asyncio.to_thread(self.ollama, transcript["text"])
        llm_end = time.perf_counter()
        tts_start = time.perf_counter()
        output_path = await asyncio.to_thread(self.audio.synthesize, answer)
        tts_end = time.perf_counter()
        try:
            await asyncio.to_thread(self.send_telegram, answer)
            await asyncio.to_thread(self.send_voice_telegram, output_path)
        finally:
            self.audio.remove_file(output_path)
        sent = time.perf_counter()
        await self.metrics.record(
            "voice_turn",
            {
                "wake_to_stt": stt_start - wake_at,
                "stt": stt_end - stt_start,
                "ollama": llm_end - llm_start,
                "piper": tts_end - tts_start,
                "delivery": sent - tts_end,
                "total": sent - wake_at,
            },
            {
                "transcript_chars": len(transcript["text"]),
                "answer_chars": len(answer),
                "audio_seconds": round(len(pcm) / SAMPLE_RATE, 2),
                "model": self.config.ollama_model,
            },
        )
        LOG.info("resposta enviada; transcript=%r", transcript["text"])

    async def print_metrics_if_due(self) -> None:
        if time.monotonic() - self.last_metrics_log < self.config.metrics_interval:
            return
        self.last_metrics_log = time.monotonic()
        LOG.info("latência p50/p95: %s", json.dumps(await self.metrics.summary(), ensure_ascii=False))

    async def run(self) -> None:
        state = "IDLE"
        started_at = 0.0
        wake_at = 0.0
        chunks: list[np.ndarray] = []
        LOG.info("Atena local iniciada; wake=%s model=%s", self.config.wake_name, self.config.ollama_model)
        with sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            callback=self.audio_callback,
        ):
            while True:
                try:
                    frame = await asyncio.to_thread(self.frames.get)
                    now = time.monotonic()
                    if state == "IDLE":
                        score = self.wake_score(frame)
                        if score >= self.config.wake_threshold:
                            LOG.info("wake word detectado; score=%.3f", score)
                            state = "LISTENING"
                            started_at = now
                            wake_at = time.perf_counter()
                            chunks = []
                            self.reset_vad()
                        await self.print_metrics_if_due()
                        continue

                    event = self.vad(frame, return_seconds=False)
                    if event and "start" in event:
                        state = "CAPTURING"
                        started_at = started_at or now
                    if state == "CAPTURING":
                        chunks.append(frame)
                    if event and "end" in event and chunks:
                        state = "IDLE"
                        await self.process_speech(chunks, wake_at)
                        chunks = []
                        self.reset_vad()
                    elif now - started_at > self.config.listen_timeout and state == "LISTENING":
                        LOG.info("timeout aguardando fala")
                        state = "IDLE"
                        chunks = []
                        self.reset_vad()
                    elif now - started_at > self.config.max_command_seconds:
                        LOG.info("limite de áudio atingido")
                        state = "IDLE"
                        await self.process_speech(chunks, wake_at)
                        chunks = []
                        self.reset_vad()
                    await self.print_metrics_if_due()
                except AudioGatewayError as exc:
                    LOG.warning("falha de áudio: %s", exc)
                    state, chunks = "IDLE", []
                    self.reset_vad()
                except Exception:
                    LOG.exception("erro no loop local; retomando")
                    state, chunks = "IDLE", []
                    self.reset_vad()
                    await asyncio.sleep(1)


def main() -> int:
    parser = argparse.ArgumentParser(description="Servidor local de voz da Atena")
    parser.add_argument("--wake-threshold", type=float, default=None)
    args = parser.parse_args()
    config = Config()
    if args.wake_threshold is not None:
        config = Config(wake_threshold=args.wake_threshold)
    logging.basicConfig(
        level=os.getenv("ATENA_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(AtenaLocalVoiceServer(config).run())
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
