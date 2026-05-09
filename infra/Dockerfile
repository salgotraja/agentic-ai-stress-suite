# syntax=docker/dockerfile:1.7
#
# rag-agent-api: production-lite container for the FastAPI surface in
# src/ops/deployment/api.py. Built once, deployed to Docker Desktop K8s
# (Article 8). The image embeds the BGE-base-en-v1.5 weights so cold pod
# starts don't pay the ~200MB Hugging Face download tax on the first
# request, which would otherwise dominate p99 during HPA scale-out.
#
# Image is intentionally fat (~5-6GB) because pyproject.toml installs the
# full superset of dependencies for all 9 articles (torch, jax, haystack,
# crewai, etc.). Splitting into a leaner runtime extras group is left as
# follow-up; for the K8s scaling demo a single image keeps the manifests
# uniform and the populate Job (future) can reuse the same image.
#
# Build:  docker build -t rag-agent-api:latest -f infra/Dockerfile .
# Run:    docker run --rm -p 8000:8000 \
#             -e GROQ_API_KEY=$GROQ_API_KEY \
#             -e CHROMA_URL=http://host.docker.internal:8000 \
#             -e REDIS_URL=redis://host.docker.internal:6379 \
#             rag-agent-api:latest

# ============================================================================
# Stage 1: builder - resolve deps with uv into /opt/venv
# ============================================================================
FROM python:3.11-slim AS builder

# Build toolchain. Most deps ship prebuilt wheels for linux/amd64 +
# linux/arm64, but `annoy` (pulled in transitively via nemoguardrails)
# has no arm64 wheel and compiles from source, so we need g++ and the
# Python headers in this stage. build-essential is removed by being
# scoped to the builder layer only - the runtime image stays slim.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential python3-dev \
    && rm -rf /var/lib/apt/lists/*

# uv via the official distroless image. Pinned to match local dev (0.9.x)
# so lockfile semantics don't drift between machine and image.
COPY --from=ghcr.io/astral-sh/uv:0.9.24 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

# Sync dependencies only (skip installing the project package itself).
# pyproject.toml declares packages=["src"] under hatchling, but we don't
# need a wheel install -- the runtime stage sets PYTHONPATH=/app and
# imports `src.ops.deployment.api` directly. This shaves one pip step
# and keeps the venv free of stale package metadata.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ============================================================================
# Stage 2: runtime - copy venv, app code, corpus; pre-bake BGE weights
# ============================================================================
FROM python:3.11-slim AS runtime

# curl is needed for the HEALTHCHECK directive below. Everything else is
# already bundled inside the venv as Python wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user. Container-escape mitigation; also K8s defaults to denying
# privilege escalation so the manifests assume a non-zero uid.
RUN groupadd --system --gid 1000 appuser \
    && useradd --system --uid 1000 --gid appuser --create-home --home-dir /home/appuser appuser

ENV PATH="/opt/venv/bin:${PATH}" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    HF_HOME=/home/appuser/.cache/huggingface \
    SENTENCE_TRANSFORMERS_HOME=/home/appuser/.cache/sentence-transformers

WORKDIR /app

COPY --from=builder /opt/venv /opt/venv
COPY src/ /app/src/
# tech_docs corpus is only ~2.4MB and lets a future in-cluster populate
# Job reuse this same image instead of needing a separate corpus image.
COPY datasets/tech_docs/ /app/datasets/tech_docs/

RUN chown -R appuser:appuser /home/appuser /app
USER appuser

# Pre-bake BGE-base-en-v1.5 weights into the image. Without this, the
# first request after a pod start triggers a Hugging Face download (~200MB,
# 5-15s on a fresh node) that lands inside the request latency tail. With
# the bake, cold-pod first-request latency drops to the embedding compute
# path only, which keeps HPA scale-out responsive.
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"

EXPOSE 8000

# HEALTHCHECK is a Docker-level signal (visible in `docker ps`). K8s
# ignores it and uses livenessProbe/readinessProbe from the Deployment
# manifest instead. We still set it because it's useful when running the
# image standalone (article-8 dockerfile smoke, before cluster apply).
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD curl -fsS http://127.0.0.1:8000/health || exit 1

CMD ["uvicorn", "src.ops.deployment.api:app", "--host", "0.0.0.0", "--port", "8000"]
