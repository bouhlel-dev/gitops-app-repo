"""Configuration, read once from the environment at process start.

The cluster manifests in config-repo are the only place these values are set in
production, so a running pod can always be traced back to a Git commit.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

FAULT_MODES = ("none", "errors", "slow")

# Switch used by the bad-release demo: a one-line change of this default ships a
# faulty version through lint, tests, scanning and CI unchanged. It is a code
# default, not a secret -- the point is that CI cannot tell it is bad.
DEFAULT_FAULT_MODE = "none"


def _float_env(name: str, default: float) -> float:
    raw = os.environ.get(name, "")
    return float(raw) if raw.strip() else default


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name, "")
    return int(raw) if raw.strip() else default


@dataclass(frozen=True)
class Settings:
    app_name: str = "gitops-demo"
    environment: str = "dev"
    version: str = "unknown"
    pod_name: str = "local"
    fault_mode: str = DEFAULT_FAULT_MODE
    fault_error_rate: float = 0.25
    fault_latency_ms: int = 2000

    def __post_init__(self) -> None:
        if self.fault_mode not in FAULT_MODES:
            raise ValueError(f"FAULT_MODE must be one of {FAULT_MODES}, got {self.fault_mode!r}")
        if not 0.0 <= self.fault_error_rate <= 1.0:
            raise ValueError(
                f"FAULT_ERROR_RATE must be between 0 and 1, got {self.fault_error_rate}"
            )
        if self.fault_latency_ms < 0:
            raise ValueError(f"FAULT_LATENCY_MS must be >= 0, got {self.fault_latency_ms}")

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            environment=os.environ.get("APP_ENV", "dev"),
            # CI bakes the git SHA into APP_VERSION, so a pod reports the commit
            # that produced it.
            version=os.environ.get("APP_VERSION", "unknown"),
            # Set by the downward API in config-repo; empty outside Kubernetes.
            pod_name=os.environ.get("POD_NAME", "local"),
            fault_mode=os.environ.get("FAULT_MODE", DEFAULT_FAULT_MODE),
            fault_error_rate=_float_env("FAULT_ERROR_RATE", 0.25),
            fault_latency_ms=_int_env("FAULT_LATENCY_MS", 2000),
        )
