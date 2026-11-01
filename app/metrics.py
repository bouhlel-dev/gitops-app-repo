"""Prometheus metrics for one process.

Each app owns its CollectorRegistry: tests are isolated and counters are
deterministic, and with a single uvicorn worker the scrape always reflects the
whole pod instead of one worker.
"""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram
from prometheus_client.exposition import generate_latest

# Text exposition 0.0.4: what Prometheus scrapes by default and what every
# Grafana/Prometheus tutorial reads, so the panel needs no special config.
CONTENT_TYPE = "text/plain; version=0.0.4; charset=utf-8"

# Buckets chosen around the analysis thresholds (p95 target of 500 ms) so the
# histogram_quantile estimate is meaningful, not a straight line to +Inf.
LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def status_class(status_code: int) -> str:
    return f"{status_code // 100}xx"


class Metrics:
    def __init__(self, registry: CollectorRegistry | None = None) -> None:
        self.registry = registry if registry is not None else CollectorRegistry()
        self.requests = Counter(
            "http_requests_total",
            "Requests handled, by method, route and status code.",
            ("method", "path", "status"),
            registry=self.registry,
        )
        self.latency = Histogram(
            "http_request_duration_seconds",
            "Request latency, by method, route and status class.",
            ("method", "path", "status_class"),
            buckets=LATENCY_BUCKETS,
            registry=self.registry,
        )
        # Lets Grafana show which build and fault mode each pod is serving, so a
        # canary failure is visible as a version, not just as a dip.
        self.build_info = Gauge(
            "app_build_info",
            "Always 1; labels describe the running build.",
            ("version", "environment", "pod", "fault_mode"),
            registry=self.registry,
        )

    def set_build_info(self, *, version: str, environment: str, pod: str, fault_mode: str) -> None:
        self.build_info.labels(
            version=version, environment=environment, pod=pod, fault_mode=fault_mode
        ).set(1)

    def record(self, method: str, path: str, status_code: int, duration_seconds: float) -> None:
        self.requests.labels(method=method, path=path, status=str(status_code)).inc()
        self.latency.labels(
            method=method, path=path, status_class=status_class(status_code)
        ).observe(duration_seconds)

    def expose(self) -> bytes:
        return generate_latest(self.registry)
