from __future__ import annotations

from core.video_analysis import (
    VideoAnalysisResult,
    _caption_text,
    build_consideration_prompt,
    extract_video_url,
)


def test_extract_supported_platform_url() -> None:
    assert extract_video_url("Analise https://youtu.be/abc123 agora") == "https://youtu.be/abc123"
    assert extract_video_url("https://www.facebook.com/watch/?v=42") == "https://www.facebook.com/watch/?v=42"


def test_reject_unrelated_url() -> None:
    assert extract_video_url("Leia https://example.com/noticia") is None


def test_prompt_requires_final_consideration_and_limits() -> None:
    result = VideoAnalysisResult(
        source_url="https://youtu.be/abc123",
        duration_seconds=42,
        transcript="A reportagem afirma que a medida começa hoje.",
        transcript_language="pt",
    )
    prompt = build_consideration_prompt(result)
    assert "consideração final" in prompt
    assert "Não invente fatos" in prompt
    assert "https://youtu.be/abc123" in prompt
    assert "42" in prompt


def test_caption_text_removes_timestamps_and_duplicate_lines() -> None:
    payload = "WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nOlá mundo\n\n00:00:02.000 --> 00:00:04.000\nOlá mundo\nNotícia confirmada"
    assert _caption_text(payload) == "Olá mundo Notícia confirmada"
