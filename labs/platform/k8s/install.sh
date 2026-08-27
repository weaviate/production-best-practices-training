#!/usr/bin/env bash
# ============================================================================
# Acme labs - kind + weaviate-helm install (BYOC learning fallback).
# Requires network access (image pulls + helm repo). See k8s/README.md for
# what this does and does NOT teach you about multi-AZ.
# ============================================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLUSTER_NAME="acme"
CHART_VERSION="17.8.3"          # pinned - VERSION_MATRIX.md
IMAGE_TAG="1.38.3"              # pinned - overrides chart appVersion 1.38.2 (C-6)
NAMESPACE="weaviate"
HELM_TIMEOUT="10m"
READY_TIMEOUT_SECS=600

log()  { printf '\033[1;36m[install]\033[0m %s\n' "$*"; }
fail() { printf '\033[1;31m[install] ERROR:\033[0m %s\n' "$*" >&2; exit 1; }

# --- prerequisites -----------------------------------------------------------
for tool in kind kubectl helm; do
  command -v "$tool" >/dev/null 2>&1 || fail "$tool not found. Install it first (see k8s/README.md)."
done

: "${WEAVIATE_API_KEY_ROOT:?Set WEAVIATE_API_KEY_ROOT (no placeholder keys - rotate first)}"
: "${WEAVIATE_API_KEY_READONLY:?Set WEAVIATE_API_KEY_READONLY}"
case "$WEAVIATE_API_KEY_ROOT" in change-me*) fail "WEAVIATE_API_KEY_ROOT is still a placeholder";; esac

# --- kind cluster --------------------------------------------------------------
if kind get clusters 2>/dev/null | grep -qx "$CLUSTER_NAME"; then
  log "kind cluster '$CLUSTER_NAME' already exists - reusing."
else
  log "Creating kind cluster '$CLUSTER_NAME' (3 workers, node image kindest/node:v1.31.9)…"
  timeout 600 kind create cluster --config "$SCRIPT_DIR/kind-cluster.yaml" --wait 5m
fi
kubectl config use-context "kind-$CLUSTER_NAME" >/dev/null

# --- helm repo -----------------------------------------------------------------
log "Adding weaviate helm repo…"
timeout 120 helm repo add weaviate https://weaviate.github.io/weaviate-helm >/dev/null
timeout 120 helm repo update weaviate >/dev/null

# --- secrets (never in values files) ---------------------------------------------
log "Creating namespace + API-key secret…"
kubectl create namespace "$NAMESPACE" --dry-run=client -o yaml | kubectl apply -f -
kubectl -n "$NAMESPACE" create secret generic weaviate-api-keys \
  --from-literal=AUTHENTICATION_APIKEY_ALLOWED_KEYS="${WEAVIATE_API_KEY_ROOT},${WEAVIATE_API_KEY_READONLY}" \
  --dry-run=client -o yaml | kubectl apply -f -

# --- install ----------------------------------------------------------------------
log "Installing weaviate chart ${CHART_VERSION} with image.tag=${IMAGE_TAG} (C-6 override)…"
timeout 900 helm upgrade --install weaviate weaviate/weaviate \
  --namespace "$NAMESPACE" \
  --version "$CHART_VERSION" \
  --values "$SCRIPT_DIR/values-weaviate.yaml" \
  --set image.tag="$IMAGE_TAG" \
  --timeout "$HELM_TIMEOUT" \
  --wait

# --- health wait loop -----------------------------------------------------------------
log "Waiting for 3/3 ready weaviate pods (max ${READY_TIMEOUT_SECS}s)…"
deadline=$(( $(date +%s) + READY_TIMEOUT_SECS ))
while true; do
  ready="$(kubectl -n "$NAMESPACE" get statefulset weaviate -o jsonpath='{.status.readyReplicas}' 2>/dev/null || echo 0)"
  ready="${ready:-0}"
  if [ "$ready" = "3" ]; then
    log "All 3 replicas ready."
    break
  fi
  if [ "$(date +%s)" -ge "$deadline" ]; then
    kubectl -n "$NAMESPACE" get pods -o wide || true
    fail "cluster not ready after ${READY_TIMEOUT_SECS}s - inspect pods above."
  fi
  log "ready replicas: ${ready}/3 - waiting…"
  sleep 10
done

log "Port-forward to use the v4 client (HTTP 8080 + gRPC 50051):"
log "  kubectl -n $NAMESPACE port-forward svc/weaviate 8080:80 &"
log "  kubectl -n $NAMESPACE port-forward svc/weaviate-grpc 50051:50051 &"
log "Done."
