"""Fixed-latency fake model for Article 8 load tests.

Why this exists: a load test against a real provider measures the provider as
much as the serving stack. Provider latency varies by minute, rate limits turn
into errors that look like overload, and every request costs money. This fake
replaces only the LLM call. Embedding, Chroma retrieval, FastAPI routing, the
threadpool, and auth all stay real, so the results describe the serving stack
under a known, constant model latency.

The fake blocks with time.sleep, the same way the real UnifiedLLMClient blocks
a worker thread while it waits on an HTTP response. An asyncio sleep would
release the thread and measure a different system.

Responses are deterministic. For the ReAct agent the first reasoning call
returns a RAGTool action and every later call returns a finish action, so each
/agent request makes exactly three fake calls (reason, RAG generation, reason)
and one real embedding. Every other prompt gets a fixed answer string.
"""

from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass

FAKE_MODEL_NAME = "fake-fixed-latency"

_REACT_MARKER = "Your response (JSON only, no other text):"
_REACT_FIRST_STEP_MARKER = "No previous actions yet."


@dataclass
class FakeLLMResponse:
    """Subset of LLMResponse that the RAG pipeline and ReAct agent read."""

    content: str
    model: str
    latency_seconds: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0


class FakeLLMClient:
    """Drop-in for UnifiedLLMClient.generate with a fixed blocking latency."""

    def __init__(self, latency_ms: float) -> None:
        if latency_ms < 0:
            raise ValueError("latency_ms must be >= 0")
        self.latency_ms = latency_ms
        self._lock = threading.Lock()
        self._calls = 0

    @property
    def calls(self) -> int:
        with self._lock:
            return self._calls

    def generate(self, prompt: str, **_: object) -> FakeLLMResponse:
        start = time.perf_counter()
        time.sleep(self.latency_ms / 1000)
        with self._lock:
            self._calls += 1
        return FakeLLMResponse(
            content=_respond(prompt),
            model=FAKE_MODEL_NAME,
            latency_seconds=time.perf_counter() - start,
        )


def _respond(prompt: str) -> str:
    if _REACT_MARKER in prompt:
        if _REACT_FIRST_STEP_MARKER in prompt:
            return json.dumps(
                {
                    "action": "tool",
                    "tool_name": "RAGTool",
                    "tool_input": "FastAPI dependency injection",
                    "reasoning": "fake model: retrieve once",
                }
            )
        return json.dumps(
            {
                "action": "finish",
                "final_answer": "fake model answer",
                "reasoning": "fake model: finish after one retrieval",
            }
        )
    return "fake model answer"
