"""FastAPI app server for in-cluster Article 8 measurement.

Surfaces the existing RAG pipeline and ReAct agent over HTTP so that Locust can
drive it from outside the cluster. Two business endpoints (`/query`, `/agent`)
plus the K8s probe pair (`/health`, `/ready`).

Why this exists: prior to this module, `benchmarks/run_article_08.py` produced a
mathematical simulation labelled as a measurement. Article 8 now requires a real
HTTP surface so that throughput and HPA behaviour are measured, not modelled.

Lifespan boot is best-effort: the BGE embedding model loads once and the pipeline
attaches to the pre-built Chroma collection if reachable. A Chroma outage at
startup logs `api.lifespan.pipeline_init_failed` and the process still boots, so
/health stays dependency-free. /ready and the business endpoints (/query,
/agent) surface 503 until Chroma is reattached. This matches K8s production
practice where readiness probes gate traffic, not liveness.
"""

from __future__ import annotations

import logging
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Literal

import redis
from fastapi import FastAPI, HTTPException
from llama_index.core import Settings as LlamaIndexSettings
from llama_index.core import StorageContext, VectorStoreIndex
from llama_index.vector_stores.chroma import ChromaVectorStore
from pydantic import BaseModel, Field

from src.agents.single_agent import ReActAgent
from src.agents.tools.calculator import CalculatorTool
from src.agents.tools.rag import RAGTool
from src.core.config import Settings, get_settings
from src.core.llm_client import UnifiedLLMClient
from src.rag.naive_rag import NaiveRAGPipeline

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "naive_rag"
AGENT_MAX_ITERATIONS = 5


class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    pipeline: Literal["naive"] = "naive"


class QueryResponse(BaseModel):
    answer: str
    docs: list[str]
    latency_ms: float


class AgentRequest(BaseModel):
    task: str = Field(..., min_length=1, max_length=2000)


class AgentResponse(BaseModel):
    result: str
    steps: int
    latency_ms: float


def _build_state(settings: Settings) -> dict[str, Any]:
    """Initialise heavyweight singletons. Called once from the lifespan event.

    Pipeline construction is best-effort: a Chroma outage at startup must not
    block the process from booting, otherwise /health stops being a
    dependency-free liveness signal. /ready re-checks Chroma per-request and
    surfaces the real state; K8s then gates traffic on /ready, not /health.
    chromadb.HttpClient validates the connection inside __init__, so the
    try/except has to wrap the pipeline constructor itself, not just the
    collection-attach call.
    """
    llm_client = UnifiedLLMClient(settings=settings)

    pipeline: NaiveRAGPipeline | None = None
    collection: Any = None
    agent: ReActAgent | None = None

    try:
        pipeline = NaiveRAGPipeline(
            collection_name=DEFAULT_COLLECTION,
            settings=settings,
        )
        collection = pipeline.chroma_client.get_or_create_collection(name=DEFAULT_COLLECTION)
        vector_store = ChromaVectorStore(chroma_collection=collection)
        storage_context = StorageContext.from_defaults(vector_store=vector_store)
        LlamaIndexSettings.embed_model = pipeline.embed_model
        pipeline._index = VectorStoreIndex.from_vector_store(
            vector_store, storage_context=storage_context
        )

        rag_tool = RAGTool(rag_pipeline=pipeline)
        calculator_tool = CalculatorTool()
        agent = ReActAgent(
            tools=[rag_tool, calculator_tool],
            llm_client=llm_client,
            max_iterations=AGENT_MAX_ITERATIONS,
        )
    except Exception as exc:
        logger.warning("api.lifespan.pipeline_init_failed: %s: %s", type(exc).__name__, exc)

    redis_client = redis.from_url(settings.redis_url, socket_timeout=2)  # type: ignore[no-untyped-call]

    return {
        "settings": settings,
        "pipeline": pipeline,
        "agent": agent,
        "redis_client": redis_client,
        "collection": collection,
    }


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    logger.info(
        "api.lifespan.start chroma_url=%s redis_url=%s", settings.chroma_url, settings.redis_url
    )
    app.state.svc = _build_state(settings)
    logger.info("api.lifespan.ready")
    yield
    logger.info("api.lifespan.shutdown")


app = FastAPI(title="rag-agent-api", version="1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness: process is up. No external dependency checks."""
    return {"status": "ok"}


@app.get("/ready")
def ready() -> dict[str, Any]:
    """Readiness: Redis ping + Chroma heartbeat. 503 if either fails."""
    svc = app.state.svc
    failures: dict[str, str] = {}

    try:
        svc["redis_client"].ping()
    except Exception as exc:
        failures["redis"] = f"{type(exc).__name__}: {exc}"

    try:
        # Chroma heartbeat is a cheap RTT probe; collection.count() also implicitly
        # validates the collection still exists. If lifespan never attached,
        # collection is None and /ready surfaces that as a failure.
        if svc["collection"] is None:
            failures["chroma"] = "collection not attached at startup"
        else:
            svc["collection"].count()
    except Exception as exc:
        failures["chroma"] = f"{type(exc).__name__}: {exc}"

    if failures:
        raise HTTPException(status_code=503, detail={"status": "not_ready", "failures": failures})
    return {"status": "ready"}


@app.post("/query", response_model=QueryResponse)
def query(request: QueryRequest) -> QueryResponse:
    """Naive RAG: embed -> retrieve top-K -> generate. Single retriever path per D2."""
    pipeline: NaiveRAGPipeline | None = app.state.svc["pipeline"]
    if pipeline is None or app.state.svc["collection"] is None:
        raise HTTPException(
            status_code=503, detail="rag pipeline unavailable (Chroma not attached)"
        )
    start = time.perf_counter()
    result = pipeline.query(query_str=request.query)
    latency_ms = (time.perf_counter() - start) * 1000

    docs = [node.node.get_content() for node in result.get("context_nodes", [])]
    return QueryResponse(answer=str(result["answer"]), docs=docs, latency_ms=latency_ms)


@app.post("/agent", response_model=AgentResponse)
def agent(request: AgentRequest) -> AgentResponse:
    """ReAct agent with 5-step max per D3. Tools: RAG, Calculator."""
    react: ReActAgent | None = app.state.svc["agent"]
    if react is None:
        raise HTTPException(status_code=503, detail="agent unavailable (Chroma not attached)")
    start = time.perf_counter()
    outcome = react.run(query=request.task)
    latency_ms = (time.perf_counter() - start) * 1000

    return AgentResponse(
        result=str(outcome.get("answer", "")),
        steps=int(outcome.get("iteration_count", 0)),
        latency_ms=latency_ms,
    )
