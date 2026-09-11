#!/usr/bin/env python3
"""Diagnóstico seguro e somente leitura da conexão durante jogos.

O módulo mede latência, perda de pacotes, resolução DNS e rota local.
Ele não altera firewall, DNS, roteador, VPN, Tasker ou configurações do Android.
Atena pode usar o JSON gerado para sugerir ações reversíveis e pedir confirmação.
"""
from __future__ import annotations

import argparse
import json
import platform
import re
import socket
import subprocess
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class PingResult:
    host: str
    transmitted: int
    received: int
    packet_loss_percent: float | None
    min_ms: float | None
    avg_ms: float | None
    max_ms: float | None
    error: str | None = None


def _run(command: list[str], timeout: int = 15) -> tuple[int, str, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
        return completed.returncode, completed.stdout, completed.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 124, "", str(exc)


def ping(host: str, count: int = 5) -> PingResult:
    count = max(1, min(count, 20))
    command = ["ping", "-c", str(count), "-W", "3", host]
    code, stdout, stderr = _run(command)
    combined = f"{stdout}\n{stderr}"
    loss_match = re.search(r"([0-9]+(?:\.[0-9]+)?)%\s*packet loss", combined)
    rtt_match = re.search(r"=\s*([0-9.]+)\/([0-9.]+)\/([0-9.]+)\/", combined)
    transmitted = count
    received = round(count * (1 - float(loss_match.group(1)) / 100)) if loss_match else 0
    return PingResult(
        host=host,
        transmitted=transmitted,
        received=received,
        packet_loss_percent=float(loss_match.group(1)) if loss_match else None,
        min_ms=float(rtt_match.group(1)) if rtt_match else None,
        avg_ms=float(rtt_match.group(2)) if rtt_match else None,
        max_ms=float(rtt_match.group(3)) if rtt_match else None,
        error=None if code == 0 else (stderr.strip() or "ping_failed"),
    )


def resolve_dns(host: str) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        addresses = sorted({entry[4][0] for entry in socket.getaddrinfo(host, None)})
        return {"host": host, "addresses": addresses, "elapsed_ms": round((time.perf_counter() - started) * 1000, 1), "error": None}
    except socket.gaierror as exc:
        return {"host": host, "addresses": [], "elapsed_ms": round((time.perf_counter() - started) * 1000, 1), "error": str(exc)}


def local_route() -> dict[str, Any]:
    code, stdout, stderr = _run(["ip", "route", "get", "1.1.1.1"])
    return {"available": code == 0, "route": stdout.strip(), "error": None if code == 0 else (stderr.strip() or "route_failed")}


def recommendations(ping_result: PingResult, dns: dict[str, Any], route: dict[str, Any]) -> list[str]:
    suggestions: list[str] = []
    if ping_result.error:
        suggestions.append("Não foi possível executar o teste ICMP neste ambiente; rode o diagnóstico no dispositivo que está jogando.")
    elif ping_result.packet_loss_percent is None or ping_result.packet_loss_percent > 2:
        suggestions.append("Há perda de pacotes; prefira cabo ou Wi-Fi 5 GHz próximo ao roteador e teste o roteador/ISP.")
    if ping_result.avg_ms is not None and ping_result.avg_ms > 80:
        suggestions.append("A latência média está alta; interrompa sincronizações em segundo plano e habilite QoS para o dispositivo no roteador.")
    if ping_result.max_ms is not None and ping_result.avg_ms is not None and ping_result.max_ms - ping_result.avg_ms > 40:
        suggestions.append("Há variação de latência (jitter); reduza tráfego concorrente e teste outro canal Wi-Fi.")
    if dns.get("error"):
        suggestions.append("A resolução DNS falhou; teste um DNS confiável no roteador somente após confirmação explícita.")
    if not route.get("available"):
        suggestions.append("Não foi possível identificar a rota local; execute o diagnóstico no dispositivo que está jogando.")
    if not suggestions:
        suggestions.append("A conexão parece estável neste teste; não há ajuste automático recomendado.")
    return suggestions


def diagnose(host: str = "1.1.1.1", dns_host: str = "www.google.com", count: int = 5) -> dict[str, Any]:
    ping_result = ping(host, count)
    dns = resolve_dns(dns_host)
    route = local_route()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": platform.platform(),
        "safe_mode": True,
        "target": host,
        "ping": asdict(ping_result),
        "dns": dns,
        "route": route,
        "recommendations": recommendations(ping_result, dns, route),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Diagnóstico somente leitura para conexão durante jogos")
    parser.add_argument("--host", default="1.1.1.1")
    parser.add_argument("--dns-host", default="www.google.com")
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--output", type=str)
    args = parser.parse_args()
    report = diagnose(args.host, args.dns_host, args.count)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with open(args.output, "w", encoding="utf-8") as handle:
            handle.write(rendered)
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
