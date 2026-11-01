"""Tests for the Prometheus exposition the canary analysis queries."""

from __future__ import annotations

from conftest import bucket_count, make_client, request_count, sample, samples


def test_request_counter_by_status_code(client):
    client.get("/")
    client.get("/")
    assert request_count(client, "/", 200) == 2.0


def test_error_requests_are_counted_separately():
    client = make_client(fault_mode="errors", fault_error_rate=1.0)
    client.get("/api/items")
    assert request_count(client, "/api/items", 500) == 1.0
    no_success = 'http_requests_total{method="GET",path="/api/items",status="200"}'
    assert no_success not in samples(client)


def test_latency_histogram_has_status_class(client):
    client.get("/")
    count = sample(
        client, "http_request_duration_seconds_count", method="GET", path="/", status_class="2xx"
    )
    assert count == 1.0


def test_histogram_buckets_are_finite_for_quantiles(client):
    client.get("/")
    assert bucket_count(client, "0.5") == 1.0
    assert any('le="+Inf"' in key for key in samples(client))


def test_the_scrape_endpoint_itself_is_not_counted(client):
    client.get("/metrics")
    client.get("/metrics")
    assert not any('path="/metrics"' in key for key in samples(client))


def test_unmatched_paths_do_not_create_new_labels(client):
    client.get("/no-such-route-xyz")
    assert request_count(client, "unmatched", 404) == 1.0


def test_build_info_marks_the_running_version(client):
    info = sample(
        client,
        "app_build_info",
        version="deadbeef",
        environment="test",
        pod="pod-test",
        fault_mode="none",
    )
    assert info == 1.0
