<img alt="Weaviate logo" src="https://weaviate.io/img/site/weaviate-logo-light.png" width="120" align="right" />

# Acme Labs — hands-on environment

[![Weaviate](https://img.shields.io/badge/Weaviate-v1.38.3-61BD73)](../VERSION_MATRIX.md)
[![Python](https://img.shields.io/badge/python-3.12-130C49)](pyproject.toml)
[![Cluster](https://img.shields.io/badge/cluster-3--node_RAFT-130C49)](platform/docker-compose.yaml)

Lab environment for **Advanced: Production Best Practices with Weaviate**.
Pinned baseline (never `latest`; see `../VERSION_MATRIX.md`): Weaviate
**1.38.3**, weaviate-client **4.22.0**, Prometheus v3.4.1, Grafana 12.0.1,
Python 3.12, helm chart 17.8.3 (BYOC reference only).

## Environment overview

One `docker compose` stack (`platform/docker-compose.yaml`):

* **weaviate-0/1/2** — a real 3-voter RAFT cluster, replication factor 3,
  API-key auth + RBAC (anonymous OFF), Prometheus metrics on, async
  indexing on, replica movement enabled, filesystem backups on a shared
  volume, healthchecks on `/v1/.well-known/ready`, resource-limited.
* **prometheus** — scrapes all 3 nodes every 15s.
* **grafana** — provisioned datasource + course dashboards
  (`operations/dashboards/`, mounted read-only). Login `admin` /
  `acme-lab` (lab-only, holds no secrets).

The Python harness lives in `src/acme/` (config, client factory, schema,
seed, verify, reset, bench, chaos). Dataset: 50k synthetic objects + exact
ground truth in `data/` (see `data/README.md` for provenance).

## Canonical path vs laptop fallback

**Canonical (live delivery):** pre-provisioned sandboxes already have the
images cached and `make doctor` green. You only run the command surface
below. The kind/Helm path in `platform/k8s/` is a self-study reference —
NOT used in class.

**Laptop fallback requirements** (if you must run locally):

| Platform | Notes |
|---|---|
| macOS (Apple Silicon & Intel) | Docker Desktop ≥ 4.30, **8 GB+ RAM allocated to Docker** (Settings → Resources), 15 GB free disk. Images are multi-arch. |
| Linux | Docker Engine 24+ with compose v2 plugin; user in `docker` group; 8 GB RAM, 15 GB disk. |
| Windows | **WSL2 only** (Ubuntu 22.04+), Docker Desktop with WSL2 backend. Clone the repo INSIDE the WSL filesystem (`~/...`, not `/mnt/c/...`) or volume I/O will be painfully slow. 8 GB+ for the WSL VM. |

Then: `make doctor` and follow its remediation hints.

## Command surface

| Command | What it does |
|---|---|
| `make doctor` | Environment checks (docker, ports, images, .env, disk/mem) with fix hints |
| `make bootstrap` | `uv venv` + `uv sync --frozen` (pip fallback with warning) |
| `make data` | Regenerate the deterministic dataset (~5 s, byte-identical) |
| `make up` | Start the stack, wait until 3/3 nodes READY |
| `make seed` | Import dataset via **server-side batching** (`batch.stream()`), deterministic UUIDs, fails visibly on any rejected object |
| `make verify` | 7-point preflight (version pin, readiness, health, queue drained, counts, sample query, prometheus) |
| `make reset` | Idempotent: drop lab collections, re-seed baseline |
| `make down` | Stop containers, KEEP volumes |
| `make nuke` | Stop + DELETE volumes (asks for confirmation) |
| `make smoke` | End-to-end: up → seed → verify → down |
| `make test` / `make lint` | Offline unit tests / ruff + mypy |
| `make lab1..lab4` | Per-lab entry points (verify + pointers) |

## First-time setup

```bash
cp .env.example .env          # then ROTATE both WEAVIATE_API_KEY_* values
make doctor && make bootstrap && make up && make seed && make verify
```

### Auth model

Static API keys (from `.env`) map 1:1 to users: `root-user` (RBAC built-in
`root`) and `readonly-user`. RBAC has only two built-ins (`root`, `viewer` —
there is no built-in `admin`); assign `viewer` to `readonly-user` once per
cluster with the root key:

```python
with connect() as client:                      # acme.client.connect
    client.users.db.assign_roles(user_id="readonly-user", role_names=["viewer"])
```

## What is SIMULATED vs REAL

| Real | Simulated / not real |
|---|---|
| 3-voter RAFT metadata plane, quorum math | **Multi-AZ**: all nodes share ONE host, disk, kernel, power cord |
| Replication factor 3, ONE/QUORUM/ALL semantics, async replication + read repair | "Node failure" = `docker compose stop` (clean-ish stop, not a kernel panic or network partition) |
| Auth (keys + RBAC), metrics, slow-query log, backups API | `backup-filesystem` works here only because of a shared volume; docs call it single-node-only — production uses S3/GCS/Azure |
| Server-side batching backpressure | Latency numbers: single-host contention ≠ production network/scale |
| Lab 4 incident signals (queue depth, tiny-batch pressure) | The incident itself is injected by a script, and dataset scale is 50k vs Acme's fictional 40M |

Every lab README repeats the boundary that matters for that lab. Conclusions
about AZ resilience or absolute performance DO NOT transfer; mechanisms,
metrics, and decision methods DO.

## Troubleshooting quick table

| Symptom | Likely cause | Fix |
|---|---|---|
| `make up` fails instantly | `.env` missing / placeholder keys | `cp .env.example .env`, rotate keys, `make doctor` |
| Node never READY | low memory; stale volume from older version | `docker stats`; `make nuke` then `make up` |
| `WeaviateStartUpError` from python | cluster down or wrong ports | `make up`; check `.env` ports vs `docker compose ps` |
| 401 Unauthorized | key mismatch between `.env` and running containers | `make down && make up` (compose re-reads `.env`) |
| gRPC health check fails at connect | port 50051 blocked/occupied | `make doctor` (port checks); VPN/proxy interference |
| verify: "index queue drained" FAIL | async indexing still catching up after seed | wait, re-run `make verify` |
| verify: counts mismatch | interrupted seed | `make reset` (idempotent, safe) |
| Prometheus target down | a node is stopped (Lab 3 leftovers) | `python -m acme.chaos status` then `restore` |
| Grafana empty | dashboards mount or provisioning not loaded | check the `../../operations/dashboards` volume mount, then restart grafana (`docker compose restart grafana`); live-render validation tracked in PENDING_VALIDATION #9 |

## Safety & cleanup

* `make reset` is always safe — it only touches `Acme*` collections and
  the incident scratch space.
* `make down` preserves data; `make nuke` destroys volumes after explicit
  confirmation.
* Chaos tooling refuses to take down a second node (quorum loss) without an
  explicit `--allow-quorum-loss`.

## No-secrets policy

No real secrets exist anywhere in this repo. `.env.example` ships
`change-me-*` placeholders; the loader and `make doctor` refuse placeholder
keys; `.env` is gitignored; compose reads keys only from `.env`; the k8s
path uses a Secret created out-of-band. If you find a real credential in a
commit, rotate it and file it as an incident.

## Dataset provenance

Fully synthetic, seeded, license-clean, byte-reproducible: `data/README.md`.

## Labs

| Lab | Timebox | Needs cluster? |
|---|---|---|
| `lab-01-architecture-sizing/` | 30 min | No (paper + workbook) |
| `lab-02-benchmark-tuning/` | 40 min | Yes |
| `lab-03-failure-recovery/` | 35 min | Yes |
| `lab-04-observability-incident/` | 40 min | Yes (instructor injects incident) |
| `capstone/` | 18 min in-class | Optional (evidence reuse) |
