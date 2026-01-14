#!/usr/bin/env bash
set -euo pipefail

# Start Development Stack
# Launches Redis, Chroma, and Phoenix for local development

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
COMPOSE_FILE="$PROJECT_ROOT/infra/docker-compose.yml"

cd "$PROJECT_ROOT"

echo "Starting development stack..."
echo "  - Redis (cache + state): http://localhost:6379"
echo "  - Chroma (vector DB): http://localhost:8000"
echo "  - Phoenix (observability): http://localhost:6006"
echo ""

docker-compose -f "$COMPOSE_FILE" up -d redis chroma phoenix

echo ""
echo "Waiting for services to be healthy..."

# Wait for services
MAX_WAIT=60
ELAPSED=0

while [ $ELAPSED -lt $MAX_WAIT ]; do
  if docker-compose -f "$COMPOSE_FILE" ps | grep -q "unhealthy\|starting"; then
    echo -n "."
    sleep 2
    ELAPSED=$((ELAPSED + 2))
  else
    break
  fi
done

echo ""
echo ""
docker-compose -f "$COMPOSE_FILE" ps

echo ""
echo "Development stack ready!"
echo ""
echo "Access services:"
echo "  - Phoenix UI: http://localhost:6006"
echo "  - Redis CLI: redis-cli -h localhost -p 6379"
echo "  - Chroma API: http://localhost:8000/api/v1"
echo ""
echo "Stop stack: docker-compose -f infra/docker-compose.yml down"
echo "View logs: docker-compose -f infra/docker-compose.yml logs -f [service]"
