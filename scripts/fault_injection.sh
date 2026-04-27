#!/usr/bin/env bash
# Fault injection scenarios for chaos engineering - task 4.28.
#
# Teaching note: WHY chaos engineering?
#   Production systems fail in ways integration tests never catch:
#   - A vector DB restart takes 30s; can the app serve cached results?
#   - Network congestion spikes to 500ms; does the agent time out gracefully?
#   - Memory pressure causes OOM kills; do pods restart cleanly?
#   Chaos engineering tests the RECOVERY path, not just the happy path.
#
# Teaching note: WHY inject faults in staging, not production?
#   Staging mirrors production topology without user impact.
#   Netflix's Chaos Monkey runs in production; most teams shouldn't.
#   Start with staging to calibrate blast radius before targeting prod.
#
# Usage:
#   ./scripts/fault_injection.sh --scenario db_failure
#   ./scripts/fault_injection.sh --scenario network_latency
#   ./scripts/fault_injection.sh --scenario memory_exhaustion
#   ./scripts/fault_injection.sh --scenario all
#
# Prerequisites: docker compose stack running (./scripts/start_dev_stack.sh)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/infra/docker-compose.yml"

APP_URL="${APP_URL:-http://localhost:8000}"
RECOVERY_TIMEOUT="${RECOVERY_TIMEOUT:-60}"  # seconds to wait for recovery

# Colour helpers: use tput when a real terminal is attached; fall back to plain text.
# WHY tput over hardcoded ANSI: tput is POSIX, handles terminal capability differences,
# and degrades gracefully (outputs empty string) when stdout is redirected to a file.
if [ -t 1 ] && command -v tput &>/dev/null; then
    RED="$(tput setaf 1)"
    GREEN="$(tput setaf 2)"
    YELLOW="$(tput setaf 3)"
    CYAN="$(tput setaf 6)"
    BOLD="$(tput bold)"
    RESET="$(tput sgr0)"
else
    RED=""
    GREEN=""
    YELLOW=""
    CYAN=""
    BOLD=""
    RESET=""
fi

log_info()    { echo "${CYAN}[INFO]${RESET}  $*"; }
log_ok()      { echo "${GREEN}[OK]${RESET}    $*"; }
log_warn()    { echo "${YELLOW}[WARN]${RESET}  $*"; }
log_error()   { echo "${RED}[ERROR]${RESET} $*" >&2; }
log_section() { echo ""; echo "${BOLD}=== $* ===${RESET}"; echo ""; }

# scenario_db_failure: stop Chroma, measure recovery time, restart it.
#
# Teaching note: Vector DB restart is the most common production incident.
#   Cold-start: Chroma loads HNSW index from disk on startup (10-30s).
#   During restart: cached responses should still serve from Redis L1/L2.
#   Recovery metric: time from container restart to first successful /api/v1/heartbeat.
#
#   What to watch for during this scenario:
#   - Does the app return 503 or serve stale-but-valid cache hits?
#   - How long does the HNSW index reload take at your corpus size?
#   - Are retry budgets in llm_client.py correctly sized for this window?
scenario_db_failure() {
    log_section "Scenario: DB Failure (Chroma restart)"

    log_info "Stopping Chroma container to simulate vector DB outage..."
    docker compose -f "$COMPOSE_FILE" stop chroma

    local start_ns
    start_ns="$(date +%s%N)"

    log_info "Chroma is down. Testing app resilience (polling ${APP_URL}/api/v1/heartbeat)..."
    log_warn "Expect HTTP errors here - that is the point. Redis cache should absorb reads."

    local elapsed=0
    local poll_interval=2
    local app_responding=false

    # Poll the Chroma heartbeat endpoint to measure downtime window.
    # We poll the Chroma port directly (8000) - this is the heartbeat, not an app endpoint.
    while [ "$elapsed" -lt "$RECOVERY_TIMEOUT" ]; do
        local now_ns
        now_ns="$(date +%s%N)"
        elapsed=$(( (now_ns - start_ns) / 1000000000 ))

        if curl --silent --fail --max-time 2 "http://localhost:8000/api/v1/heartbeat" &>/dev/null; then
            app_responding=true
            break
        fi
        log_info "  [${elapsed}s elapsed] Chroma not yet responsive - restarting now if not already done..."
        sleep "$poll_interval"
    done

    log_info "Restarting Chroma container..."
    docker compose -f "$COMPOSE_FILE" start chroma

    log_info "Waiting for Chroma to pass health check after restart..."
    local recovery_start_ns
    recovery_start_ns="$(date +%s%N)"
    local recovered=false

    while true; do
        local now_ns
        now_ns="$(date +%s%N)"
        local wait_elapsed=$(( (now_ns - recovery_start_ns) / 1000000000 ))

        if [ "$wait_elapsed" -ge "$RECOVERY_TIMEOUT" ]; then
            log_error "Chroma did not recover within ${RECOVERY_TIMEOUT}s. Check container logs."
            log_error "  docker compose -f $COMPOSE_FILE logs chroma"
            return 1
        fi

        if curl --silent --fail --max-time 2 "http://localhost:8000/api/v1/heartbeat" &>/dev/null; then
            recovered=true
            break
        fi
        log_info "  [${wait_elapsed}s] Waiting for Chroma recovery..."
        sleep "$poll_interval"
    done

    local end_ns
    end_ns="$(date +%s%N)"
    local total_elapsed=$(( (end_ns - start_ns) / 1000000000 ))

    log_ok "Chroma recovered successfully."
    log_ok "Recovery time: ${total_elapsed}s (stop → healthy again)"
    log_info "Interpret results:"
    log_info "  - If recovery > 30s: HNSW index reload is the bottleneck; pre-warm on startup."
    log_info "  - If app served errors: Redis cache miss - check cache TTL and warming strategy."
    log_info "  - Target recovery SLA: <60s for dev stack, <30s for production."
}

# scenario_network_latency: inject 200ms artificial latency via tc on Linux.
#
# Teaching note: WHY simulate network latency?
#   LLM API calls in production cross the internet (50-300ms baseline).
#   Adding 200ms of artificial latency tests whether timeout budgets,
#   retry logic, and user-facing SLAs hold under realistic conditions.
#   'tc' (traffic control) on Linux injects latency at the kernel level -
#   all sockets on the interface are affected, matching a real network event.
#
#   macOS alternative: Network Link Conditioner (System Preferences > Developer).
#   Not scriptable from bash; must be configured manually in the GUI.
#
#   What to watch for during this scenario:
#   - Does llm_client.py time out before the 30s budget is exhausted?
#   - Do retry delays compound with the injected latency (retry storm risk)?
#   - Does the RAG pipeline degrade gracefully (partial results vs hard fail)?
scenario_network_latency() {
    log_section "Scenario: Network Latency (200ms injection)"

    local os
    os="$(uname -s)"

    if [ "$os" = "Linux" ]; then
        log_info "Detected Linux - using tc (traffic control) to inject 200ms latency on eth0."
        log_warn "This affects ALL outbound traffic on eth0 for 30 seconds."

        # WHY eth0: default interface in Docker-based dev environments and most cloud VMs.
        # On Kubernetes nodes the interface may differ (ens3, enp0s3, etc.) - adjust as needed.
        tc qdisc add dev eth0 root netem delay 200ms
        log_ok "Latency injected: 200ms on eth0"

        log_info "Sustaining latency for 30s - run your load test now:"
        log_info "  locust -f tests/load/locustfile.py --host $APP_URL"
        sleep 30

        tc qdisc del dev eth0 root
        log_ok "Network latency injection complete. eth0 restored to normal."

        log_info "Interpret results:"
        log_info "  - p95 latency should be ~200ms higher than baseline."
        log_info "  - Timeout errors indicate budget too tight; adjust HTTPX timeout in llm_client.py."
        log_info "  - Zero timeout errors: timeout budgets are appropriate for real-world latency."

    elif [ "$os" = "Darwin" ]; then
        log_warn "macOS detected - 'tc' (traffic control) is a Linux-only kernel feature."
        log_warn "On macOS, use Network Link Conditioner to inject latency manually:"
        echo ""
        echo "  Manual steps:"
        echo "  1. Open System Preferences > Network (or Xcode > Open Developer Tool > More Devices)"
        echo "  2. Enable 'Network Link Conditioner' from Additional Tools for Xcode"
        echo "  3. Set profile: '3G' (adds ~100ms) or create a custom profile with 200ms delay"
        echo "  4. Enable the conditioner, run your tests, then disable it"
        echo ""
        echo "  Alternative (container-level): docker compose exec <service> tc ..."
        echo "  Requires the container to run with CAP_NET_ADMIN (add to docker-compose.yml)."
        echo ""
        log_info "Skipping automated injection on macOS."
    else
        log_warn "Unknown OS '$os' - network latency injection not supported."
        log_info "Supported: Linux (tc), macOS (Network Link Conditioner manual)."
    fi
}

# scenario_memory_exhaustion: verify container memory limits and OOM recovery.
#
# Teaching note: WHY test memory exhaustion?
#   Python processes can leak memory (LangChain object cycles, embedding model
#   growth during long-running benchmark runs). Docker's memory limit triggers
#   OOM kill + automatic container restart (thanks to restart: unless-stopped).
#   This scenario verifies:
#     1) The container restarts cleanly after an OOM kill.
#     2) Health checks catch the downtime window (so load balancers can drain).
#     3) No persistent corruption - the app serves correct results post-restart.
#
#   WHY show docker inspect limits: Operators often don't know what limits are
#   set. Surfacing them here helps teams tune before a production OOM event.
scenario_memory_exhaustion() {
    log_section "Scenario: Memory Exhaustion (OOM simulation)"

    # Identify the app container. In this dev stack there is no dedicated 'app'
    # service - the agent/RAG code runs as a Python process, not a container.
    # This scenario is most relevant when the stack includes a deployed app service.
    local container_id
    container_id="$(docker compose -f "$COMPOSE_FILE" ps -q app 2>/dev/null || echo "")"

    if [ -z "$container_id" ]; then
        log_warn "App service not running or not configured in docker-compose.yml."
        log_info "This scenario applies when you add a containerised app service."
        log_info "Showing memory stats for available services instead:"
        echo ""

        # Show memory usage for all running stack containers.
        # WHY --no-stream: we want a snapshot, not a live feed (avoids blocking the script).
        docker compose -f "$COMPOSE_FILE" ps -q 2>/dev/null | while IFS= read -r cid; do
            if [ -n "$cid" ]; then
                local name
                name="$(docker inspect --format '{{.Name}}' "$cid" | sed 's|^/||')"
                local mem
                mem="$(docker stats --no-stream --format "{{.MemUsage}}" "$cid" 2>/dev/null || echo "unavailable")"
                local limit
                limit="$(docker inspect --format '{{.HostConfig.Memory}}' "$cid" 2>/dev/null || echo "0")"
                if [ "$limit" = "0" ]; then
                    limit="no limit set"
                else
                    # Convert bytes to megabytes for readability.
                    limit="$(( limit / 1024 / 1024 ))M"
                fi
                log_info "  ${name}: current=${mem}, docker limit=${limit}"
            fi
        done

        echo ""
        log_info "To test memory exhaustion manually:"
        log_info "  1. Add memory limit to a service in docker-compose.yml (e.g., memory: 256m)"
        log_info "  2. Run a stress container to exhaust memory:"
        echo ""
        echo "     docker run --rm --memory=256m stress:latest --vm 1 --vm-bytes 512M"
        echo ""
        log_info "  3. Watch the container restart:"
        echo ""
        echo "     docker events --filter event=oom --filter event=die --filter event=restart"
        echo ""
        log_info "  4. Verify app recovers (health check passes, queries succeed):"
        echo ""
        echo "     watch -n1 'docker compose -f $COMPOSE_FILE ps'"
        return 0
    fi

    log_info "App container found: $container_id"

    local mem_usage
    mem_usage="$(docker stats --no-stream --format "{{.MemUsage}}" "$container_id" 2>/dev/null || echo "unavailable")"
    log_info "Current memory usage: $mem_usage"

    local mem_limit
    mem_limit="$(docker inspect --format '{{.HostConfig.Memory}}' "$container_id" 2>/dev/null || echo "0")"
    if [ "$mem_limit" = "0" ]; then
        log_warn "No Docker memory limit set on the app container."
        log_warn "Without a limit, OOM kills go to the host OS - containers keep running."
        log_warn "Set a memory limit in docker-compose.yml deploy.resources.limits.memory"
    else
        local mem_limit_mb=$(( mem_limit / 1024 / 1024 ))
        log_info "Docker memory limit: ${mem_limit_mb}M"
    fi

    log_info ""
    log_info "To simulate OOM exhaustion against the running app container:"
    echo ""
    echo "  # Stress the container from inside (requires stress tool in the image):"
    echo "  docker exec $container_id stress --vm 1 --vm-bytes ${mem_limit_mb:-512}M --timeout 10s"
    echo ""
    echo "  # Or allocate memory via Python (for quick testing):"
    echo "  docker exec $container_id python -c \\"
    echo "    \"import time; x = bytearray(512 * 1024 * 1024); time.sleep(10)\""
    echo ""
    log_info "Monitor OOM events in real time:"
    echo ""
    echo "  docker events --filter event=oom --filter event=die --filter event=restart"
    echo ""
    log_ok "Memory exhaustion scenario setup complete."
    log_info "After OOM kill: verify restart with 'docker compose ps' and a /health probe."
}

# print_usage: display help text without exiting (caller decides exit code).
print_usage() {
    echo "Usage: $0 --scenario <name>"
    echo ""
    echo "Scenarios:"
    echo "  db_failure          Stop and restart Chroma; measure recovery time"
    echo "  network_latency     Inject 200ms latency via tc (Linux) or manual NLC (macOS)"
    echo "  memory_exhaustion   Show memory limits and OOM simulation instructions"
    echo "  all                 Run all three scenarios sequentially"
    echo ""
    echo "Environment variables:"
    echo "  APP_URL             Base URL for the app (default: http://localhost:8000)"
    echo "  RECOVERY_TIMEOUT    Seconds to wait for recovery (default: 60)"
    echo ""
    echo "Example:"
    echo "  $0 --scenario db_failure"
    echo "  RECOVERY_TIMEOUT=120 $0 --scenario all"
}

# usage: print help and exit 1 (for error cases).
usage() {
    print_usage
    exit 1
}

main() {
    local scenario=""

    # Parse arguments.
    # WHY manual parsing over getopts: long options (--scenario) are not supported
    # by POSIX getopts; getopt (GNU) is platform-dependent. Manual parsing is portable.
    while [ $# -gt 0 ]; do
        case "$1" in
            --scenario)
                shift
                scenario="${1:-}"
                ;;
            --help | -h)
                print_usage
                exit 0
                ;;
            *)
                log_error "Unknown argument: $1"
                usage
                ;;
        esac
        shift
    done

    if [ -z "$scenario" ]; then
        log_error "Missing required argument: --scenario"
        usage
    fi

    case "$scenario" in
        db_failure)
            scenario_db_failure
            ;;
        network_latency)
            scenario_network_latency
            ;;
        memory_exhaustion)
            scenario_memory_exhaustion
            ;;
        all)
            log_section "Running all fault injection scenarios"
            scenario_db_failure
            log_info "Pausing 10s between scenarios..."
            sleep 10
            scenario_network_latency
            log_info "Pausing 10s between scenarios..."
            sleep 10
            scenario_memory_exhaustion
            log_section "All scenarios complete"
            ;;
        *)
            log_error "Unknown scenario: '$scenario'"
            usage
            ;;
    esac
}

main "$@"
