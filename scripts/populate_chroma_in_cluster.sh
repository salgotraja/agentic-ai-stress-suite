#!/usr/bin/env bash
#
# populate_chroma_in_cluster.sh: seed the in-cluster Chroma PVC with the
# `naive_rag` collection used by Article 8.
#
# Strategy: open a kubectl port-forward to chroma-service:8000 on a local
# port, run scripts/populate_chroma.py against http://localhost:<port>, then
# tear the port-forward down on exit. We use port 18000 (not 8000) to avoid
# clashing with the host-side docker-compose Chroma which binds 8000 and may
# still be running while we work in-cluster.
#
# Idempotent: populate_chroma.py exits 0 without re-embedding if the
# collection already has rows. Re-run anytime; cheap.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

LOCAL_PORT="${LOCAL_PORT:-18000}"
COLLECTION="${COLLECTION:-naive_rag}"
NAMESPACE="${NAMESPACE:-default}"

# Pre-flight: cluster reachable and chroma-service exists. Failing here gives
# a much clearer error than letting kubectl port-forward silently exit.
if ! kubectl get svc chroma-service -n "$NAMESPACE" >/dev/null 2>&1; then
  echo "ERROR: Service ${NAMESPACE}/chroma-service not found." >&2
  echo "Apply src/ops/deployment/k8s/chroma.yaml first." >&2
  exit 1
fi

kubectl wait --for=condition=Ready pod -l app=chroma -n "$NAMESPACE" --timeout=60s

# Background port-forward. Bound to 127.0.0.1 only; never expose this beyond
# loopback even briefly. Stash the PID so the trap can clean up.
echo "Port-forwarding chroma-service:8000 -> localhost:${LOCAL_PORT} ..."
kubectl port-forward -n "$NAMESPACE" svc/chroma-service "${LOCAL_PORT}:8000" >/tmp/populate_chroma_pf.log 2>&1 &
PF_PID=$!
trap 'kill "$PF_PID" 2>/dev/null || true' EXIT

# Wait until the local port answers HTTP. kubectl port-forward prints
# "Forwarding from..." before the local listener is actually accepting; a
# polled curl is the only reliable readiness signal.
for i in $(seq 1 30); do
  if curl -sf "http://localhost:${LOCAL_PORT}/api/v2/heartbeat" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
  if [ "$i" -eq 30 ]; then
    echo "ERROR: port-forward did not become ready within 15s. Logs:" >&2
    cat /tmp/populate_chroma_pf.log >&2
    exit 1
  fi
done

# Run the populator. CHROMA_URL is read by Pydantic Settings; overriding it
# here keeps the script unaware of localhost vs in-cluster vs compose.
cd "$PROJECT_ROOT"
CHROMA_URL="http://localhost:${LOCAL_PORT}" \
  uv run python scripts/populate_chroma.py --collection "$COLLECTION"

echo "Populate complete. Verifying via /api/v2/heartbeat:"
curl -s "http://localhost:${LOCAL_PORT}/api/v2/heartbeat"
echo
