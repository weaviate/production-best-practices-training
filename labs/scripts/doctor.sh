#!/usr/bin/env bash
# Acme labs environment doctor. Exits non-zero with remediation hints.
set -euo pipefail

LABS_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FAILURES=0
WARNINGS=0

ok()   { printf '  \033[32mPASS\033[0m  %s\n' "$*"; }
warn() { printf '  \033[33mWARN\033[0m  %s\n' "$*"; WARNINGS=$((WARNINGS+1)); }
bad()  { printf '  \033[31mFAIL\033[0m  %s\n' "$*"; FAILURES=$((FAILURES+1)); }

echo "Acme labs doctor - $(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --- docker ------------------------------------------------------------------
if command -v docker >/dev/null 2>&1; then
  if timeout 10 docker info >/dev/null 2>&1; then
    ok "docker daemon reachable ($(docker --version))"
  else
    bad "docker installed but daemon unreachable - start Docker Desktop / dockerd, or check group membership (usermod -aG docker \$USER)"
  fi
else
  bad "docker not found - install Docker Engine 24+ / Docker Desktop"
fi

# --- compose v2 -----------------------------------------------------------------
if timeout 10 docker compose version >/dev/null 2>&1; then
  ok "docker compose v2 available ($(docker compose version --short 2>/dev/null || echo '?'))"
else
  bad "docker compose v2 missing - it ships with current Docker; upgrade Docker or install the compose plugin"
fi

# --- python / uv ------------------------------------------------------------------
if command -v uv >/dev/null 2>&1; then
  ok "uv available ($(uv --version 2>/dev/null | head -1))"
else
  warn "uv not found - 'make bootstrap' will fall back to python3 -m venv + pip"
fi
PYBIN="$(command -v python3.12 || command -v python3 || true)"
if [ -n "$PYBIN" ]; then
  PYVER="$("$PYBIN" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))')"
  case "$PYVER" in
    3.12.*|3.13.*) ok "python $PYVER at $PYBIN" ;;
    *) warn "python $PYVER found; labs target 3.12 - install python3.12 (pyenv/uv python install 3.12)" ;;
  esac
else
  bad "no python3 found - install Python 3.12"
fi

# --- ports free (or already ours) --------------------------------------------------
PORTS=(8080 8081 8082 50051 50052 50053 9090 3000 2112 2113 2114)
if command -v docker >/dev/null 2>&1 && timeout 10 docker info >/dev/null 2>&1; then
  RUNNING="$(docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null || true)"
else
  RUNNING=""
fi
for p in "${PORTS[@]}"; do
  in_use=0
  if command -v ss >/dev/null 2>&1; then
    ss -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "[:.]${p}\$" && in_use=1 || true
  elif command -v lsof >/dev/null 2>&1; then
    lsof -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1 && in_use=1 || true
  fi
  if [ "$in_use" = 1 ]; then
    if printf '%s' "$RUNNING" | grep -q "acme.*:${p}->"; then
      ok "port ${p} in use by the lab cluster (fine)"
    else
      bad "port ${p} already in use by another process - stop it or change labs/.env + compose ports"
    fi
  else
    ok "port ${p} free"
  fi
done

# --- images present ------------------------------------------------------------------
for img in "cr.weaviate.io/semitechnologies/weaviate:1.38.3" \
           "prom/prometheus:v3.4.1" \
           "grafana/grafana:12.0.1"; do
  if command -v docker >/dev/null 2>&1 && docker image inspect "$img" >/dev/null 2>&1; then
    ok "image cached: $img"
  else
    warn "image not cached: $img - 'make up' will pull it (needs network; pre-provisioned sandboxes have it cached)"
  fi
done

# --- env file ---------------------------------------------------------------------------
if [ -f "$LABS_DIR/.env" ]; then
  if grep -q "change-me" "$LABS_DIR/.env"; then
    bad ".env still contains placeholder keys - edit WEAVIATE_API_KEY_* (any two distinct random strings, e.g. \`openssl rand -hex 24\`)"
  else
    ok ".env present with rotated keys"
  fi
else
  bad ".env missing - run: cp .env.example .env && edit WEAVIATE_API_KEY_*"
fi

# --- dataset ------------------------------------------------------------------------------
if [ -f "$LABS_DIR/data/vectors.npy" ]; then
  ok "dataset artifacts present (labs/data)"
else
  warn "dataset not generated - run: python3 data/generate.py (deterministic, ~5s)"
fi

# --- disk / memory -----------------------------------------------------------------------------
AVAIL_GB="$(df -Pk "$LABS_DIR" | awk 'NR==2 {printf "%d", $4/1024/1024}')"
if [ "${AVAIL_GB:-0}" -ge 10 ]; then
  ok "disk: ${AVAIL_GB} GiB free (need >= 10)"
else
  bad "disk: only ${AVAIL_GB} GiB free - free up space (>= 10 GiB required; 'make nuke' reclaims lab volumes)"
fi
if [ -r /proc/meminfo ]; then
  MEM_GB="$(awk '/MemTotal/ {printf "%d", $2/1024/1024}' /proc/meminfo)"
elif command -v sysctl >/dev/null 2>&1; then
  MEM_GB="$(( $(sysctl -n hw.memsize 2>/dev/null || echo 0) / 1024 / 1024 / 1024 ))"
else
  MEM_GB=0
fi
if [ "${MEM_GB:-0}" -ge 8 ]; then
  ok "memory: ${MEM_GB} GiB total (need >= 8)"
elif [ "${MEM_GB:-0}" -ge 6 ]; then
  warn "memory: ${MEM_GB} GiB total - labs run but tight; close other workloads"
else
  bad "memory: ${MEM_GB} GiB total - 8 GiB recommended for the 3-node cluster + tooling"
fi

echo
if [ "$FAILURES" -gt 0 ]; then
  echo "doctor: $FAILURES failure(s), $WARNINGS warning(s) - fix FAIL items above, then re-run 'make doctor'."
  exit 1
fi
echo "doctor: all checks passed ($WARNINGS warning(s))."
