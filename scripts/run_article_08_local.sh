#!/usr/bin/env bash
# Article 8 local load procedure: fake-model API in Docker, closed-loop
# (Locust) and fixed-arrival-rate (open-loop) runs, probe and occupancy
# sampling, container CPU and memory sampling.
#
# Everything runs against containers this script creates (prefix a08-) on a
# private network; nothing else is touched. Usage:
#
#   export A08_TOKEN_FILE=/path/to/token       # any random string, kept out of git
#   export A08_OUT=results/data/article_08_local_<date>
#   scripts/run_article_08_local.sh infra-up    # network, Chroma, Redis, collection
#   scripts/run_article_08_local.sh api-up <workers> [async-health]
#   scripts/run_article_08_local.sh closed <tag> <users> <seconds>
#   scripts/run_article_08_local.sh open <tag> <rate_rps> <seconds>
#   scripts/run_article_08_local.sh api-down
#   scripts/run_article_08_local.sh infra-down
#
# Settings (env, defaults shown): A08_FAKE_LATENCY_MS=1000, A08_CPUS_PER_WORKER=1.5,
# A08_MEM_PER_WORKER_GB=2, A08_TIMEOUT_S=30, A08_RECOVERY_S=90, A08_PORT=8088,
# A08_IMAGE=rag-agent-api:latest, A08_EMBED_CACHE=.cache/embeddings.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${A08_PORT:-8088}"
HOST="http://localhost:${PORT}"
IMAGE="${A08_IMAGE:-rag-agent-api:latest}"
LATENCY_MS="${A08_FAKE_LATENCY_MS:-1000}"
CPUS_PER_WORKER="${A08_CPUS_PER_WORKER:-1.5}"
MEM_PER_WORKER_GB="${A08_MEM_PER_WORKER_GB:-2}"
TIMEOUT_S="${A08_TIMEOUT_S:-30}"
RECOVERY_S="${A08_RECOVERY_S:-90}"
EMBED_CACHE="${A08_EMBED_CACHE:-${ROOT}/.cache/embeddings}"
OUT="${A08_OUT:?set A08_OUT to the output directory}"
COLLECTION=a08_naive_rag

token() { tr -d '\n' <"${A08_TOKEN_FILE:?set A08_TOKEN_FILE}"; }

infra_up() {
  docker network create a08-net >/dev/null
  docker run -d --name a08-chroma --network a08-net -p 8018:8000 chromadb/chroma:1.5.9 >/dev/null
  docker run -d --name a08-redis --network a08-net redis:8.10.2-alpine >/dev/null
  until curl -sf localhost:8018/api/v2/heartbeat >/dev/null; do sleep 1; done
  (cd "$ROOT" && CHROMA_URL=http://localhost:8018 OBSERVABILITY_ENABLED=false \
    uv run --no-sync python scripts/populate_chroma.py --collection "$COLLECTION")
}

api_up() {
  local workers="$1" health_async="${2:-}"
  local cpus mem
  cpus=$(python3 -c "print(${workers} * ${CPUS_PER_WORKER})")
  mem=$((workers * MEM_PER_WORKER_GB))
  mkdir -p "$OUT"
  docker run -d --name a08-api --network a08-net -p "${PORT}:8000" \
    --cpus "$cpus" --memory "${mem}g" \
    -e API_AUTH_TOKEN="$(token)" \
    -e CHROMA_URL=http://a08-chroma:8000 -e REDIS_URL=redis://a08-redis:6379 \
    -e API_FAKE_LLM_LATENCY_MS="$LATENCY_MS" -e API_COLLECTION_NAME="$COLLECTION" \
    -e API_LOADTEST_INSTRUMENTATION=1 \
    -e API_HEALTH_ASYNC="$([ "$health_async" = async-health ] && echo true || echo false)" \
    -e OBSERVABILITY_ENABLED=false -e HF_HUB_OFFLINE=1 \
    -v "${ROOT}/src:/app/src:ro" -v "${EMBED_CACHE}:/app/.cache/embeddings" \
    "$IMAGE" uvicorn src.ops.deployment.api:app --host 0.0.0.0 --port 8000 \
    --workers "$workers" >/dev/null
  until curl -sf "${HOST}/ready" >/dev/null; do sleep 2; done
  # Warm every worker: one authenticated /query per worker slot, several times.
  for _ in $(seq 1 $((workers * 4))); do
    curl -sf -o /dev/null -H "Authorization: Bearer $(token)" -H 'content-type: application/json' \
      -d '{"query":"warm up"}' "${HOST}/query"
  done
  echo "{\"workers\": ${workers}, \"cpus\": ${cpus}, \"memory_gb\": ${mem}, \"fake_latency_ms\": ${LATENCY_MS}, \"health\": \"$([ "$health_async" = async-health ] && echo async || echo sync)\", \"image\": \"$(docker image inspect "$IMAGE" --format '{{.Id}}')\"}" \
    >"${OUT}/api_config_w${workers}${health_async:+_async}.json"
}

samplers_start() {
  local dir="$1" seconds="$2"
  (cd "$ROOT" && uv run --no-sync python benchmarks/article_08_local_load.py probe --host "$HOST" \
    --duration "$seconds" --out "${dir}/probe.jsonl") &
  PROBE_PID=$!
  (
    end=$(($(date +%s) + seconds))
    while [ "$(date +%s)" -lt "$end" ]; do
      printf '%s ' "$(date +%s)"
      docker stats --no-stream a08-api --format '{{.CPUPerc}} {{.MemUsage}}'
    done >"${dir}/container_stats.txt"
  ) &
  STATS_PID=$!
  docker events --filter container=a08-api --format '{{.Time}} {{.Action}}' >"${dir}/docker_events.txt" &
  EVENTS_PID=$!
}

samplers_stop() {
  wait "$PROBE_PID" "$STATS_PID" || true
  kill "$EVENTS_PID" 2>/dev/null || true
  docker inspect a08-api --format '{"oom_killed": {{.State.OOMKilled}}, "restart_count": {{.RestartCount}}, "status": "{{.State.Status}}"}' >"$1/container_state.json"
}

closed() {
  local tag="$1" users="$2" seconds="$3" dir="${OUT}/${1}"
  mkdir -p "$dir"
  samplers_start "$dir" $((seconds + RECOVERY_S))
  date +%s >"${dir}/load_start_ts.txt"
  (cd "$ROOT" && LOADTEST_API_TOKEN="$(token)" LOADTEST_TIMEOUT_S="$TIMEOUT_S" \
    LOADTEST_REQUEST_LOG="${dir}/requests.jsonl" \
    uv run --no-sync locust -f src/ops/deployment/load_test.py --headless -u "$users" \
    -r "$(python3 -c "print(max(1, ${users} // 10))")" -t "${seconds}s" --host "$HOST" \
    --csv "${dir}/locust" --only-summary >"${dir}/locust_stdout.txt" 2>&1) || true
  date +%s >"${dir}/load_end_ts.txt"
  samplers_stop "$dir"
  echo "{\"kind\": \"closed\", \"users\": ${users}, \"duration_s\": ${seconds}, \"timeout_s\": ${TIMEOUT_S}}" >"${dir}/run.json"
}

open_loop() {
  local tag="$1" rate="$2" seconds="$3" dir="${OUT}/${1}"
  mkdir -p "$dir"
  samplers_start "$dir" $((seconds + RECOVERY_S))
  date +%s >"${dir}/load_start_ts.txt"
  (cd "$ROOT" && LOADTEST_API_TOKEN="$(token)" uv run --no-sync python benchmarks/article_08_local_load.py \
    open-loop --host "$HOST" --rate "$rate" --duration "$seconds" --timeout "$TIMEOUT_S" \
    --out "${dir}/requests.jsonl" >"${dir}/open_loop_stdout.txt" 2>&1) || true
  date +%s >"${dir}/load_end_ts.txt"
  samplers_stop "$dir"
  echo "{\"kind\": \"open\", \"rate_rps\": ${rate}, \"duration_s\": ${seconds}, \"timeout_s\": ${TIMEOUT_S}}" >"${dir}/run.json"
}

case "${1:-}" in
  infra-up) infra_up ;;
  api-up) api_up "$2" "${3:-}" ;;
  closed) closed "$2" "$3" "$4" ;;
  open) open_loop "$2" "$3" "$4" ;;
  api-down) docker rm -f a08-api >/dev/null ;;
  infra-down) docker rm -f a08-chroma a08-redis >/dev/null; docker network rm a08-net >/dev/null ;;
  *) sed -n '2,20p' "$0"; exit 2 ;;
esac
