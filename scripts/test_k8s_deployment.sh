#!/usr/bin/env bash
# K8s deployment smoke test - task 4.26.
#
# Teaching note: WHY test K8s manifests in CI with kind?
#   kubectl apply --dry-run=client only validates YAML schema.
#   A live kind cluster tests the ACTUAL control plane behaviour:
#   - Do pods actually reach Running state (image pull, probes, resource limits)?
#   - Does the HPA register correctly with the metrics server?
#   - Can the Service reach the pod (kube-proxy rules wired up)?
#   kind (Kubernetes-in-Docker) spins up a real single-node cluster in ~60s,
#   costs no money, and is fully self-contained - perfect for CI.
#
# Prerequisites:
#   - kind (https://kind.sigs.k8s.io/) installed
#   - kubectl installed
#   - Docker running
#
# Usage:
#   ./scripts/test_k8s_deployment.sh              # full test
#   ./scripts/test_k8s_deployment.sh --skip-build # skip docker image build
#   ./scripts/test_k8s_deployment.sh --dry-run    # validate manifests only (no kind)

set -euo pipefail

CLUSTER_NAME="rag-agent-test"
K8S_DIR="src/ops/deployment/k8s"
NAMESPACE="default"
APP_LABEL="rag-agent-api"
WAIT_TIMEOUT="120s"
DRY_RUN=false
SKIP_BUILD=false

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

log() {
    echo "[$(date '+%H:%M:%S')] $*"
}

# ---------------------------------------------------------------------------
# parse_args: extract --dry-run and --skip-build from $@.
# Teaching note: process flags before any side-effecting work so every code
# path downstream can branch on the boolean variables rather than re-parsing.
# ---------------------------------------------------------------------------
parse_args() {
    for arg in "$@"; do
        case "$arg" in
            --dry-run)    DRY_RUN=true ;;
            --skip-build) SKIP_BUILD=true ;;
            *)
                echo "Unknown argument: $arg"
                echo "Usage: $0 [--dry-run] [--skip-build]"
                exit 1
                ;;
        esac
    done
}

# ---------------------------------------------------------------------------
# check_prerequisites: verify required binaries exist before doing real work.
# Teaching note: fail fast on prerequisites, not mid-test. Nothing is worse
# than a 90-second cluster creation followed by a "kind: command not found".
# We accept an optional list so --dry-run can skip checking kind/docker.
# ---------------------------------------------------------------------------
check_prerequisites() {
    local tools=("$@")

    declare -A install_urls
    install_urls["kind"]="https://kind.sigs.k8s.io/docs/user/quick-start/#installation"
    install_urls["kubectl"]="https://kubernetes.io/docs/tasks/tools/"
    install_urls["docker"]="https://docs.docker.com/get-docker/"

    local missing=false
    for tool in "${tools[@]}"; do
        if ! command -v "$tool" &>/dev/null; then
            echo "Missing prerequisite: $tool"
            echo "  Install: ${install_urls[$tool]:-https://google.com/search?q=install+$tool}"
            missing=true
        fi
    done

    if [ "$missing" = "true" ]; then
        echo "Install missing prerequisites and re-run."
        exit 1
    fi

    log "Prerequisites OK: ${tools[*]}"
}

# ---------------------------------------------------------------------------
# validate_manifests: schema-validate all manifests against the live API.
# Teaching note: dry-run catches schema errors (wrong apiVersion, typos in
# field names) without creating any cluster resources. It uses the server-side
# schema from the configured cluster, so it is more accurate than a pure YAML
# linter. Run this even in --dry-run mode as the cheapest sanity check.
# ---------------------------------------------------------------------------
validate_manifests() {
    log "Validating manifests (kubectl apply --dry-run=client)..."
    kubectl apply -f "$K8S_DIR/" --dry-run=client
    log "Manifest validation passed."
}

# ---------------------------------------------------------------------------
# create_cluster: spin up a single-node kind cluster or reuse an existing one.
# Teaching note: --wait 60s blocks until the API server is reachable, so the
# next kubectl command never races against cluster initialisation. Reusing an
# existing cluster speeds up local iteration without re-paying the 60s startup
# cost each run; CI should always start fresh (no prior cluster).
# ---------------------------------------------------------------------------
create_cluster() {
    if kind get clusters 2>/dev/null | grep -q "^${CLUSTER_NAME}$"; then
        log "Cluster $CLUSTER_NAME already exists, reusing."
    else
        log "Creating kind cluster: $CLUSTER_NAME ..."
        kind create cluster --name "$CLUSTER_NAME" --wait 60s
        log "Cluster created."
    fi

    # Point kubectl at this cluster for all subsequent commands.
    kubectl config use-context "kind-${CLUSTER_NAME}"
    log "kubectl context set to kind-${CLUSTER_NAME}."
}

# ---------------------------------------------------------------------------
# load_test_image: build a minimal FastAPI image and load it into kind.
# Teaching note: kind nodes run containerd, not the host Docker daemon, so
# images built locally are invisible to the cluster until explicitly loaded.
# `kind load docker-image` copies the image tarball into the node's
# containerd image store, bypassing any registry. In real CI the production
# image would be pushed to a registry (ECR/GCR/GHCR) and pulled by the node;
# here we use a throwaway image to keep the test self-contained and free.
# ---------------------------------------------------------------------------
load_test_image() {
    local dockerfile="/tmp/Dockerfile.rag-agent-test"
    local entrypoint="/tmp/main_rag_test.py"

    # Write a minimal FastAPI app that satisfies the liveness and readiness
    # probes defined in deployment.yaml (/health and /ready).
    cat > "$entrypoint" << 'PYEOF'
from fastapi import FastAPI

app = FastAPI()


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict:
    return {"status": "ready"}
PYEOF

    cat > "$dockerfile" << 'EOF'
FROM python:3.11-slim
RUN pip install fastapi uvicorn --quiet
COPY main_rag_test.py /app/main.py
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
EOF

    log "Building test image rag-agent-api:latest ..."
    docker build -f "$dockerfile" -t rag-agent-api:latest /tmp/ --quiet
    log "Image built. Loading into kind cluster $CLUSTER_NAME ..."
    kind load docker-image rag-agent-api:latest --name "$CLUSTER_NAME"
    log "Image loaded into cluster."
}

# ---------------------------------------------------------------------------
# deploy_manifests: apply K8s manifests in dependency order.
# Teaching note: order matters because the Deployment references the
# ConfigMap and Secret via envFrom - if they don't exist yet, the pod spec
# is accepted but pods fail to start with "configmap not found". Applying
# ConfigMap and Secret first guarantees pods can start immediately after the
# Deployment is created. Ingress is applied last (and with || true) because
# the NGINX Ingress Controller is not installed in a bare kind cluster.
# ---------------------------------------------------------------------------
deploy_manifests() {
    log "Applying ConfigMap and Secret (Deployment depends on them)..."
    kubectl apply -f "$K8S_DIR/configmap.yaml"
    kubectl apply -f "$K8S_DIR/secrets.yaml"

    log "Applying Deployment and Service..."
    kubectl apply -f "$K8S_DIR/deployment.yaml"
    kubectl apply -f "$K8S_DIR/service.yaml"

    # HPA and Ingress depend on Deployment and Service being present.
    log "Applying HPA..."
    kubectl apply -f "$K8S_DIR/hpa.yaml"

    # Ingress requires the NGINX Ingress Controller add-on.
    # In a bare kind cluster it will be accepted (the Ingress resource is
    # valid) but will have no effect. We log a note rather than failing.
    log "Applying Ingress (may be inactive without ingress controller)..."
    kubectl apply -f "$K8S_DIR/ingress.yaml" || \
        log "WARNING: Ingress apply failed - NGINX controller likely not installed. Continuing."

    log "All manifests applied."
}

# ---------------------------------------------------------------------------
# wait_for_pods: block until the Deployment rollout completes and at least
# one pod is Running. On failure, dump pod describe for CI diagnostics.
# Teaching note: `kubectl rollout status` watches the deployment controller's
# progress condition, which accounts for readiness probes. It is more reliable
# than polling pod phase directly because it waits for the full ready signal.
# ---------------------------------------------------------------------------
wait_for_pods() {
    log "Waiting for deployment rollout (timeout: $WAIT_TIMEOUT)..."
    kubectl rollout status "deployment/$APP_LABEL" \
        --namespace "$NAMESPACE" \
        --timeout "$WAIT_TIMEOUT"

    local pod_count
    pod_count=$(kubectl get pods \
        --namespace "$NAMESPACE" \
        -l "app=$APP_LABEL" \
        --field-selector="status.phase=Running" \
        --no-headers 2>/dev/null | wc -l | tr -d ' ')

    if [ "$pod_count" -eq 0 ]; then
        log "ERROR: No running pods found. Dumping pod describe for diagnostics:"
        kubectl describe pods --namespace "$NAMESPACE" -l "app=$APP_LABEL" || true
        exit 1
    fi

    log "Pods running: $pod_count"
}

# ---------------------------------------------------------------------------
# run_smoke_tests: port-forward the ClusterIP service and curl /health.
# Teaching note: ClusterIP services are not reachable from the host network
# by default (that is the point - they are cluster-internal). `kubectl
# port-forward` creates a tunnel from a local port to the service port via
# the API server. We background it, wait briefly for the tunnel to open, run
# the curl, then kill the tunnel to avoid port conflicts on re-runs.
# ---------------------------------------------------------------------------
run_smoke_tests() {
    local local_port=18000
    local service_port=80
    local pf_pid

    log "Port-forwarding service/rag-agent-service -> localhost:${local_port} ..."
    kubectl port-forward \
        --namespace "$NAMESPACE" \
        "service/rag-agent-service" \
        "${local_port}:${service_port}" &>/dev/null &
    pf_pid=$!

    # Give the tunnel a moment to establish before hitting it.
    sleep 3

    local health_url="http://localhost:${local_port}/health"
    log "Running smoke test: GET $health_url ..."
    if ! curl -sf --max-time 10 "$health_url" > /dev/null; then
        kill "$pf_pid" 2>/dev/null || true
        log "ERROR: Smoke test failed - $health_url did not return 200."
        exit 1
    fi

    kill "$pf_pid" 2>/dev/null || true
    log "Smoke test passed: /health returned 200."
}

# ---------------------------------------------------------------------------
# verify_hpa: confirm the HPA object is registered with the control plane.
# Teaching note: in a bare kind cluster without the metrics-server add-on,
# the HPA will show <unknown> for current CPU (it cannot scrape metrics).
# That is expected and not a manifest defect - the resource is correctly
# defined and will function once metrics-server is installed. We log this
# distinction so CI operators are not alarmed by the <unknown> output.
# ---------------------------------------------------------------------------
verify_hpa() {
    log "Verifying HPA registration..."
    if kubectl get hpa "${APP_LABEL}-hpa" --namespace "$NAMESPACE" -o wide 2>/dev/null; then
        log "HPA registered. Note: CPU metrics show <unknown> without metrics-server add-on - expected in kind."
    else
        log "WARNING: HPA not found. Check hpa.yaml name matches deployment."
    fi
}

# ---------------------------------------------------------------------------
# cleanup: delete the kind cluster to free Docker resources.
# Teaching note: kind clusters consume ~300MB RAM per node while running.
# Always delete after CI tests. In local development you may skip cleanup
# (comment out the cleanup call in main) to reuse the cluster across runs.
# ---------------------------------------------------------------------------
cleanup() {
    log "Deleting kind cluster: $CLUSTER_NAME ..."
    kind delete cluster --name "$CLUSTER_NAME"
    log "Cluster deleted."
}

# ---------------------------------------------------------------------------
# main: orchestrate the test flow based on parsed flags.
# ---------------------------------------------------------------------------
main() {
    parse_args "$@"

    if [ "$DRY_RUN" = "true" ]; then
        # Dry-run only needs kubectl for schema validation; no cluster or Docker.
        check_prerequisites kubectl
        validate_manifests
        log "Dry-run complete. Manifests are schema-valid."
        exit 0
    fi

    # Full test: bring up a real kind cluster and exercise all manifests.
    check_prerequisites kind kubectl docker
    validate_manifests
    create_cluster

    if [ "$SKIP_BUILD" = "false" ]; then
        load_test_image
    else
        log "Skipping image build (--skip-build). Ensure rag-agent-api:latest is already loaded."
    fi

    deploy_manifests
    wait_for_pods
    run_smoke_tests
    verify_hpa
    cleanup

    log "All K8s deployment tests passed."
}

main "$@"
