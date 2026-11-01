"""Fault injection used to simulate a bad release.

Pure functions taking an explicit `sample` so the tests are deterministic and
the app decides where randomness comes from.
"""

from __future__ import annotations

from .settings import Settings


def should_fail(settings: Settings, sample: float) -> bool:
    """True when this request should answer HTTP 500."""
    if settings.fault_mode != "errors":
        return False
    return sample < settings.fault_error_rate


def delay_seconds(settings: Settings) -> float:
    """Extra latency to add, in seconds (slow mode only)."""
    if settings.fault_mode != "slow":
        return 0.0
    return settings.fault_latency_ms / 1000.0
