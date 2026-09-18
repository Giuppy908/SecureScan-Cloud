#!/usr/bin/env python3
"""Esegue gli esperimenti HA riproducibili di SecureScan Cloud.

Questo file non implementa una pagina dell'interfaccia. Viene usato quando si
vuole misurare comportamento del gateway e delle due repliche API in scenari
come baseline, singola replica, failover e recovery.

I risultati prodotti qui non sostituiscono i dati applicativi mostrati in
Dashboard o Cronologia: servono invece a dimostrare proprieta` non funzionali
come load balancing, fault tolerance, latenza, throughput ed error rate.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


ROOT_DIR = Path(__file__).resolve().parents[2]
SCENARIOS_DIR = ROOT_DIR / "experiments" / "scenarios"
RESULTS_DIR = ROOT_DIR / "experiments" / "results"
DEFAULT_COMPOSE_FILE = ROOT_DIR / "infrastructure" / "compose" / "compose.yaml"
DEFAULT_ENV_FILE = ROOT_DIR / ".env"
DEFAULT_GATEWAY_URL = "http://localhost:8000"
DEFAULT_PROMETHEUS_URL = "http://127.0.0.1:9090"
DEFAULT_KONG_ADMIN_URL = "http://127.0.0.1:8001"
DEFAULT_UPSTREAM_NAME = "analysis-api-upstream"
DEFAULT_KONG_SERVICE_NAME = "analysis-api-service"
REQUIRED_SERVICES = [
    "kong",
    "prometheus",
    "analysis-api-1",
    "analysis-api-2",
    "analysis-worker",
]
PROM_TARGETS = {
    "analysis-api-1": 'up{job="analysis-api",instance="analysis-api-1:8000"}',
    "analysis-api-2": 'up{job="analysis-api",instance="analysis-api-2:8000"}',
}
SERVICE_TARGETS = {
    "analysis-api-1": "analysis-api-1:8000",
    "analysis-api-2": "analysis-api-2:8000",
}


@dataclass
class ScenarioAction:
    """Azione temporizzata da applicare durante uno scenario.

    Esempi reali nel repository:
    - fermare una replica API durante il carico;
    - riavviare una replica mentre le richieste stanno continuando.
    """
    type: str
    service: str
    offset_seconds: float


@dataclass
class ScenarioConfig:
    """Configurazione completa di uno scenario di benchmark.

    Ogni file JSON sotto `experiments/scenarios/` viene convertito in questa
    struttura prima dell'esecuzione. In questo modo gli esperimenti restano
    dichiarativi: i parametri sono nei JSON, mentre la logica di esecuzione
    resta concentrata nello script Python.
    """
    name: str
    description: str
    endpoint_path: str
    duration_seconds: float
    concurrency: int
    timeout_seconds: float
    expected_active_replicas: int
    initial_service_states: dict[str, str]
    actions: list[ScenarioAction]


@dataclass
class RequestSample:
    """Campione di una singola richiesta HTTP inviata al gateway.

    Questi record permettono di ricostruire cosa e` successo durante il test:
    latenza, esito, replica backend raggiunta e latenze osservate da Kong.
    """
    timestamp: str
    elapsed_seconds: float
    latency_ms: float
    status_code: int | None
    backend_instance: str | None
    success: bool
    error: str | None
    error_category: str | None
    kong_proxy_latency_ms: float | None
    kong_upstream_latency_ms: float | None


@dataclass
class EventRecord:
    """Evento strutturato emesso durante fault o recovery.

    Gli eventi completano i campioni HTTP: aiutano a capire quando e` partito
    un fault, quando Kong lo ha rilevato e quando il routing si e` riallineato.
    """
    timestamp: str
    elapsed_seconds: float
    event: str
    details: dict[str, Any]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_timestamp() -> str:
    return utc_now().isoformat()


def load_scenario(path: Path, duration_scale: float) -> ScenarioConfig:
    """Legge uno scenario JSON e applica l'eventuale scala temporale.

    `duration_scale` consente smoke test piu` rapidi senza riscrivere i file
    scenario originali, che rimangono il riferimento metodologico principale.
    """
    payload = json.loads(path.read_text())
    actions = [
        ScenarioAction(
            type=item["type"],
            service=item["service"],
            offset_seconds=float(item["offset_seconds"]) * duration_scale,
        )
        for item in payload.get("actions", [])
    ]
    return ScenarioConfig(
        name=payload["name"],
        description=payload["description"],
        endpoint_path=payload["endpoint_path"],
        duration_seconds=float(payload["duration_seconds"]) * duration_scale,
        concurrency=int(payload["concurrency"]),
        timeout_seconds=float(payload["timeout_seconds"]),
        expected_active_replicas=int(payload["expected_active_replicas"]),
        initial_service_states=dict(payload["initial_service_states"]),
        actions=actions,
    )


def percent(values: list[float], percentile: float) -> float:
    """Calcola un percentile con interpolazione lineare semplice."""
    if not values:
        return 0.0
    ordered = sorted(values)
    index = (len(ordered) - 1) * percentile
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[int(index)]
    fraction = index - lower
    return ordered[lower] * (1 - fraction) + ordered[upper] * fraction


class ComposeController:
    """Adattatore minimo verso lo stack Docker Compose locale.

    Gli esperimenti non manipolano direttamente container o processi Unix:
    usano sempre il Compose del progetto, cosi` i benchmark restano allineati
    alla demo locale reale di SecureScan Cloud.
    """

    def __init__(self, compose_file: Path, env_file: Path) -> None:
        self.compose_file = compose_file
        self.env_file = env_file

    def run(self, *args: str) -> subprocess.CompletedProcess[str]:
        command = [
            "docker",
            "compose",
            "--env-file",
            str(self.env_file),
            "-f",
            str(self.compose_file),
            *args,
        ]
        return subprocess.run(command, cwd=ROOT_DIR, text=True, capture_output=True)

    def run_checked(self, *args: str) -> subprocess.CompletedProcess[str]:
        result = self.run(*args)
        if result.returncode != 0:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "docker compose failed")
        return result

    def running_services(self) -> set[str]:
        result = self.run_checked("ps", "--status", "running", "--services")
        return {line.strip() for line in result.stdout.splitlines() if line.strip()}

    def ensure_stack_active(self) -> None:
        """Verifica che i servizi minimi richiesti dagli esperimenti siano attivi."""
        running = self.running_services()
        missing = [service for service in REQUIRED_SERVICES if service not in running]
        if missing:
            raise RuntimeError("Required services are not running: " + ", ".join(missing))

    def set_service_state(self, service: str, desired_state: str) -> float:
        """Porta una replica nello stato richiesto e restituisce il tempo del comando."""
        started = time.monotonic()
        if desired_state == "running":
            self.run_checked("up", "-d", service)
            return time.monotonic() - started
        if desired_state == "stopped":
            self.run_checked("stop", "-t", "0", service)
            return time.monotonic() - started
        raise ValueError(f"Unsupported desired state: {desired_state}")

    def restore_default_state(self) -> None:
        """Riporta lo scenario finale alla baseline con entrambe le API attive."""
        self.set_service_state("analysis-api-1", "running")
        self.set_service_state("analysis-api-2", "running")


class KongAdminClient:
    """Lettura diretta della topologia Kong durante i benchmark.

    Serve a misurare il comportamento reale del gateway: non basta sapere che
    una replica e` stata fermata, bisogna anche osservare quando Kong la marca
    come unhealthy e quando ricomincia a instradare traffico dopo il recovery.
    """

    def __init__(self, base_url: str, upstream_name: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.upstream_name = upstream_name

    def _get_json(self, path: str) -> dict[str, Any]:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_upstream(self) -> dict[str, Any]:
        return self._get_json(f"/upstreams/{urllib.parse.quote(self.upstream_name, safe='')}")

    def get_service(self, service_name: str) -> dict[str, Any]:
        return self._get_json(f"/services/{urllib.parse.quote(service_name, safe='')}")

    def get_targets(self) -> list[dict[str, Any]]:
        payload = self._get_json(f"/upstreams/{urllib.parse.quote(self.upstream_name, safe='')}/targets")
        return payload.get("data", [])

    def get_upstream_health(self) -> dict[str, str]:
        payload = self._get_json(f"/upstreams/{urllib.parse.quote(self.upstream_name, safe='')}/health")
        health_map: dict[str, str] = {}
        for item in payload.get("data", []):
            target = item.get("target")
            health = item.get("health")
            if isinstance(target, str) and isinstance(health, str):
                health_map[target] = health
        return health_map

    def wait_for_target_health(
        self,
        target: str,
        expected_health: str,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 0.05,
    ) -> tuple[str, float]:
        """Poll Kong until one upstream target converges to the expected health."""
        started = time.monotonic()
        while time.monotonic() - started <= timeout_seconds:
            current = self.get_upstream_health().get(target)
            if current == expected_health:
                return current, time.monotonic() - started
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Kong target did not reach {expected_health}: {target}")


class PrometheusClient:
    """Client minimo per interrogare Prometheus durante gli esperimenti.

    Le query qui servono solo come evidenza di supporto per i benchmark HA:
    verificano, per esempio, quando una replica passa da `up=1` a `up=0`.
    """
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def instant_query(self, expression: str) -> list[dict[str, Any]]:
        query = urllib.parse.urlencode({"query": expression})
        url = f"{self.base_url}/api/v1/query?{query}"
        with urllib.request.urlopen(url, timeout=5) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {payload}")
        return payload["data"]["result"]

    def scalar(self, expression: str) -> float:
        result = self.instant_query(expression)
        if not result:
            return 0.0
        return float(result[0]["value"][1])

    def wait_for_value(
        self,
        expression: str,
        expected: float,
        timeout_seconds: float = 30.0,
        poll_interval_seconds: float = 1.0,
    ) -> tuple[float, float]:
        started = time.monotonic()
        while time.monotonic() - started <= timeout_seconds:
            value = self.scalar(expression)
            if value == expected:
                return value, time.monotonic() - started
            time.sleep(poll_interval_seconds)
        raise TimeoutError(f"Prometheus expression did not reach {expected}: {expression}")


def perform_request(url: str, timeout_seconds: float, started_at_monotonic: float) -> RequestSample:
    """Esegue una richiesta verso il gateway e ne registra l'esito dettagliato.

    Le intestazioni restituite da Kong permettono di capire quale replica ha
    servito la richiesta e quali latenze sono state osservate dal gateway.
    """
    request_started = time.monotonic()
    timestamp = iso_timestamp()
    backend_instance: str | None = None
    status_code: int | None = None
    kong_proxy_latency_ms: float | None = None
    kong_upstream_latency_ms: float | None = None

    try:
        request = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            status_code = response.status
            backend_instance = response.headers.get("X-Backend-Instance")
            proxy_latency_header = response.headers.get("X-Kong-Proxy-Latency")
            upstream_latency_header = response.headers.get("X-Kong-Upstream-Latency")
            kong_proxy_latency_ms = float(proxy_latency_header) if proxy_latency_header is not None else None
            kong_upstream_latency_ms = float(upstream_latency_header) if upstream_latency_header is not None else None
            response.read()
            success = 200 <= status_code < 400
            error_message = None
            error_category = None
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        backend_instance = exc.headers.get("X-Backend-Instance")
        proxy_latency_header = exc.headers.get("X-Kong-Proxy-Latency")
        upstream_latency_header = exc.headers.get("X-Kong-Upstream-Latency")
        kong_proxy_latency_ms = float(proxy_latency_header) if proxy_latency_header is not None else None
        kong_upstream_latency_ms = float(upstream_latency_header) if upstream_latency_header is not None else None
        success = False
        error_message = str(exc)
        error_category = "http_5xx" if 500 <= exc.code <= 599 else "http_error"
    except Exception as exc:  # noqa: BLE001
        success = False
        error_message = str(exc)
        lowered = error_message.lower()
        if isinstance(exc, TimeoutError) or "timed out" in lowered or "timeout" in lowered:
            error_category = "timeout"
        else:
            error_category = "client_error"

    latency_ms = (time.monotonic() - request_started) * 1000
    return RequestSample(
        timestamp=timestamp,
        elapsed_seconds=time.monotonic() - started_at_monotonic,
        latency_ms=latency_ms,
        status_code=status_code,
        backend_instance=backend_instance,
        success=success,
        error=error_message,
        error_category=error_category,
        kong_proxy_latency_ms=kong_proxy_latency_ms,
        kong_upstream_latency_ms=kong_upstream_latency_ms,
    )


def write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True) + "\n")


def write_summary_csv(path: Path, summaries: list[dict[str, Any]]) -> None:
    """Esporta una vista tabellare compatta dei risultati finali."""
    fieldnames = [
        "scenario",
        "started_at",
        "finished_at",
        "duration_seconds",
        "concurrency",
        "expected_active_replicas",
        "action_type",
        "action_service",
        "kong_transition_seconds",
        "prometheus_transition_seconds",
        "routing_transition_seconds",
        "total_requests",
        "successful_requests",
        "failed_requests",
        "http_2xx_requests",
        "http_5xx_requests",
        "client_error_requests",
        "timeout_requests",
        "error_rate",
        "throughput_rps",
        "latency_min_ms",
        "latency_avg_ms",
        "latency_p50_ms",
        "latency_p95_ms",
        "latency_p99_ms",
        "latency_max_ms",
        "max_latency_ms",
        "backend_distribution",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for summary in summaries:
            row = {name: summary.get(name, "") for name in fieldnames}
            row["backend_distribution"] = json.dumps(summary.get("backend_distribution", {}), sort_keys=True)
            writer.writerow(row)


def _svg_canvas(width: int = 960, height: int = 540) -> tuple[int, int]:
    return width, height


def write_bar_chart_svg(path: Path, *, title: str, x_label: str, y_label: str, values: dict[str, float], color: str) -> None:
    """Genera un grafico SVG semplice senza dipendenze esterne.

    La suite usa solo standard library Python: i grafici vengono quindi creati
    manualmente in SVG per restare portabili e riproducibili.
    """
    width, height = _svg_canvas()
    margin_left = 80
    margin_bottom = 80
    margin_top = 60
    margin_right = 40
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    max_value = max(values.values(), default=1.0)
    if max_value <= 0:
        max_value = 1.0
    bar_width = chart_width / max(len(values), 1) * 0.6
    gap = chart_width / max(len(values), 1) * 0.4
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0c1220"/>',
        f'<text x="{width/2}" y="30" fill="#f4f7fb" text-anchor="middle" font-size="24" font-family="Arial">{title}</text>',
        f'<text x="{width/2}" y="{height-20}" fill="#c0cad9" text-anchor="middle" font-size="14" font-family="Arial">{x_label}</text>',
        f'<text x="20" y="{height/2}" fill="#c0cad9" text-anchor="middle" font-size="14" font-family="Arial" transform="rotate(-90 20 {height/2})">{y_label}</text>',
    ]
    for index, (name, value) in enumerate(values.items()):
        x = margin_left + index * (bar_width + gap) + gap / 2
        bar_height = chart_height * (value / max_value)
        y = margin_top + (chart_height - bar_height)
        parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" fill="{color}" rx="8"/>')
        parts.append(f'<text x="{x + bar_width/2:.1f}" y="{y - 8:.1f}" fill="#f4f7fb" text-anchor="middle" font-size="12" font-family="Arial">{value:.2f}</text>')
        parts.append(f'<text x="{x + bar_width/2:.1f}" y="{height - 45}" fill="#c0cad9" text-anchor="middle" font-size="12" font-family="Arial">{name}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts))


def write_grouped_latency_svg(path: Path, scenario_summaries: list[dict[str, Any]]) -> None:
    width, height = _svg_canvas(1100, 560)
    margin_left = 80
    margin_bottom = 100
    margin_top = 60
    margin_right = 40
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    metrics = ["latency_p95_ms", "latency_p99_ms"]
    max_value = max((summary[metric] for summary in scenario_summaries for metric in metrics), default=1.0)
    if max_value <= 0:
        max_value = 1.0
    group_width = chart_width / max(len(scenario_summaries), 1)
    bar_width = group_width / (len(metrics) + 1)
    colors = {"latency_p95_ms": "#06b6d4", "latency_p99_ms": "#f59e0b"}
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0c1220"/>',
        '<text x="550" y="30" fill="#f4f7fb" text-anchor="middle" font-size="24" font-family="Arial">P95 e P99 per scenario</text>',
    ]
    for group_index, summary in enumerate(scenario_summaries):
        group_x = margin_left + group_index * group_width + bar_width * 0.5
        for metric_index, metric in enumerate(metrics):
            value = summary[metric]
            x = group_x + metric_index * bar_width
            bar_height = chart_height * (value / max_value)
            y = margin_top + (chart_height - bar_height)
            parts.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width * 0.8:.1f}" height="{bar_height:.1f}" fill="{colors[metric]}" rx="6"/>')
            parts.append(f'<text x="{x + bar_width*0.4:.1f}" y="{y - 6:.1f}" fill="#f4f7fb" text-anchor="middle" font-size="11" font-family="Arial">{value:.2f}</text>')
        parts.append(f'<text x="{group_x + bar_width/2:.1f}" y="{height - 55}" fill="#c0cad9" text-anchor="middle" font-size="12" font-family="Arial">{summary["scenario"]}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts))


def write_backend_distribution_svg(path: Path, scenario_summaries: list[dict[str, Any]]) -> None:
    width, height = _svg_canvas(1100, 560)
    margin_left = 100
    margin_bottom = 90
    margin_top = 60
    margin_right = 40
    chart_width = width - margin_left - margin_right
    chart_height = height - margin_top - margin_bottom
    backend_names = sorted({backend for summary in scenario_summaries for backend in summary["backend_distribution"]})
    palette = ["#06b6d4", "#22c55e", "#f59e0b", "#ef4444", "#8b5cf6"]
    colors = {backend: palette[index % len(palette)] for index, backend in enumerate(backend_names)}
    bar_height = chart_height / max(len(scenario_summaries), 1) * 0.55
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0c1220"/>',
        '<text x="550" y="30" fill="#f4f7fb" text-anchor="middle" font-size="24" font-family="Arial">Distribuzione richieste per replica</text>',
    ]
    for index, summary in enumerate(scenario_summaries):
        y = margin_top + index * (bar_height + 35)
        total = max(sum(summary["backend_distribution"].values()), 1)
        current_x = margin_left
        parts.append(f'<text x="20" y="{y + bar_height/2:.1f}" fill="#c0cad9" font-size="12" font-family="Arial">{summary["scenario"]}</text>')
        for backend, count in sorted(summary["backend_distribution"].items()):
            width_fraction = chart_width * (count / total)
            parts.append(f'<rect x="{current_x:.1f}" y="{y:.1f}" width="{width_fraction:.1f}" height="{bar_height:.1f}" fill="{colors[backend]}" rx="5"/>')
            if width_fraction > 70:
                parts.append(f'<text x="{current_x + width_fraction/2:.1f}" y="{y + bar_height/2 + 4:.1f}" fill="#0c1220" text-anchor="middle" font-size="11" font-family="Arial">{backend}: {count}</text>')
            current_x += width_fraction
    legend_y = height - 28
    legend_x = 100
    for backend in backend_names:
        parts.append(f'<rect x="{legend_x}" y="{legend_y-12}" width="14" height="14" fill="{colors[backend]}" rx="3"/>')
        parts.append(f'<text x="{legend_x + 22}" y="{legend_y}" fill="#c0cad9" font-size="12" font-family="Arial">{backend}</text>')
        legend_x += 190
    parts.append("</svg>")
    path.write_text("\n".join(parts))


def write_timeline_svg(path: Path, scenario_results: list[dict[str, Any]]) -> None:
    timeline_scenarios = [item for item in scenario_results if item["events"]]
    if not timeline_scenarios:
        return
    width, height = _svg_canvas(1100, 560)
    margin_left = 120
    margin_bottom = 60
    margin_top = 60
    margin_right = 40
    max_time = max(
        (event["elapsed_seconds"] for result in timeline_scenarios for event in result["events"]),
        default=1.0,
    )
    if max_time <= 0:
        max_time = 1.0
    row_height = 120
    palette = {
        "action_started": "#f59e0b",
        "action_completed": "#fb7185",
        "kong_state_observed": "#22c55e",
        "kong_state_timeout": "#ef4444",
        "prometheus_state_observed": "#84cc16",
        "prometheus_state_timeout": "#dc2626",
        "routing_transition_observed": "#06b6d4",
    }
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<rect width="100%" height="100%" fill="#0c1220"/>',
        '<text x="550" y="30" fill="#f4f7fb" text-anchor="middle" font-size="24" font-family="Arial">Timeline fault e recovery</text>',
    ]
    for row_index, result in enumerate(timeline_scenarios):
        y = margin_top + row_index * row_height
        parts.append(f'<text x="20" y="{y + 10}" fill="#c0cad9" font-size="12" font-family="Arial">{result["scenario"]}</text>')
        parts.append(f'<line x1="{margin_left}" y1="{y}" x2="{width - margin_right}" y2="{y}" stroke="#344055" stroke-width="2"/>')
        for event in result["events"]:
            x = margin_left + ((width - margin_left - margin_right) * (event["elapsed_seconds"] / max_time))
            color = palette.get(event["event"], "#f4f7fb")
            parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="7" fill="{color}"/>')
            parts.append(f'<text x="{x:.1f}" y="{y - 14:.1f}" fill="#f4f7fb" text-anchor="middle" font-size="10" font-family="Arial">{event["elapsed_seconds"]:.1f}s</text>')
            parts.append(f'<text x="{x:.1f}" y="{y + 24:.1f}" fill="#c0cad9" text-anchor="middle" font-size="10" font-family="Arial">{event["event"]}</text>')
    parts.append("</svg>")
    path.write_text("\n".join(parts))


class ExperimentRunner:
    """Coordina setup, carico, fault injection e raccolta evidenze.

    Questo e` il cuore della suite sperimentale: prepara lo scenario scelto,
    invia richieste continue al gateway, raccoglie metriche da Kong/Prometheus
    e salva sia dati grezzi sia riepiloghi leggibili nella relazione finale.
    """

    def __init__(
        self,
        compose_file: Path,
        env_file: Path,
        gateway_url: str,
        prometheus_url: str,
        kong_admin_url: str,
        output_dir: Path,
    ) -> None:
        self.compose = ComposeController(compose_file, env_file)
        self.gateway_url = gateway_url.rstrip("/")
        self.prometheus = PrometheusClient(prometheus_url.rstrip("/"))
        self.kong_admin = KongAdminClient(kong_admin_url.rstrip("/"), DEFAULT_UPSTREAM_NAME)
        self.output_dir = output_dir
        self.log_lines: list[str] = []

    def log(self, message: str) -> None:
        line = f"[{iso_timestamp()}] {message}"
        self.log_lines.append(line)
        print(line)

    def ensure_prerequisites(self) -> None:
        """Controlla che stack, upstream Kong e target Prometheus siano coerenti."""
        self.compose.ensure_stack_active()
        upstream = self.kong_admin.get_upstream()
        if upstream.get("name") != DEFAULT_UPSTREAM_NAME:
            raise RuntimeError(f"Kong upstream not found: {DEFAULT_UPSTREAM_NAME}")
        service = self.kong_admin.get_service(DEFAULT_KONG_SERVICE_NAME)
        if service.get("name") != DEFAULT_KONG_SERVICE_NAME:
            raise RuntimeError(f"Kong service not found: {DEFAULT_KONG_SERVICE_NAME}")
        health = self.kong_admin.get_upstream_health()
        for service_name, target_name in SERVICE_TARGETS.items():
            if target_name not in health:
                raise RuntimeError(f"Kong target missing from upstream health: {target_name}")
            self.log(f"Kong health check: {target_name} -> {health[target_name]}")
        for instance_name, expression in PROM_TARGETS.items():
            current = self.prometheus.scalar(expression)
            self.log(f"Prometheus up check: {instance_name} -> {current}")

    def restore_final_state(self) -> None:
        """Tenta sempre di lasciare l'ambiente locale in stato pulito post-test."""
        self.log("Restoring final state with both API replicas running.")
        self.compose.restore_default_state()
        for service_name, target_name in SERVICE_TARGETS.items():
            try:
                _state, observed_after = self.kong_admin.wait_for_target_health(
                    target_name,
                    "HEALTHY",
                    timeout_seconds=30.0,
                    poll_interval_seconds=0.05,
                )
                self.log(f"Kong final health restored: {service_name} -> HEALTHY after {observed_after:.3f}s")
            except TimeoutError as exc:
                self.log(f"Kong final health restore timeout: {service_name} -> {exc}")

    def run_scenario(self, scenario: ScenarioConfig) -> dict[str, Any]:
        """Execute one scenario and persist raw evidence plus an aggregated summary."""
        self.log(f"Starting scenario {scenario.name}: {scenario.description}")
        for service, desired_state in scenario.initial_service_states.items():
            self.log(f"Setting initial state: {service} -> {desired_state}")
            docker_command_duration = self.compose.set_service_state(service, desired_state)
            target_name = SERVICE_TARGETS.get(service)
            if target_name is not None:
                expected_health = "HEALTHY" if desired_state == "running" else "UNHEALTHY"
                _state, kong_observed_after = self.kong_admin.wait_for_target_health(
                    target_name,
                    expected_health,
                    timeout_seconds=30.0,
                    poll_interval_seconds=0.05,
                )
                self.log(
                    f"Initial state observed in Kong: {target_name} -> {expected_health} after {kong_observed_after:.3f}s"
                )
            if service in PROM_TARGETS:
                expected_up = 1.0 if desired_state == "running" else 0.0
                _value, observed_after = self.prometheus.wait_for_value(
                    PROM_TARGETS[service],
                    expected_up,
                    poll_interval_seconds=0.5,
                )
                self.log(
                    f"Initial state observed in Prometheus: {service} -> up={expected_up} after {observed_after:.2f}s"
                )
            self.log(f"Initial docker command duration: {service} -> {docker_command_duration:.3f}s")

        samples: list[RequestSample] = []
        events: list[EventRecord] = []
        action_contexts: dict[tuple[str, str], dict[str, Any]] = {}
        benchmark_start_monotonic = time.monotonic()
        started_at = iso_timestamp()
        load_stop_at = benchmark_start_monotonic + scenario.duration_seconds
        action_threads: list[threading.Thread] = []
        samples_lock = threading.Lock()

        def record_event(name: str, details: dict[str, Any]) -> EventRecord:
            # Gli eventi sono salvati insieme ai campioni HTTP per poter
            # correlare il momento del fault con il comportamento del traffico.
            event = EventRecord(
                timestamp=iso_timestamp(),
                elapsed_seconds=time.monotonic() - benchmark_start_monotonic,
                event=name,
                details=details,
            )
            events.append(event)
            return event

        def action_runner(action: ScenarioAction) -> None:
            # Ogni azione viene eseguita in un thread dedicato per lasciare
            # continuare il carico concorrente mentre avvengono stop/start.
            while time.monotonic() < benchmark_start_monotonic + action.offset_seconds:
                time.sleep(0.05)

            action_started_monotonic = time.monotonic()
            action_started_event = record_event("action_started", {"type": action.type, "service": action.service})
            desired_state = "stopped" if action.type == "stop_service" else "running"
            expected_up = 0.0 if desired_state == "stopped" else 1.0
            expected_health = "UNHEALTHY" if desired_state == "stopped" else "HEALTHY"
            target_name = SERVICE_TARGETS.get(action.service)
            action_contexts[(action.type, action.service)] = {
                "action_started_elapsed_seconds": action_started_event.elapsed_seconds,
                "action_started_monotonic": action_started_monotonic,
            }

            self.log(f"Executing action {action.type} on {action.service}")
            docker_command_duration = self.compose.set_service_state(action.service, desired_state)
            record_event(
                "action_completed",
                {
                    "type": action.type,
                    "service": action.service,
                    "docker_command_duration_seconds": docker_command_duration,
                },
            )

            if target_name is not None:
                try:
                    _state, observed_after = self.kong_admin.wait_for_target_health(
                        target_name,
                        expected_health,
                        timeout_seconds=30.0,
                        poll_interval_seconds=0.05,
                    )
                    record_event(
                        "kong_state_observed",
                        {
                            "service": action.service,
                            "target": target_name,
                            "expected_health": expected_health,
                            "observed_after_seconds": observed_after,
                        },
                    )
                except TimeoutError as exc:
                    record_event(
                        "kong_state_timeout",
                        {
                            "service": action.service,
                            "target": target_name,
                            "expected_health": expected_health,
                            "error": str(exc),
                        },
                    )

            if action.service in PROM_TARGETS:
                try:
                    _value, observed_after = self.prometheus.wait_for_value(
                        PROM_TARGETS[action.service],
                        expected_up,
                        poll_interval_seconds=0.5,
                    )
                    record_event(
                        "prometheus_state_observed",
                        {
                            "service": action.service,
                            "expected_up": expected_up,
                            "observed_after_seconds": observed_after,
                        },
                    )
                except TimeoutError as exc:
                    record_event(
                        "prometheus_state_timeout",
                        {"service": action.service, "error": str(exc)},
                    )

        for action in scenario.actions:
            thread = threading.Thread(target=action_runner, args=(action,), daemon=True)
            thread.start()
            action_threads.append(thread)

        def worker() -> None:
            # I worker del benchmark non sono gli analysis-worker applicativi:
            # qui rappresentano semplicemente thread che generano richieste
            # concorrenti verso Kong per simulare traffico continuo.
            endpoint_url = f"{self.gateway_url}{scenario.endpoint_path}"
            while time.monotonic() < load_stop_at:
                sample = perform_request(endpoint_url, scenario.timeout_seconds, benchmark_start_monotonic)
                with samples_lock:
                    samples.append(sample)

        with ThreadPoolExecutor(max_workers=scenario.concurrency) as executor:
            futures = [executor.submit(worker) for _ in range(scenario.concurrency)]
            for future in futures:
                future.result()

        for thread in action_threads:
            thread.join()

        finished_at = iso_timestamp()

        self._derive_transition_events(scenario, samples, action_contexts, record_event)
        prometheus_snapshot = self._collect_prometheus_snapshot()
        summary = self._build_summary(scenario, samples, started_at, finished_at)
        self._enrich_summary_from_events(summary, events)
        payload = {
            "scenario": summary["scenario"],
            "description": scenario.description,
            "config": {
                "endpoint_path": scenario.endpoint_path,
                "duration_seconds": scenario.duration_seconds,
                "concurrency": scenario.concurrency,
                "timeout_seconds": scenario.timeout_seconds,
                "expected_active_replicas": scenario.expected_active_replicas,
                "initial_service_states": scenario.initial_service_states,
                "actions": [asdict(action) for action in scenario.actions],
            },
            "summary": summary,
            "events": [asdict(event) for event in events],
            "prometheus_snapshot": prometheus_snapshot,
            "requests": [asdict(sample) for sample in samples],
        }
        write_json(self.output_dir / f"{scenario.name}.json", payload)
        self.log(f"Completed scenario {scenario.name} with {summary['total_requests']} requests.")
        return payload

    def _derive_transition_events(
        self,
        scenario: ScenarioConfig,
        samples: list[RequestSample],
        action_contexts: dict[tuple[str, str], dict[str, Any]],
        record_event: Callable[[str, dict[str, Any]], EventRecord],
    ) -> None:
        """Deriva il momento in cui il routing smette o riprende di usare una replica.

        Questo passaggio e` importante per la relazione: separa il semplice
        stop/start del container dal momento in cui il traffico cambia davvero.
        """
        if not scenario.actions:
            return
        for action in scenario.actions:
            context = action_contexts.get((action.type, action.service))
            if not context:
                continue
            action_started_elapsed = context["action_started_elapsed_seconds"]
            relevant_samples = [
                sample
                for sample in samples
                if sample.backend_instance == action.service and sample.elapsed_seconds >= action_started_elapsed
            ]
            if action.type == "stop_service":
                if relevant_samples:
                    last_sample = max(relevant_samples, key=lambda item: item.elapsed_seconds)
                    record_event(
                        "routing_transition_observed",
                        {
                            "service": action.service,
                            "kind": "last_request_after_stop",
                            "observed_after_seconds": last_sample.elapsed_seconds - action_started_elapsed,
                        },
                    )
            elif action.type == "start_service":
                if relevant_samples:
                    first_sample = min(relevant_samples, key=lambda item: item.elapsed_seconds)
                    record_event(
                        "routing_transition_observed",
                        {
                            "service": action.service,
                            "kind": "first_request_after_start",
                            "observed_after_seconds": first_sample.elapsed_seconds - action_started_elapsed,
                        },
                    )

    def _collect_prometheus_snapshot(self) -> dict[str, Any]:
        """Salva uno snapshot finale delle metriche piu` rilevanti."""
        return {
            "api_targets_up": {
                service: self.prometheus.scalar(expression)
                for service, expression in PROM_TARGETS.items()
            },
            "kong_requests_total_rate": self.prometheus.scalar("sum(rate(kong_http_requests_total[1m]))"),
            "api_requests_by_instance": self.prometheus.instant_query(
                'sum by (instance_id) (rate(securescan_api_http_requests_total[1m]))'
            ),
            "worker_running": self.prometheus.instant_query("securescan_worker_running"),
        }

    def _build_summary(
        self,
        scenario: ScenarioConfig,
        samples: list[RequestSample],
        started_at: str,
        finished_at: str,
    ) -> dict[str, Any]:
        """Calcola il riepilogo numerico usato in CSV, JSON e grafici finali."""
        latencies = [sample.latency_ms for sample in samples]
        successful = [sample for sample in samples if sample.success]
        failed = [sample for sample in samples if not sample.success]
        backend_distribution = Counter(sample.backend_instance or "unknown" for sample in successful)
        duration = max(scenario.duration_seconds, 0.001)
        return {
            "scenario": scenario.name,
            "started_at": started_at,
            "finished_at": finished_at,
            "duration_seconds": scenario.duration_seconds,
            "concurrency": scenario.concurrency,
            "expected_active_replicas": scenario.expected_active_replicas,
            "action_type": scenario.actions[0].type if scenario.actions else None,
            "action_service": scenario.actions[0].service if scenario.actions else None,
            "kong_transition_seconds": None,
            "prometheus_transition_seconds": None,
            "routing_transition_seconds": None,
            "total_requests": len(samples),
            "successful_requests": len(successful),
            "failed_requests": len(failed),
            "http_2xx_requests": sum(
                1
                for sample in samples
                if sample.success and sample.status_code is not None and 200 <= sample.status_code < 300
            ),
            "http_5xx_requests": sum(1 for sample in samples if sample.status_code is not None and 500 <= sample.status_code < 600),
            "client_error_requests": sum(1 for sample in failed if sample.error_category == "client_error"),
            "timeout_requests": sum(1 for sample in failed if sample.error_category == "timeout"),
            "error_rate": (len(failed) / len(samples)) if samples else 0.0,
            "throughput_rps": len(samples) / duration,
            "latency_min_ms": min(latencies, default=0.0),
            "latency_avg_ms": (sum(latencies) / len(latencies)) if latencies else 0.0,
            "latency_p50_ms": percent(latencies, 0.50),
            "latency_p95_ms": percent(latencies, 0.95),
            "latency_p99_ms": percent(latencies, 0.99),
            "latency_max_ms": max(latencies, default=0.0),
            "max_latency_ms": max(latencies, default=0.0),
            "backend_distribution": dict(sorted(backend_distribution.items())),
        }

    def _enrich_summary_from_events(self, summary: dict[str, Any], events: list[EventRecord]) -> None:
        """Trasferisce nel summary le misure di detection/recovery derivate dagli eventi."""
        for event in events:
            if event.event == "kong_state_observed":
                summary["kong_transition_seconds"] = event.details.get("observed_after_seconds")
            elif event.event == "prometheus_state_observed":
                summary["prometheus_transition_seconds"] = event.details.get("observed_after_seconds")
            elif event.event == "routing_transition_observed":
                summary["routing_transition_seconds"] = event.details.get("observed_after_seconds")

    def finalize(self, results: list[dict[str, Any]]) -> None:
        """Scrive tutti gli artefatti finali leggibili per confronto e relazione."""
        summaries = [result["summary"] for result in results]
        write_summary_csv(self.output_dir / "summary.csv", summaries)
        write_bar_chart_svg(
            self.output_dir / "throughput_by_scenario.svg",
            title="Throughput per scenario",
            x_label="Scenario",
            y_label="Richieste al secondo",
            values={summary["scenario"]: summary["throughput_rps"] for summary in summaries},
            color="#06b6d4",
        )
        write_grouped_latency_svg(self.output_dir / "latency_percentiles_by_scenario.svg", summaries)
        write_bar_chart_svg(
            self.output_dir / "error_rate_by_scenario.svg",
            title="Error rate per scenario",
            x_label="Scenario",
            y_label="Error rate",
            values={summary["scenario"]: summary["error_rate"] * 100 for summary in summaries},
            color="#ef4444",
        )
        write_backend_distribution_svg(self.output_dir / "backend_distribution.svg", summaries)
        write_timeline_svg(self.output_dir / "fault_recovery_timeline.svg", results)
        (self.output_dir / "run.log").write_text("\n".join(self.log_lines) + "\n")


def parse_args() -> argparse.Namespace:
    """Definisce la CLI della suite sperimentale."""
    parser = argparse.ArgumentParser(description="Run SecureScan Cloud benchmark scenarios.")
    parser.add_argument("--scenario", action="append", help="Scenario name to run. Can be repeated.")
    parser.add_argument("--all", action="store_true", help="Run all available scenarios.")
    parser.add_argument("--duration-scale", type=float, default=1.0, help="Scale scenario durations.")
    parser.add_argument("--gateway-url", default=DEFAULT_GATEWAY_URL, help="Public gateway base URL.")
    parser.add_argument("--prometheus-url", default=DEFAULT_PROMETHEUS_URL, help="Prometheus base URL.")
    parser.add_argument("--kong-admin-url", default=DEFAULT_KONG_ADMIN_URL, help="Kong Admin API base URL.")
    parser.add_argument("--compose-file", default=str(DEFAULT_COMPOSE_FILE), help="Compose file path.")
    parser.add_argument("--env-file", default=str(DEFAULT_ENV_FILE), help="Compose env file path.")
    parser.add_argument("--output-dir", help="Explicit output directory.")
    return parser.parse_args()


def resolve_scenarios(args: argparse.Namespace) -> list[Path]:
    """Converte i nomi richiesti da CLI nei file scenario presenti nel repository."""
    available = {path.stem: path for path in sorted(SCENARIOS_DIR.glob("*.json"))}
    if args.all:
        return list(available.values())
    if args.scenario:
        missing = [name for name in args.scenario if name not in available]
        if missing:
            raise SystemExit(f"Unknown scenarios: {', '.join(missing)}")
        return [available[name] for name in args.scenario]
    raise SystemExit("Specify --all or at least one --scenario.")


def create_output_dir(explicit_dir: str | None) -> Path:
    """Crea la directory in cui verranno salvati JSON, CSV, log e grafici SVG."""
    if explicit_dir:
        output_dir = Path(explicit_dir).resolve()
    else:
        timestamp = utc_now().strftime("%Y%m%dT%H%M%SZ")
        output_dir = RESULTS_DIR / timestamp
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


def main() -> int:
    """Entry point della suite benchmark HA locale."""
    args = parse_args()
    scenario_paths = resolve_scenarios(args)
    output_dir = create_output_dir(args.output_dir)
    runner = ExperimentRunner(
        compose_file=Path(args.compose_file).resolve(),
        env_file=Path(args.env_file).resolve(),
        gateway_url=args.gateway_url,
        prometheus_url=args.prometheus_url,
        kong_admin_url=args.kong_admin_url,
        output_dir=output_dir,
    )

    results: list[dict[str, Any]] = []
    try:
        runner.ensure_prerequisites()
        for path in scenario_paths:
            scenario = load_scenario(path, args.duration_scale)
            results.append(runner.run_scenario(scenario))
    finally:
        try:
            runner.restore_final_state()
        except Exception as exc:  # noqa: BLE001
            runner.log(f"Final state restore failed: {exc}")

    if results:
        runner.finalize(results)
    print(f"Results written to {output_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
