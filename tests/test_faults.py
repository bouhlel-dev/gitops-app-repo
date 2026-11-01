"""Tests for fault injection and settings validation."""

from __future__ import annotations

import time

import pytest
from conftest import BASE, bucket_count, make_client, request_count

from app import main
from app.faults import delay_seconds, should_fail
from app.settings import DEFAULT_FAULT_MODE, FAULT_MODES, Settings


def shipped_settings(**overrides) -> Settings:
    return Settings(**{**BASE, "fault_mode": "none", **overrides})


class FakeRandom:
    """Deterministic stand-in for random.random()."""

    def __init__(self, values):
        self.values = list(values)
        self.index = 0

    def random(self):
        value = self.values[self.index % len(self.values)]
        self.index += 1
        return value


def test_the_shipped_default_is_a_healthy_release():
    # The bad-release demo flips exactly this constant, so assert that the
    # version on the main branch is the healthy one.
    assert DEFAULT_FAULT_MODE == "none"


def test_should_fail_only_in_errors_mode():
    errors = shipped_settings(fault_mode="errors", fault_error_rate=0.5)
    assert should_fail(errors, 0.4) is True
    assert should_fail(errors, 0.6) is False
    assert should_fail(shipped_settings(fault_error_rate=1.0), 0.0) is False
    slow = shipped_settings(fault_mode="slow", fault_error_rate=1.0)
    assert should_fail(slow, 0.0) is False


def test_delay_only_in_slow_mode():
    slow = shipped_settings(fault_mode="slow", fault_latency_ms=2000)
    assert delay_seconds(slow) == 2.0
    assert delay_seconds(shipped_settings(fault_mode="errors", fault_latency_ms=2000)) == 0.0


def test_errors_rate_one_faults_every_business_call():
    client = make_client(fault_mode="errors", fault_error_rate=1.0)
    assert client.get("/").status_code == 500
    assert client.get("/api/items").status_code == 500


def test_errors_rate_zero_is_clean():
    client = make_client(fault_mode="errors", fault_error_rate=0.0)
    assert client.get("/").status_code == 200


def test_error_rate_is_applied_per_request(monkeypatch):
    monkeypatch.setattr(main, "random", FakeRandom([0.4, 0.6]))
    client = make_client(fault_mode="errors", fault_error_rate=0.5)
    assert client.get("/").status_code == 500
    assert client.get("/").status_code == 200


def test_slow_mode_is_visible_in_the_histogram():
    client = make_client(fault_mode="slow", fault_latency_ms=150)
    started = time.perf_counter()
    assert client.get("/").status_code == 200
    assert time.perf_counter() - started >= 0.15
    # What the p95 analysis notices: the request misses the fast buckets.
    assert bucket_count(client, "0.05") == 0.0
    assert bucket_count(client, "0.25") == 1.0


def test_metrics_are_recorded_for_faulted_calls():
    client = make_client(fault_mode="errors", fault_error_rate=1.0)
    client.get("/api/items")
    assert request_count(client, "/api/items", 500) == 1.0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"fault_mode": "bogus"},
        {"fault_error_rate": 1.5},
        {"fault_error_rate": -0.1},
        {"fault_latency_ms": -5},
    ],
)
def test_invalid_settings_are_rejected_at_startup(kwargs):
    with pytest.raises(ValueError):
        shipped_settings(**kwargs)


def test_every_documented_fault_mode_is_accepted():
    for mode in FAULT_MODES:
        assert shipped_settings(fault_mode=mode).fault_mode == mode


def test_settings_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.setenv("APP_VERSION", "1a2b3c4")
    monkeypatch.setenv("POD_NAME", "gitops-demo-7f9c-abcde")
    monkeypatch.setenv("FAULT_MODE", "slow")
    monkeypatch.setenv("FAULT_ERROR_RATE", "0.7")
    monkeypatch.setenv("FAULT_LATENCY_MS", "900")
    settings = Settings.from_env()
    assert settings.environment == "prod"
    assert settings.version == "1a2b3c4"
    assert settings.pod_name == "gitops-demo-7f9c-abcde"
    assert settings.fault_mode == "slow"
    assert settings.fault_error_rate == 0.7
    assert settings.fault_latency_ms == 900


def test_unknown_env_fault_mode_fails_fast(monkeypatch):
    monkeypatch.setenv("FAULT_MODE", "explode")
    with pytest.raises(ValueError):
        Settings.from_env()
