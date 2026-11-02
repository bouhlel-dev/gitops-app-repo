# gitops-app-repo — the application and the pipeline that ships it

One small FastAPI service whose job is to be *deployable*. It has three business
endpoints, two probes and a Prometheus scrape endpoint, and nothing else. Every
interesting thing about this project happens either in
[`.github/workflows/ci.yml`](.github/workflows/ci.yml) or in
[gitops-config-repo](https://github.com/bouhlel-dev/gitops-config-repo), which
holds the manifests and the cluster.

```
here: code, Dockerfile, CI            config-repo: desired state, Argo CD, bootstrap
        |                                        ^
        |  build, test, scan, push               |  Argo CD syncs what merged here
        +--> GHCR image ---- promote tag ------>+
                                                 |
                                                 v
                                    Rollout 10 -> 30 -> 60 -> 100, analysed on
                                    Prometheus metrics, auto-rollback on failure
```

## Layout

```
app/main.py          endpoints, probes, /metrics, the latency switch for the demo
app/settings.py      every value read from the environment, validated once
app/faults.py        the injected failures the canary demo can switch on
app/metrics.py       Prometheus counters and histograms, no global registry
tests/               28 tests, none of which measures a duration (that matters)
Dockerfile           two stages, non-root, digest-pinned base, HEALTHCHECK
.github/workflows/ci.yml
```

## Run it locally

```bash
python -m venv .venv
.venv/Scripts/pip install -r requirements-dev.txt
.venv/Scripts/python -m uvicorn app.main:app --reload --port 8000

curl localhost:8000/            # {"service":"gitops-demo","version":"dev",...}
curl localhost:8000/api/items
curl localhost:8000/health
curl localhost:8000/metrics
```

Or as the image the cluster actually runs:

```bash
docker build -t gitops-demo:dev .
docker run --rm -p 8000:8000 gitops-demo:dev
```

## Check it

```bash
.venv/Scripts/python -m ruff check app tests
.venv/Scripts/python -m ruff format --check app tests
.venv/Scripts/python -m pytest -q                    # 28 passed
```

CI runs those three inside the image's own base image
(`python:3.12-slim-bookworm@sha256:e697c8…`), not on the runner's Python. There is
no "it passed on my machine" case, because the machine it runs on is the
interpreter that ships.

## The pipeline

[`ci.yml`](.github/workflows/ci.yml) has two jobs. `test` gates the commit;
`deliver` produces the artifact and the deployment request.

| Stage | What it does | What stops on it |
|---|---|---|
| Lint and test | ruff + pytest in the pinned base image | style, typing of env values, contract tests |
| Build | `docker buildx build` with `GIT_SHA` as a build arg | Dockerfile faults, a layer that cannot be produced |
| Scan | Trivy at the pinned version, `--severity HIGH,CRITICAL --ignore-unfixed` | any fixable HIGH or CRITICAL in the image |
| Publish | push `ghcr.io/bouhlel-dev/gitops-demo:<sha>` with `GITHUB_TOKEN` | nothing above it passed |
| Promote | `kustomize edit set image` in a checkout of config-repo, re-render and *grep the output* for the tag, commit, open a PR, squash-merge it | the render guard |

Two details carry weight:

- **The tag is the commit, never only `latest`.** `${GITHUB_SHA::7}` is also
  baked into `APP_VERSION`, so a running pod reports which commit produced it and
  a version can be traced in both directions.
- **The render guard.** Before CI commits anything it renders both overlays and
  greps for `image: …:<sha>`. A promotion that silently failed to rewrite the tag
  is a red build, not a cluster that keeps running the old image while a green
  checkmark says otherwise.

CI never runs `kubectl`. The only write it performs against a cluster is a commit
to a git repository.

## Secrets

| Credential | Where | Scope |
|---|---|---|
| `GITHUB_TOKEN` | provided by Actions, `packages: write` | push to this repo's GHCR packages |
| `CONFIG_REPO_TOKEN` | Actions secret of this repo | fine-grained PAT: `Contents: read/write` + `Pull requests: read/write`, on config-repo only |

The default `GITHUB_TOKEN` cannot write to another repository, which is why the
PAT exists. It is passed as the `token:` input of the config-repo
`actions/checkout` step — without that, Git falls back to the runner's
`GIT_ASKPASS`, which vends the Actions bot's own token, and config-repo answers
the push with `403 denied to github-actions[bot]`. Nothing in this repository or
in either workflow file contains a credential.

## Version pins live in the other repo

`config-repo/versions.env` is the single source of truth for the Python base
image, Trivy, kustomize and every tool CI installs. `ci.yml` checks config-repo
out, sources that file and installs at exactly those versions. The `ARG` default
in the Dockerfile exists only so `docker build .` works standalone.

## Fault injection, and why the demo switches are honest

`app/settings.py` reads three knobs — `FAULT_MODE` (`none|errors|slow`),
`FAULT_ERROR_RATE`, `FAULT_LATENCY_MS` — and `app/faults.py` applies them to
business endpoints only, never to `/health`. A probe that failed on an injected
fault would pull the canary out of the Service endpoints and starve the analysis
of exactly the traffic that proves the version is bad.

`app/main.py` also holds `EXTRA_LATENCY_MS = 0.0`. The bad-release demo ships it
as `600.0`. It is a code default, not a secret and not a knob anyone should touch
in a real deployment, and that is the point: ruff formats it, no test measures a
duration, Trivy has nothing to say about latency, the image builds and CI
publishes it. There is even a test asserting the shipped default is a healthy
release — it checks `DEFAULT_FAULT_MODE == "none"`, which stays true. The
regression reaches production-looking traffic with a fully green pipeline, and
the p95 of the canary is the first thing in the chain that objects.

The `/metrics` endpoint is excluded from instrumentation on purpose: counting the
scrapes would let a stream of internal 200s dilute the success rate the release
decision is made on.

## Metrics exposed

| Metric | Labels | Used by |
|---|---|---|
| `http_requests_total` | method, path, status | the success-rate gate |
| `http_request_duration_seconds` | method, path, status_class, 11 buckets around the 500 ms threshold | the p95 gate |
| `app_build_info` | version, environment, pod, fault_mode | Grafana: which build a dip belongs to |

Buckets are chosen around the analysis threshold so `histogram_quantile`
interpolates near the decision rather than extrapolating to `+Inf`. Route labels
use the matched template, or one constant `unmatched`, so a scan for `/{anything}`
cannot flood the TSDB with label values.

## Limitations

- Single uvicorn worker, in-process registry: metrics reset when a pod restarts,
  which is why the analysis reads a 1-minute `rate()` and not a counter.
- No database, so nothing here exercises migrations or connection pooling.
- No authentication: there is no secret for the pipeline to leak, which keeps the
  demo honest but says nothing about secret management beyond "not in git".
- The image is public on GHCR. `docker pull` works without login.

## Verify a release actually happened

```bash
gh run list --workflow ci.yml --limit 5
gh run view <id> --log-failed
gh pr list --repo bouhlel-dev/gitops-config-repo --state merged --limit 5
curl -s -H 'Host: gitops-demo.local' http://127.0.0.1/ | grep -o '"version":"[^"]*"'
```

That last one is the end of the chain: the version string in a live pod is the
commit you pushed.
