"""Tests for the request/response contract."""

from __future__ import annotations

from conftest import make_client


def test_root_reports_build_identity(client):
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "service": "gitops-demo",
        "version": "deadbeef",
        "environment": "test",
        "pod": "pod-test",
        "message": "hello from GitOps",
    }
    assert response.headers["X-App-Version"] == "deadbeef"
    assert response.headers["X-Pod"] == "pod-test"


def test_items_endpoint_is_served(client):
    response = client.get("/api/items")
    assert response.status_code == 200
    assert len(response.json()["items"]) == 3


def test_health_is_200_with_version(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["version"] == "deadbeef"


def test_metrics_endpoint_serves_prometheus_text(client):
    response = client.get("/metrics")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "# HELP http_requests_total" in response.text


def test_unknown_path_is_404(client):
    assert client.get("/does-not-exist").status_code == 404


def test_health_stays_200_when_the_release_is_faulty():
    """The invariant that makes the canary demo work.

    If /health failed while faults were injected, Kubernetes would evict the
    canary from the Service and the analysis would see no traffic at all.
    """
    client = make_client(fault_mode="errors", fault_error_rate=1.0)
    assert client.get("/").status_code == 500
    assert client.get("/health").status_code == 200
