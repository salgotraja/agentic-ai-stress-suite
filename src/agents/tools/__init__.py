"""Agent tool taxonomy and pluggable execution surface.

Why a dedicated tools package:
- Agents are only as useful as the tools they can compose; isolating them in
  one package keeps the agent core (reasoning, planning, state) separate from
  the I/O surface (search, calculation, RAG, MCP).
- Every tool extends `BaseTool`, which mandates `execute`, `mock_execute`, and
  `describe`. The `mock_execute` contract is what makes unit-testing agent
  trajectories possible without paying for real API calls or hitting the
  network - swap real for mock at construction time.

Tool categories shipped here (all inherit from `BaseTool`):
- I/O-bound (network, disk, subprocess): `search`, `rag`, `db_lookup`,
  `mcp_tools`, `custom_embedding_rag`. These dominate wall-clock time but
  release the GIL during their wait, so a `ThreadPoolExecutor` parallelises
  them effectively (see `single_agent.execute_tools_parallel`).
- CPU-bound: `calculator`, `code_exec`. These hold the GIL; only a
  `ProcessPoolExecutor` parallelises them, and the process-spawn overhead
  (~50-100 ms) only pays off for long-running computations.

Security note: `code_exec` runs LLM-generated Python and is inherently
dangerous. Read its module docstring before enabling it outside a sandbox.
"""
