# syntax=docker/dockerfile:1.7

# config-repo/versions.env holds the authoritative pin and CI passes it here;
# this default only exists so `docker build .` works standalone.
ARG PYTHON_BASE_IMAGE=python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df

# ---- build: resolve and install dependencies into a venv ---------------------
FROM ${PYTHON_BASE_IMAGE} AS build

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /build

# Only the manifest is copied first, so the dependency layer is reused whenever
# the code changes but requirements.txt does not.
COPY requirements.txt ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install -r requirements.txt

# ---- runtime: no compiler, no pip cache, no source tooling -------------------
FROM ${PYTHON_BASE_IMAGE} AS runtime

# ARG values reset at each FROM, so re-declare the ones this stage uses.
ARG GIT_SHA=dev
ARG PYTHON_BASE_IMAGE
# CI passes $GITHUB_SERVER_URL/$GITHUB_REPOSITORY; locally pass
# $(git config --get remote.origin.url). No handle is hardcoded in the repo.
ARG REPO_URL=
LABEL org.opencontainers.image.title="gitops-demo" \
      org.opencontainers.image.source="${REPO_URL}" \
      org.opencontainers.image.revision="${GIT_SHA}" \
      org.opencontainers.image.base.name="${PYTHON_BASE_IMAGE}"

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
