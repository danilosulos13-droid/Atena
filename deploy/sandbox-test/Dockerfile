FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONNOUSERSITE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 65532 sandbox \
    && useradd --uid 65532 --gid 65532 --create-home --shell /usr/sbin/nologin sandbox

COPY deploy/sandbox-test/requirements.txt /tmp/requirements.txt
RUN python -m pip install --no-cache-dir -r /tmp/requirements.txt

WORKDIR /workspace
USER 65532:65532

# O executor fornece o comando explicitamente; não usar entrypoint que duplique argumentos.
