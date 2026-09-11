#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
RUNTIME="${CONTAINER_RUNTIME:-podman}"
IMAGE="${SANDBOX_IMAGE:-atena-sandbox-test:latest}"

if [[ "$RUNTIME" != "podman" ]]; then
  echo "este build rootless exige CONTAINER_RUNTIME=podman" >&2
  exit 2
fi

command -v "$RUNTIME" >/dev/null || {
  echo "runtime não encontrado: $RUNTIME" >&2
  exit 127
}

if [[ "$(podman info --format '{{.Host.Security.Rootless}}' 2>/dev/null || true)" != "true" ]]; then
  echo "Podman precisa estar configurado em modo rootless" >&2
  exit 3
fi

exec "$RUNTIME" build \
  --pull=missing \
  --ignorefile "$ROOT_DIR/deploy/sandbox-test/.dockerignore" \
  --file "$ROOT_DIR/deploy/sandbox-test/Dockerfile" \
  --tag "$IMAGE" \
  "$ROOT_DIR"
