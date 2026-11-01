# syntax=docker/dockerfile:1.7

# ---- build: resolve and install dependencies into a venv ---------------------
FROM python:3.12-slim-bookworm AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Only the manifest is copied first, so the dependency layer is reused whenever
# the code changes but requirements.txt does not.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.txt

# ---- runtime: no compiler, no pip cache, no source tooling -------------------
FROM python:3.12-slim-bookworm AS runtime

ARG GIT_SHA=dev
LABEL org.opencontainers.image.title="gitops-demo" \
      org.opencontainers.image.source="https://github.com/OWNER/app-repo" \
      org.opencontainers.image.revision="${GIT_SHA}"

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/opt/venv/bin:${PATH}" \
    APP_VERSION="${GIT_SHA}"

# uid/gid 10001 is also what config-repo expects in securityContext.
RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY app/ ./app/

USER 10001:10001
EXPOSE 8000

# curl is not installed on purpose; the probe uses the interpreter already here.
HEALTHCHECK --interval=15s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"]

ENTRYPOINT ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
