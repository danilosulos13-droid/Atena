"""Gateway local de áudio para a Atena.

STT usa faster-whisper quando instalado. TTS usa o executável Piper,
configurado por variáveis de ambiente. O módulo não baixa modelos nem
executa comandos recebidos do usuário.
"""
from __future__ import annotations

import io
import logging
import os
import shutil
import subprocess
import tempfile
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

log = logging.getLogger("atena.audio")


class AudioGatewayError(RuntimeError):
    """Erro controlado de transcrição ou síntese."""


@dataclass(frozen=True)
class AudioConfig:
    whisper_model: str = os.getenv("ATENA_WHISPER_MODEL", "small")
    whisper_device: str = os.getenv("ATENA_WHISPER_DEVICE", "cpu")
    whisper_compute_type: str = os.getenv("ATENA_WHISPER_COMPUTE_TYPE", "int8")
    whisper_language: str = os.getenv("ATENA_WHISPER_LANGUAGE", "pt")
    piper_bin: str = os.getenv("ATENA_PIPER_BIN", "piper")
    piper_model: str = os.getenv("ATENA_PIPER_MODEL", "")
    piper_config: str = os.getenv("ATENA_PIPER_CONFIG", "")
    max_audio_bytes: int = int(os.getenv("ATENA_MAX_AUDIO_BYTES", str(10 * 1024 * 1024)))
    max_audio_seconds: int = int(os.getenv("ATENA_MAX_AUDIO_SECONDS", "180"))
    timeout_seconds: int = int(os.getenv("ATENA_AUDIO_TIMEOUT", "120"))


class AudioGateway:
    def __init__(self, config: AudioConfig | None = None) -> None:
        self.config = config or AudioConfig()
        self._whisper: Any = None

    def _load_whisper(self) -> Any:
        if self._whisper is None:
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise AudioGatewayError(
                    "faster-whisper não está instalado; use pip install faster-whisper"
                ) from exc
            try:
                self._whisper = WhisperModel(
                    self.config.whisper_model,
                    device=self.config.whisper_device,
                    compute_type=self.config.whisper_compute_type,
                )
            except Exception as exc:
                raise AudioGatewayError(f"não foi possível carregar Whisper: {type(exc).__name__}") from exc
        return self._whisper

    def _check_size(self, data: bytes) -> None:
        if not data:
            raise AudioGatewayError("arquivo de áudio vazio")
        if len(data) > self.config.max_audio_bytes:
            raise AudioGatewayError("arquivo de áudio excede o limite permitido")

    def transcribe_bytes(self, data: bytes, suffix: str = ".ogg") -> dict[str, Any]:
        """Transcreve bytes de áudio em processo bloqueante, para usar via to_thread."""
        self._check_size(data)
        model = self._load_whisper()
        with tempfile.TemporaryDirectory(prefix="atena-stt-") as tmp:
            source = Path(tmp) / f"input{suffix if suffix.startswith('.') else '.' + suffix}"
            source.write_bytes(data)
            try:
                segments, info = model.transcribe(
                    str(source),
                    language=self.config.whisper_language or None,
                    vad_filter=True,
                    condition_on_previous_text=False,
                )
                parts: list[str] = []
                duration = 0.0
                for segment in segments:
                    parts.append(str(segment.text).strip())
                    duration = max(duration, float(getattr(segment, "end", 0.0) or 0.0))
                    if duration > self.config.max_audio_seconds:
                        raise AudioGatewayError("áudio excede a duração máxima permitida")
                text = " ".join(part for part in parts if part).strip()
                if not text:
                    raise AudioGatewayError("não foi possível reconhecer fala")
                return {
                    "text": text,
                    "language": getattr(info, "language", self.config.whisper_language),
                    "duration_seconds": round(duration, 2),
                    "model": self.config.whisper_model,
                }
            except AudioGatewayError:
                raise
            except Exception as exc:
                raise AudioGatewayError(f"falha na transcrição: {type(exc).__name__}") from exc

    def synthesize(self, text: str, output_path: str | Path | None = None) -> Path:
        """Gera WAV com Piper. O texto nunca é interpretado como shell."""
        clean = " ".join(str(text).split()).strip()
        if not clean:
            raise AudioGatewayError("texto vazio para síntese")
        if len(clean) > 3500:
            clean = clean[:3499] + "…"
        if not self.config.piper_model:
            raise AudioGatewayError("ATENA_PIPER_MODEL não está configurado")
        if shutil.which(self.config.piper_bin) is None and not Path(self.config.piper_bin).exists():
            raise AudioGatewayError("executável Piper não encontrado")
        target = Path(output_path) if output_path else Path(tempfile.mktemp(prefix="atena-tts-", suffix=".wav"))
        target.parent.mkdir(parents=True, exist_ok=True)
        command = [self.config.piper_bin, "--model", self.config.piper_model, "--output_file", str(target)]
        if self.config.piper_config:
            command.extend(["--config", self.config.piper_config])
        try:
            completed = subprocess.run(
                command,
                input=clean.encode("utf-8"),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.config.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AudioGatewayError("Piper excedeu o tempo limite") from exc
        except OSError as exc:
            raise AudioGatewayError("não foi possível iniciar o Piper") from exc
        if completed.returncode != 0 or not target.exists() or target.stat().st_size == 0:
            log.warning("Piper falhou: %s", completed.stderr.decode("utf-8", "replace")[-500:])
            raise AudioGatewayError("Piper não gerou áudio")
        return target

    @staticmethod
    def remove_file(path: str | Path | None) -> None:
        if path:
            try:
                Path(path).unlink(missing_ok=True)
            except OSError:
                log.warning("não foi possível remover áudio temporário", exc_info=True)
