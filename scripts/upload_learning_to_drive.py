#!/usr/bin/env python3
"""Envia artefatos de aprendizagem da Atena para o Google Drive.

O script usa um token OAuth de usuário com refresh_token. Ele não imprime
credenciais, cria as subpastas ausentes dentro da pasta-raiz configurada e
roteia cada artefato para a categoria adequada do cérebro da Atena.

Exemplos:
    python scripts/upload_learning_to_drive.py \
      --report atena_evolution/training/latest_workflow_result.json \
      --state atena_evolution/model_promotion_state.json \
      --audio /tmp/atena-learning.ogg

    python scripts/upload_learning_to_drive.py --dry-run \
      --report atena_evolution/training/latest_workflow_result.json

Variáveis aceitas:
    GOOGLE_DRIVE_TOKEN_FILE   Caminho do token OAuth autorizado.
    GOOGLE_DRIVE_FOLDER_ID    ID da pasta "ATENA — Cérebro".
    ATENA_GOOGLE_DRIVE_SCOPE  Escopo OAuth; padrão: https://www.googleapis.com/auth/drive
    ATENA_DRIVE_DEDUP         "0" desativa deduplicação; padrão: "1".
"""
from __future__ import annotations

import argparse
import hashlib
import json
import mimetypes
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

ROOT_FOLDER_NAME = "ATENA — Cérebro"
DEFAULT_SCOPE = "https://www.googleapis.com/auth/drive"
SUBFOLDERS = (
    "Aprendizagens",
    "Memórias",
    "Pesquisas",
    "Relatórios",
    "Modelos",
    "Áudios",
)


class DriveUploadError(RuntimeError):
    """Erro operacional que pode ser mostrado sem expor credenciais."""


@dataclass(frozen=True)
class UploadItem:
    path: Path
    category: str

    @property
    def name(self) -> str:
        return self.path.name


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(chunk_size), b""):
            digest.update(chunk)
    return digest.hexdigest()


def category_for_path(path: Path) -> str:
    """Determina a subpasta sem depender de nomes absolutos do runner."""
    normalized = "/".join(path.parts).lower()
    name = path.name.lower()
    suffix = path.suffix.lower()
    if suffix in {".ogg", ".mp3", ".wav", ".m4a", ".opus"} or "audio" in normalized:
        return "Áudios"
    if "state" in name or "memory" in normalized or "memori" in normalized or "promotion" in name:
        return "Memórias"
    if "model" in normalized or "adapter" in normalized or name.endswith((".safetensors", ".bin")):
        return "Modelos"
    if "research" in normalized or "pesquis" in normalized or name in {"sources.json", "research.json"}:
        return "Pesquisas"
    if "sft" in name or "experience" in name or "learning" in normalized or "aprendiz" in normalized:
        return "Aprendizagens"
    return "Relatórios"


def collect_items(
    reports: Iterable[Path] = (),
    states: Iterable[Path] = (),
    audio: Iterable[Path] = (),
    research: Iterable[Path] = (),
    learning: Iterable[Path] = (),
    models: Iterable[Path] = (),
) -> list[UploadItem]:
    """Converte argumentos em itens únicos, preservando a ordem de entrada."""
    explicit = (
        [(p, "Relatórios") for p in reports]
        + [(p, "Memórias") for p in states]
        + [(p, "Áudios") for p in audio]
        + [(p, "Pesquisas") for p in research]
        + [(p, "Aprendizagens") for p in learning]
        + [(p, "Modelos") for p in models]
    )
    result: list[UploadItem] = []
    seen: set[Path] = set()
    for raw_path, explicit_category in explicit:
        path = Path(raw_path)
        if path.is_dir():
            for child in sorted(p for p in path.rglob("*") if p.is_file()):
                if child not in seen:
                    result.append(UploadItem(child, explicit_category))
                    seen.add(child)
        elif path.is_file() and path not in seen:
            result.append(UploadItem(path, explicit_category))
            seen.add(path)
        else:
            raise DriveUploadError(f"arquivo não encontrado: {path}")
    return result


def _drive_service(token_file: Path, scope: str) -> Any:
    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise DriveUploadError(
            "Dependências ausentes; instale google-api-python-client e google-auth-oauthlib."
        ) from exc
    if not token_file.is_file():
        raise DriveUploadError(f"arquivo de token OAuth não encontrado: {token_file}")
    try:
        credentials = Credentials.from_authorized_user_file(str(token_file), [scope])
        return build("drive", "v3", credentials=credentials, cache_discovery=False)
    except Exception as exc:  # biblioteca pode variar o tipo de erro OAuth
        raise DriveUploadError(f"não foi possível abrir as credenciais OAuth: {type(exc).__name__}") from exc


def _escape_drive_query(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def find_child_folder(service: Any, parent_id: str, name: str) -> str | None:
    query = (
        "trashed = false and mimeType = 'application/vnd.google-apps.folder' "
        f"and name = '{_escape_drive_query(name)}' and '{_escape_drive_query(parent_id)}' in parents"
    )
    response = service.files().list(
        q=query,
        pageSize=10,
        fields="files(id,name)",
        spaces="drive",
        orderBy="createdTime",
    ).execute()
    files = response.get("files", [])
    return str(files[0]["id"]) if files else None


def ensure_subfolders(service: Any, root_id: str, dry_run: bool = False) -> dict[str, str]:
    folders: dict[str, str] = {}
    for name in SUBFOLDERS:
        existing = find_child_folder(service, root_id, name)
        if existing:
            folders[name] = existing
            continue
        if dry_run:
            folders[name] = f"<would-create:{name}>"
            continue
        created = service.files().create(
            body={
                "name": name,
                "mimeType": "application/vnd.google-apps.folder",
                "parents": [root_id],
            },
            fields="id,name",
        ).execute()
        folders[name] = str(created["id"])
    return folders


def existing_file_hashes(service: Any, folder_id: str, filename: str) -> list[str]:
    """Retorna hashes armazenados no appProperties de arquivos com mesmo nome."""
    query = (
        "trashed = false and name = '"
        + _escape_drive_query(filename)
        + "' and '"
        + _escape_drive_query(folder_id)
        + "' in parents"
    )
    response = service.files().list(
        q=query,
        pageSize=20,
        fields="files(id,name,appProperties)",
        spaces="drive",
    ).execute()
    hashes: list[str] = []
    for item in response.get("files", []):
        value = (item.get("appProperties") or {}).get("atena_sha256")
        if value:
            hashes.append(str(value))
    return hashes


def upload_item(service: Any, item: UploadItem, folder_id: str, dedup: bool = True) -> dict[str, Any]:
    try:
        from googleapiclient.http import MediaFileUpload
    except ImportError as exc:
        raise DriveUploadError("googleapiclient.http não está disponível") from exc

    digest = sha256_file(item.path)
    if dedup and digest in existing_file_hashes(service, folder_id, item.name):
        return {"status": "skipped", "reason": "já existe", "name": item.name, "sha256": digest}

    mime_type = mimetypes.guess_type(item.name)[0] or "application/octet-stream"
    created = service.files().create(
        body={
            "name": item.name,
            "parents": [folder_id],
            "description": f"Atena learning artifact; sha256={digest}",
            "appProperties": {
                "atena_source": "atena-evolution-workflow",
                "atena_category": item.category,
                "atena_sha256": digest,
            },
        },
        media_body=MediaFileUpload(str(item.path), mimetype=mime_type, resumable=True),
        fields="id,name,mimeType,webViewLink,size",
    ).execute()
    return {"status": "uploaded", "name": item.name, "sha256": digest, "file": created}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--token", type=Path, default=Path(os.getenv("GOOGLE_DRIVE_TOKEN_FILE", "")))
    parser.add_argument("--folder-id", default=os.getenv("GOOGLE_DRIVE_FOLDER_ID", ""))
    parser.add_argument("--scope", default=os.getenv("ATENA_GOOGLE_DRIVE_SCOPE", DEFAULT_SCOPE))
    parser.add_argument("--report", action="append", type=Path, default=[])
    parser.add_argument("--state", action="append", type=Path, default=[])
    parser.add_argument("--audio", action="append", type=Path, default=[])
    parser.add_argument("--research", action="append", type=Path, default=[])
    parser.add_argument("--learning", action="append", type=Path, default=[])
    parser.add_argument("--model", action="append", type=Path, default=[])
    parser.add_argument("--dry-run", action="store_true", help="validar e listar o que seria enviado")
    parser.add_argument("--no-dedup", action="store_true", help="não verificar hashes já enviados")
    parser.add_argument("--output", type=Path, help="salvar o resumo JSON neste arquivo")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not args.folder_id:
            raise DriveUploadError("GOOGLE_DRIVE_FOLDER_ID/--folder-id não configurado")
        items = collect_items(args.report, args.state, args.audio, args.research, args.learning, args.model)
        if not items:
            raise DriveUploadError("nenhum artefato foi informado")
        if args.dry_run:
            result = {
                "status": "dry-run",
                "root_folder_id": args.folder_id,
                "items": [
                    {"path": str(i.path), "name": i.name, "category": i.category, "sha256": sha256_file(i.path)}
                    for i in items
                ],
            }
        else:
            if not args.token:
                raise DriveUploadError("GOOGLE_DRIVE_TOKEN_FILE/--token não configurado")
            service = _drive_service(args.token, args.scope)
            folders = ensure_subfolders(service, args.folder_id)
            uploads = [
                upload_item(service, item, folders[item.category], dedup=not args.no_dedup)
                for item in items
            ]
            result = {"status": "ok", "root_folder_id": args.folder_id, "folders": folders, "uploads": uploads}
        serialized = json.dumps(result, ensure_ascii=False, indent=2)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(serialized + "\n", encoding="utf-8")
        print(serialized)
        return 0
    except DriveUploadError as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"ERRO inesperado: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
