"""HTTP surface: business endpoints, probes and the Prometheus scrape endpoint."""

from __future__ import annotations

import asyncio
import random
import time

from fastapi import Depends, FastAPI, HTTPException, Request, Response

from .faults import delay_seconds, should_fail
from .metrics import CONTENT_TYPE, Metrics
from .settings import Settings

# Prometheus scrapes this every few seconds. Counting the scrapes would let a
# steady stream of internal 200s mask a bad release in the success-rate query.
UNINSTRUMENTED_PATHS = frozenset({"/metrics"})

# The bad-release demo (config-repo/scripts/demo-bad-release.sh) ships this as
# 600.0 instead of 0.0. It is a code default, not a knob anyone is meant to
# touch in a real deployment: no test measures time, no linter spots it and
# Trivy has nothing to say about it, so CI publishes the regression happily and
# the only thing in the chain that stops it is the p95 the canary is measured
# on. That is the claim the demo is making, so the switch lives in the app.
EXTRA_LATENCY_MS = 600.0


def route_label(request: Request) -> str:
    """Route template if it matched, otherwise a single constant.

    Keeps label cardinality bounded, so a scan for `/{anything}` cannot flood
    the Prometheus TSDB.
    """
    route = request.scope.get("route")
    return getattr(route, "path", None) or "unmatched"


async def inject_faults(request: Request) -> None:
    """Attached to business endpoints only, never to the probes."""
    settings: Settings = request.app.state.settings
    if should_fail(settings, random.random()):
        raise HTTPException(status_code=500, detail="injected fault: simulated bad release")
    delay = delay_seconds(settings)
    if delay:
        await asyncio.sleep(delay)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings if settings is not None else Settings.from_env()
    metrics = Metrics()
    metrics.set_build_info(
        version=settings.version,
        environment=settings.environment,
        pod=settings.pod_name,
        fault_mode=settings.fault_mode,
    )

    app = FastAPI(title=settings.app_name, version=settings.version)
    app.state.settings = settings
    app.state.metrics = metrics

    @app.middleware("http")
    async def measure_latency(request: Request, call_next):
        if request.url.path in UNINSTRUMENTED_PATHS:
            return await call_next(request)
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            metrics.record(
                request.method,
                route_label(request),
                status_code,
                time.perf_counter() - started,
            )

    @app.get("/", dependencies=[Depends(inject_faults)])
    async def index(request: Request, response: Response) -> dict:
        response.headers["X-App-Version"] = settings.version
        response.headers["X-Pod"] = settings.pod_name
        return {
            "service": settings.app_name,
            "version": settings.version,
            "environment": settings.environment,
            "pod": settings.pod_name,
            "message": "hello from GitOps",
        }

    @app.get("/api/items", dependencies=[Depends(inject_faults)])
    async def items(request: Request, response: Response) -> dict:
        if EXTRA_LATENCY_MS:
            await asyncio.sleep(EXTRA_LATENCY_MS / 1000)
        response.headers["X-App-Version"] = settings.version
        response.headers["X-Pod"] = settings.pod_name
        return {
            "version": settings.version,
            "pod": settings.pod_name,
            "items": [
                {"id": 1, "name": "kind"},
                {"id": 2, "name": "argocd"},
                {"id": 3, "name": "rollouts"},
            ],
        }

    @app.get("/health")
    async def health(response: Response) -> dict:
        # Always 200 while the process is up. A probe that failed on the injected
        # fault would pull the canary out of the Service endpoints and starve the
        # canary analysis of the traffic that proves the version is bad.
        response.headers["X-App-Version"] = settings.version
        return {"status": "ok", "version": settings.version, "pod": settings.pod_name}

    @app.get("/metrics")
    async def scrape() -> Response:
        return Response(content=metrics.expose(), media_type=CONTENT_TYPE)

    return app


app = create_app()
