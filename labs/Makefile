# ============================================================================
# Acme labs - command surface.  Run `make help` for the tour.
# Every target echoes what it does and is wrapped in a timeout.
# ============================================================================

SHELL := /usr/bin/env bash
.SHELLFLAGS := -euo pipefail -c
.DEFAULT_GOAL := help

COMPOSE := docker compose --env-file .env -f platform/docker-compose.yaml
# Prefer the project venv, fall back to system python (evaluated at run time).
PYRUN := if [ -x .venv/bin/python ]; then PYBIN=.venv/bin/python; else PYBIN=python3; fi; PYTHONPATH=src "$$PYBIN"

.PHONY: help doctor bootstrap up seed verify reset down nuke smoke \
        lab1 lab2 lab3 lab4 data test lint \
        lab2-prep lab2-check lab2-run lab3-prep lab3-check lab3-kill lab3-verify \
        lab4-prep lab4-check sandbox-reset

help: ## Show this help
	@grep -E '^[a-z0-9-]+:.*##' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

doctor: ## Check docker, compose, python/uv, ports, images, .env, disk, memory
	@echo "==> doctor: checking your environment"
	@timeout 120 bash scripts/doctor.sh

bootstrap: ## Create venv + install deps (uv sync --frozen; pip fallback)
	@echo "==> bootstrap: python environment"
	@if command -v uv >/dev/null 2>&1 && [ -f uv.lock ]; then \
	  echo "    using uv (locked)"; \
	  timeout 600 uv venv --allow-existing .venv; \
	  timeout 600 uv sync --frozen; \
	elif command -v uv >/dev/null 2>&1; then \
	  echo "    NOTE: uv.lock not present yet (see lockfile-PENDING.md);"; \
	  echo "    using 'uv pip install -e .[dev]' as an UNLOCKED fallback."; \
	  timeout 600 uv venv --allow-existing .venv; \
	  timeout 600 uv pip install -e ".[dev]"; \
	else \
	  echo "    uv not found - falling back to python3 -m venv + pip -e .[dev]"; \
	  timeout 600 python3 -m venv .venv; \
	  timeout 900 .venv/bin/pip install -e ".[dev]"; \
	fi
	@echo "==> bootstrap done. Activate with: source .venv/bin/activate"

data: ## (Re)generate the deterministic dataset (~5s, byte-identical)
	@echo "==> data: generating labs/data artifacts"
	@timeout 300 python3 data/generate.py >/dev/null
	@echo "    done - see data/manifest.json"

up: ## Start the 3-node cluster + prometheus + grafana; wait for readiness
	@echo "==> up: starting compose stack (pinned images, no 'latest')"
	@test -f .env || { echo "ERROR: labs/.env missing - cp .env.example .env and rotate keys (make doctor)"; exit 1; }
	@timeout 300 $(COMPOSE) up -d --wait --wait-timeout 240 || { \
	  echo "compose --wait failed; recent logs:"; $(COMPOSE) ps; exit 1; }
	@timeout 180 bash scripts/wait-ready.sh 150
	@echo "==> cluster ready: http://localhost:8080 (grafana :3000, prometheus :9090)"

seed: ## Import the Acme dataset (server-side batching, deterministic IDs)
	@echo "==> seed: importing dataset via collection.batch.stream()"
	@$(PYRUN) -c 'import sys' || { echo "python env broken - run: make bootstrap"; exit 1; }
	@timeout 1800 bash -c '$(PYRUN) -m acme.seed'

verify: ## Run the preflight checklist (version, readiness, counts, query, prometheus)
	@echo "==> verify: preflight checklist"
	@timeout 600 bash -c '$(PYRUN) -m acme.verify'

reset: ## Idempotent reset: drop lab collections, re-seed baseline
	@echo "==> reset: teardown + re-seed (safe to run anytime)"
	@timeout 2400 bash -c '$(PYRUN) -m acme.reset'

down: ## Stop the stack, KEEP volumes (data survives)
	@echo "==> down: stopping containers (volumes preserved)"
	@timeout 120 $(COMPOSE) down

nuke: ## Stop the stack and DELETE volumes (asks for confirmation)
	@echo "==> nuke: this deletes ALL lab data volumes."
	@read -r -p "Type 'nuke' to confirm: " ans && [ "$$ans" = "nuke" ] || { echo "aborted."; exit 1; }
	@timeout 120 $(COMPOSE) down -v
	@echo "==> volumes removed. 'make up && make seed' rebuilds from scratch."

smoke: ## End-to-end: up -> seed -> verify -> down
	@echo "==> smoke: full pipeline"
	@$(MAKE) up
	@$(MAKE) seed
	@$(MAKE) verify
	@$(MAKE) down
	@echo "==> smoke: PASS"

test: ## Run offline unit tests (integration tests skip without a cluster)
	@echo "==> test: pytest (unit)"
	@timeout 600 bash -c '$(PYRUN) -m pytest tests -m "not integration" -q'

lint: ## ruff + mypy
	@echo "==> lint: ruff + mypy"
	@timeout 300 ruff check src tests data
	@timeout 600 bash -c 'if [ -x .venv/bin/mypy ]; then .venv/bin/mypy; else mypy; fi'

# ---- lab conveniences -------------------------------------------------------

lab1: ## Lab 1 (paper/workbook) - no cluster needed
	@echo "==> Lab 1 is paper+workbook based: open lab-01-architecture-sizing/README.md"
	@echo "    Workload cards A/B/C are inside; the estimator worksheet is in the participant workbook."

lab2: ## Lab 2 - benchmark & tune (needs cluster + seed)
	@echo "==> Lab 2: benchmark & tune - open lab-02-benchmark-tuning/README.md"
	@$(MAKE) verify
	@echo "    Baseline:   PYTHONPATH=src python -m acme.bench --preset baseline"
	@echo "    Then ONE of: --preset rq8 | ef-sweep | hfresh | filter-strategy"

lab3: ## Lab 3 - controlled failure & recovery (needs cluster + seed)
	@echo "==> Lab 3: failure & recovery - open lab-03-failure-recovery/README.md"
	@$(MAKE) verify
	@timeout 120 bash -c '$(PYRUN) -m acme.chaos status'
	@echo "    Drill:  PYTHONPATH=src python -m acme.chaos kill weaviate-1"

lab4: ## Lab 4 - incident investigation (instructor injects the incident)
	@echo "==> Lab 4: incident investigation - open lab-04-observability-incident/README.md"
	@$(MAKE) verify
	@echo "    Dashboards: http://localhost:3000  Prometheus: http://localhost:9090"
	@echo "    (The incident is injected by the instructor - no peeking in labs/instructor/)"

# ---- instructor run-of-show state targets (S0-S3 sandbox states) -----------
# Prep/check pairs used fleet-wide during breaks; see course/facilitator-run-of-show.md.

lab2-prep: ## S1: baseline dataset seeded, harness ready (idempotent)
	@echo "==> lab2-prep: ensuring S1 (baseline seeded)"
	@$(MAKE) reset

lab2-check: ## Verify S1 (green = ready for Lab 2)
	@$(MAKE) verify

lab2-run: ## Run the Lab 2 baseline benchmark preset
	@echo "==> lab2-run: baseline preset (then choose ONE change preset)"
	@timeout 900 bash -c '$(PYRUN) -m acme.bench --preset baseline'

lab3-prep: ## S2: replicated collection preloaded, chaos armed but not triggered
	@echo "==> lab3-prep: ensuring S2 (RF=3 baseline, async replication default-on)"
	@$(MAKE) reset
	@timeout 120 bash -c '$(PYRUN) -m acme.chaos status'

lab3-check: ## Verify S2 (cluster green + all nodes running)
	@$(MAKE) verify
	@timeout 120 bash -c '$(PYRUN) -m acme.chaos status'

lab3-kill: ## Lab 3 drill: stop one node (NODE=weaviate-1 by default)
	@echo "==> lab3-kill: stopping $${NODE:-weaviate-1} (labeled simulation - not an AZ outage)"
	@timeout 120 bash -c '$(PYRUN) -m acme.chaos kill $${NODE:-weaviate-1}'

lab3-verify: ## Post-drill: node restored + cluster converged + verify green
	@timeout 300 bash -c '$(PYRUN) -m acme.chaos restore $${NODE:-weaviate-1}'
	@timeout 300 bash -c '$(PYRUN) -m acme.chaos convergence'
	@$(MAKE) verify

lab4-prep: ## S3: inject the Lab 4 incident (instructor console; needs labs/instructor/, absent from participant bundle)
	@if [ -f instructor/incident_injector.py ]; then \
	  echo "==> lab4-prep: injecting incident (instructor console only)"; \
	  timeout 300 bash -c '$(PYRUN) instructor/incident_injector.py inject'; \
	else \
	  echo "lab4-prep is instructor-only: instructor/incident_injector.py is not in the participant bundle."; \
	  exit 1; \
	fi

lab4-check: ## S3 check (instructor console only - output names the fault; never on projector)
	@if [ -f instructor/incident_injector.py ]; then \
	  timeout 120 bash -c '$(PYRUN) instructor/incident_injector.py status'; \
	else \
	  echo "lab4-check is instructor-only."; exit 1; \
	fi

sandbox-reset: ## Full recovery: down -> up -> reseed -> verify (~5 min budget)
	@echo "==> sandbox-reset: full recovery path"
	@$(MAKE) down
	@$(MAKE) up
	@$(MAKE) reset
	@$(MAKE) verify
