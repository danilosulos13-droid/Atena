"""Análise controlada de vídeos públicos para a Atena.

O módulo aceita URLs públicas de plataformas conhecidas ou arquivos locais,
extrai metadados e áudio e prepara uma transcrição para uma consideração final.
Não publica, não comenta e não executa ações no conteúdo analisado.
"""
from __future__ import annotations

import json
import html
import os
import re
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests


VIDEO_URL_RE = re.compile(r"https?://[^\s<>]+", re.IGNORECASE)
SUPPORTED_HOSTS = {
    "youtube.com", "www.youtube.com", "youtu.be", "m.youtube.com",
    "facebook.com", "www.facebook.com", "fb.watch", "www.fb.watch",
    "instagram.com", "www.instagram.com", "vimeo.com", "www.vimeo.com",
    "dailymotion.com", "www.dailymotion.com", "tiktok.com", "www.tiktok.com",
}
VIDEO_EXTENSIONS = (".mp4", ".webm", ".mov", ".mkv", ".avi", ".m4v")


class VideoAnalysisError(RuntimeError):
    """Erro controlado de entrada, dependência ou processamento de vídeo."""


@dataclass(frozen=True)
class VideoAnalysisConfig:
    max_duration_seconds: int = int(os.getenv("ATENA_VIDEO_MAX_DURATION_S", "1800"))
    max_bytes: int = int(os.getenv("ATENA_VIDEO_MAX_BYTES", str(500 * 1024 * 1024)))
    workdir: Path = Path(os.getenv("ATENA_VIDEO_WORKDIR", tempfile.gettempdir()))
    whisper_model: str = os.getenv("ATENA_VIDEO_WHISPER_MODEL", "small")
    whisper_device: str = os.getenv("ATENA_VIDEO_WHISPER_DEVICE", "cpu")
    language: str = os.getenv("ATENA_VIDEO_LANGUAGE", "pt")


@dataclass
class VideoAnalysisResult:
    source_url: str = ""
    title: str = ""
    duration_seconds: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    transcript: str = ""
    transcript_language: str = ""
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_url": self.source_url,
            "title": self.title,
            "duration_seconds": self.duration_seconds,
            "width": self.width,
            "height": self.height,
            "fps": self.fps,
            "transcript": self.transcript,
            "transcript_language": self.transcript_language,
            "warnings": list(self.warnings),
        }


def extract_video_url(text: str) -> str | None:
    """Retorna uma URL de vídeo conhecida encontrada no texto."""
    for raw in VIDEO_URL_RE.findall(text or ""):
        url = raw.rstrip(".,!?;:)")
        host = (urlparse(url).hostname or "").casefold()
        if host in SUPPORTED_HOSTS or urlparse(url).path.casefold().endswith(VIDEO_EXTENSIONS):
            return url
    return None


def _run(command: list[str], *, timeout: int = 120) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise VideoAnalysisError(f"dependência ausente: {command[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise VideoAnalysisError("processamento do vídeo excedeu o tempo limite") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()[-500:]
        raise VideoAnalysisError(f"ferramenta de vídeo falhou: {detail}") from exc


def _probe(path: Path) -> dict[str, Any]:
    result = _run(["ffprobe", "-v", "error", "-show_format", "-show_streams", "-of", "json", str(path)])
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise VideoAnalysisError("ffprobe retornou metadados inválidos") from exc


def _metadata(path: Path, source_url: str) -> VideoAnalysisResult:
    payload = _probe(path)
    fmt = payload.get("format", {})
    streams = payload.get("streams", [])
    video = next((item for item in streams if item.get("codec_type") == "video"), {})
    fps = 0.0
    rate = str(video.get("r_frame_rate", "0/1"))
    try:
        numerator, denominator = rate.split("/", 1)
        fps = float(numerator) / float(denominator or 1)
    except (ValueError, ZeroDivisionError):
        pass
    return VideoAnalysisResult(
        source_url=source_url,
        title=str(fmt.get("tags", {}).get("title", "")),
        duration_seconds=float(fmt.get("duration") or 0),
        width=int(video.get("width") or 0),
        height=int(video.get("height") or 0),
        fps=round(fps, 3),
    )


def _validate(path: Path, config: VideoAnalysisConfig) -> None:
    if not path.exists() or not path.is_file():
        raise VideoAnalysisError("arquivo de vídeo não encontrado")
    if path.stat().st_size > config.max_bytes:
        raise VideoAnalysisError(f"vídeo excede o limite de {config.max_bytes // (1024 * 1024)} MB")
    result = _metadata(path, "")
    if result.duration_seconds <= 0:
        raise VideoAnalysisError("não foi possível determinar a duração do vídeo")
    if result.duration_seconds > config.max_duration_seconds:
        raise VideoAnalysisError(f"vídeo excede o limite de {config.max_duration_seconds // 60} minutos")


def _download(url: str, target: Path, config: VideoAnalysisConfig) -> Path:
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise VideoAnalysisError("para URLs do YouTube/Facebook instale setup/requirements-video.txt") from exc
    target.mkdir(parents=True, exist_ok=True)
    options = {
        "outtmpl": str(target / "source.%(ext)s"),
        "format": "bv*[height<=720]+ba/b[height<=720]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "restrictfilenames": True,
        "max_filesize": config.max_bytes,
        "socket_timeout": 30,
        "retries": 2,
        "quiet": True,
        "no_warnings": True,
    }
    try:
        with yt_dlp.YoutubeDL(options) as downloader:
            downloader.download([url])
    except Exception as exc:
        raise VideoAnalysisError(f"não foi possível obter o vídeo público: {type(exc).__name__}") from exc
    candidates = sorted(target.glob("source.*"))
    candidates = [item for item in candidates if item.suffix.casefold() in VIDEO_EXTENSIONS]
    if not candidates:
        raise VideoAnalysisError("o downloader não produziu um arquivo de vídeo")
    return candidates[0]


def _caption_text(payload: str) -> str:
    """Converte VTT/SRT simples em texto, sem baixar o vídeo."""
    lines: list[str] = []
    for raw in payload.splitlines():
        line = html.unescape(raw).strip()
        if not line or line.upper() == "WEBVTT" or line.isdigit():
            continue
        if "-->" in line or line.startswith(("NOTE", "STYLE", "REGION")):
            continue
        line = re.sub(r"<[^>]+>", " ", line)
        line = re.sub(r"\s+", " ", line).strip()
        if line and (not lines or line != lines[-1]):
            lines.append(line)
    return " ".join(lines)[:120_000]


def _subtitle_url(info: dict[str, Any], language: str) -> str:
    collections = [info.get("subtitles") or {}, info.get("automatic_captions") or {}]
    preferred = [language, language.split("-", 1)[0], "pt", "pt-BR", "en"]
    for collection in collections:
        for key in preferred + list(collection):
            entries = collection.get(key) or []
            for entry in entries:
                url = str(entry.get("url", ""))
                if url.startswith(("http://", "https://")):
                    return url
    return ""


def analyze_video_url_remote(url: str, *, config: VideoAnalysisConfig | None = None) -> VideoAnalysisResult:
    """Analisa um vídeo sem baixar seu arquivo, usando metadados e legendas remotas."""
    config = config or VideoAnalysisConfig()
    if not extract_video_url(url):
        raise VideoAnalysisError("URL não reconhecida como vídeo público suportado")
    try:
        import yt_dlp  # type: ignore
    except ImportError as exc:
        raise VideoAnalysisError("para análise remota instale setup/requirements-video.txt") from exc
    try:
        options = {"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}
        with yt_dlp.YoutubeDL(options) as downloader:
            info = downloader.extract_info(url, download=False)
    except Exception as exc:
        raise VideoAnalysisError(f"não foi possível ler os metadados públicos: {type(exc).__name__}") from exc
    duration = float(info.get("duration") or 0)
    if duration and duration > config.max_duration_seconds:
        raise VideoAnalysisError(f"vídeo excede o limite de {config.max_duration_seconds // 60} minutos")
    result = VideoAnalysisResult(
        source_url=url,
        title=str(info.get("title") or ""),
        duration_seconds=duration,
        width=int(info.get("width") or 0),
        height=int(info.get("height") or 0),
        fps=float(info.get("fps") or 0),
        warnings=["arquivo do vídeo não foi baixado; análise baseada em metadados e legendas remotas"],
    )
    caption_url = _subtitle_url(info, config.language)
    if not caption_url:
        result.warnings.append("não há legenda pública disponível; não foi possível transcrever sem baixar o vídeo")
        return result
    try:
        response = requests.get(caption_url, timeout=20, headers={"User-Agent": "Atena-IA remote video analysis/1.0"})
        response.raise_for_status()
        result.transcript = _caption_text(response.text)
        result.transcript_language = config.language
    except requests.RequestException as exc:
        result.warnings.append(f"legenda remota indisponível: {type(exc).__name__}")
    if not result.transcript:
        result.warnings.append("legenda encontrada, mas sem texto utilizável")
    return result


def _extract_audio(video: Path, target: Path) -> Path:
    audio = target / "audio.wav"
    _run(["ffmpeg", "-y", "-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(audio)], timeout=300)
    return audio


def _transcribe(audio: Path, config: VideoAnalysisConfig) -> tuple[str, str]:
    try:
        from faster_whisper import WhisperModel  # type: ignore
    except ImportError as exc:
        raise VideoAnalysisError("transcrição indisponível: instale setup/requirements-video.txt") from exc
    compute_type = os.getenv("ATENA_VIDEO_WHISPER_COMPUTE", "int8" if config.whisper_device == "cpu" else "float16")
    try:
        model = WhisperModel(config.whisper_model, device=config.whisper_device, compute_type=compute_type)
        segments, info = model.transcribe(str(audio), language=config.language, vad_filter=True)
        text = " ".join(segment.text.strip() for segment in segments if segment.text.strip())
        return text[:120_000], str(getattr(info, "language", config.language))
    except Exception as exc:
        raise VideoAnalysisError(f"falha na transcrição: {type(exc).__name__}") from exc


def analyze_video_file(path: str | Path, *, source_url: str = "", config: VideoAnalysisConfig | None = None) -> VideoAnalysisResult:
    config = config or VideoAnalysisConfig()
    video = Path(path)
    _validate(video, config)
    result = _metadata(video, source_url)
    with tempfile.TemporaryDirectory(prefix="atena-video-", dir=str(config.workdir)) as temp:
        audio = _extract_audio(video, Path(temp))
        result.transcript, result.transcript_language = _transcribe(audio, config)
    if not result.transcript:
        result.warnings.append("nenhuma fala foi transcrita; a consideração fica limitada aos metadados")
    return result


def analyze_video_url(url: str, *, config: VideoAnalysisConfig | None = None) -> VideoAnalysisResult:
    config = config or VideoAnalysisConfig()
    if not extract_video_url(url):
        raise VideoAnalysisError("URL não reconhecida como vídeo público suportado")
    config.workdir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="atena-video-download-", dir=str(config.workdir)) as temp:
        video = _download(url, Path(temp), config)
        result = analyze_video_file(video, source_url=url, config=config)
        return result


def build_consideration_prompt(result: VideoAnalysisResult) -> str:
    """Prompt que obriga separar fatos transcritos, alegações e limitações."""
    metadata = json.dumps(result.to_dict(), ensure_ascii=False)
    return (
        "Analise o vídeo abaixo com neutralidade e produza uma consideração final em português. "
        "Não invente fatos que não estejam na transcrição. Separe: resumo, principais alegações, "
        "evidências citadas, pontos não verificáveis, possíveis vieses/limitações e uma consideração final. "
        "Diga explicitamente que a análise foi baseada na transcrição quando não houver análise visual. "
        "Inclua a fonte do vídeo e a duração.\n\nDADOS DO VÍDEO:\n" + metadata
    )


__all__ = [
    "VideoAnalysisConfig", "VideoAnalysisError", "VideoAnalysisResult",
    "analyze_video_file", "analyze_video_url", "analyze_video_url_remote",
    "build_consideration_prompt",
    "extract_video_url",
]
