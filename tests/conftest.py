"""Shared fixtures and a small Prometheus text-format parser for assertions."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from app.settings import Settings

BASE = {
    "app_name": "gitops-demo",
    "environment": "test",
    "version": "deadbeef",
    "pod_name": "pod-test",
}

LABEL_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"')


def make_client(**overrides) -> TestClient:
    settings = Settings(**{**BASE, "fault_mode": "none", **overrides})
    return TestClient(create_app(settings))


def metric_key(line: str) -> str:
    """`name{b="2",a="1"} 3.0` -> `name{a="1",b="2"}`, labels sorted."""
    key, _, _value = line.strip().rpartition(" ")
    name, _, rest = key.partition("{")
    if not rest:
        return name
    ordered = ",".join(f'{k}="{v}"' for k, v in sorted(LABEL_RE.findall(rest)))
    return f"{name}{{{ordered}}}"


def samples(client: TestClient) -> dict[str, float]:
    body = client.get("/metrics").text
    return {
        metric_key(line): float(line.rpartition(" ")[2])
        for line in body.splitlines()
        if line and not line.startswith("#")
    }


def sample(client: TestClient, name: str, **labels) -> float:
    ordered = ",".join(f'{k}="{v}"' for k, v in sorted(labels.items()))
    key = f"{name}{{{ordered}}}"
    found = samples(client)
    assert key in found, f"{key} missing. Have: {sorted(found)}"
    return found[key]


def request_count(client: TestClient, path: str, status: int, method: str = "GET") -> float:
    return sample(client, "http_requests_total", method=method, path=path, status=str(status))


def bucket_count(
    client: TestClient,
    le: str,
    path: str = "/",
    status_class: str = "2xx",
    method: str = "GET",
) -> float:
    return sample(
        client,
        "http_request_duration_seconds_bucket",
        le=le,
        method=method,
        path=path,
        status_class=status_class,
    )


@pytest.fixture
def client() -> TestClient:
    return make_client()
