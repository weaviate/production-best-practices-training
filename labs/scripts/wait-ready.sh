#!/usr/bin/env bash
# Poll /v1/.well-known/ready on all lab nodes until 200 or timeout.
set -euo pipefail

TIMEOUT_SECS="${1:-120}"
PORTS=(8080 8081 8082)
HOST="${WEAVIATE_HTTP_HOST:-localhost}"

deadline=$(( $(date +%s) + TIMEOUT_SECS ))
echo "Waiting for readiness on ${HOST}:${PORTS[*]} (max ${TIMEOUT_SECS}s)…"
while true; do
  ready=0
  for p in "${PORTS[@]}"; do
    code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://${HOST}:${p}/v1/.well-known/ready" || echo 000)"
    [ "$code" = "200" ] && ready=$((ready+1))
  done
  if [ "$ready" -eq "${#PORTS[@]}" ]; then
    echo "All ${#PORTS[@]} nodes READY."
    exit 0
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    echo "ERROR: only ${ready}/${#PORTS[@]} nodes ready after ${TIMEOUT_SECS}s." >&2
    echo "Inspect: docker compose -f platform/docker-compose.yaml ps && docker compose -f platform/docker-compose.yaml logs --tail 50" >&2
    exit 1
  fi
  sleep 3
done
