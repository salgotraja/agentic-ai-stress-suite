# Integration Tests

End-to-end integration tests for the Agentic AI Stress Test Suite.

## Phase 1 E2E Tests

`test_phase1_e2e.py` contains comprehensive end-to-end tests that verify all Phase 1 components work together.

### Prerequisites

1. **Docker Compose services must be running:**
   ```bash
   ./scripts/start_dev_stack.sh
   ```

   This starts:
   - Redis (cache/state)
   - Chroma (vector DB)
   - Phoenix (observability)

2. **Environment variables configured:**
   - Ensure `.env` or `.env.local` has required LLM API keys
   - See `.env.example` for required variables

### Running Tests

**Run all Phase 1 E2E tests:**
```bash
pytest tests/integration/test_phase1_e2e.py -v
```

**Run specific test:**
```bash
pytest tests/integration/test_phase1_e2e.py::test_e2e_naive_rag_query -v
```

**With coverage:**
```bash
pytest tests/integration/test_phase1_e2e.py --cov=src/ --cov-report=term-missing
```

### Test Coverage

Phase 1 E2E tests verify:

1. **Naive RAG Query** (`test_e2e_naive_rag_query`)
   - Document indexing and chunking
   - Vector search retrieval
   - LLM answer generation
   - Observability trace capture

2. **ReAct Agent with Tools** (`test_e2e_react_agent_with_tools`)
   - Agent reasoning loop
   - Tool selection (RAG, Calculator)
   - Multi-step workflows
   - Final answer synthesis

3. **Multi-Agent Collaboration** (`test_e2e_multi_agent_collaboration`)
   - Researcher-Writer pipeline
   - State handoff between agents
   - Sequential orchestration
   - End-to-end multi-agent flow

4. **All Components Integration** (`test_e2e_all_components_integration`)
   - Complex scenario with all components
   - RAG + Single-agent + Multi-agent
   - Full stack integration

5. **Observability Integration** (`test_e2e_observability_integration`)
   - Correlation ID propagation
   - Trace structure validation
   - Phoenix integration

### Viewing Traces

After running tests, view traces in Phoenix UI:
```bash
open http://localhost:6006
```

Look for:
- Trace spans for each operation
- Latency measurements
- LLM token usage
- Tool invocations
- Agent reasoning steps

### Cleanup

Stop services after testing:
```bash
docker-compose -f infra/docker-compose.yml down
```

### Troubleshooting

**Services not healthy:**
```bash
docker-compose -f infra/docker-compose.yml ps
docker-compose -f infra/docker-compose.yml logs [service]
```

**Connection errors:**
- Ensure services are running: `docker-compose ps`
- Check ports are not in use: `lsof -i :6006,6379,8000`
- Restart services: `docker-compose down && ./scripts/start_dev_stack.sh`

**Test failures:**
- Check API keys are set in `.env.local`
- Verify services are healthy (all show `(healthy)` status)
- Check Phoenix UI for error traces
- Review test output for specific assertion failures
