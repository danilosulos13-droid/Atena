import importlib.util
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]


def load_module(path: str, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_audio_gateway_rejects_empty_audio():
    audio = load_module(str(REPO_ROOT / "core" / "audio_gateway.py"), "audio_gateway_test")
    gateway = audio.AudioGateway(audio.AudioConfig(max_audio_bytes=10))
    try:
        gateway.transcribe_bytes(b"")
    except audio.AudioGatewayError as exc:
        assert "vazio" in str(exc)
    else:
        raise AssertionError("áudio vazio deveria ser rejeitado")


def test_audio_gateway_rejects_oversized_audio():
    audio = load_module(str(REPO_ROOT / "core" / "audio_gateway.py"), "audio_gateway_size_test")
    gateway = audio.AudioGateway(audio.AudioConfig(max_audio_bytes=3))
    try:
        gateway.transcribe_bytes(b"1234")
    except audio.AudioGatewayError as exc:
        assert "limite" in str(exc)
    else:
        raise AssertionError("áudio grande deveria ser rejeitado")


def test_voice_command_is_documented_and_persistent(tmp_path, monkeypatch):
    chat = load_module(str(REPO_ROOT / "scripts" / "atena_telegram_chat.py"), "telegram_voice_test")
    monkeypatch.setattr(chat, "VOICE_SETTINGS_PATH", tmp_path / "voice.json")
    instance = chat.AtenaTelegramChat("token", "123")
    import asyncio
    assert "ativado" in asyncio.run(instance.command(123, "/voz on"))
    assert "ativado" in asyncio.run(instance.command(123, "/voz status"))
    assert json.loads((tmp_path / "voice.json").read_text()) == ["123"]
    assert "desativado" in asyncio.run(instance.command(123, "/voz off"))
