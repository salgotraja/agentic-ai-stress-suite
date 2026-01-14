# Testcontainer Reuse Strategies

This document explains container reuse strategies in our test suite for optimal performance.

## Current Approach: Session-Scoped Containers

**Status**: ✅ Implemented (Default)

All infrastructure containers (Redis, PostgreSQL, ChromaDB) use `scope="session"`:

```python
@pytest.fixture(scope="session")
def chroma_container():
    # Container started once per pytest session
    # Reused across all tests in the session
    # Cleaned up when session ends
```

### Benefits:
- **Fast**: Container started once, reused by all tests
- **Isolated**: Each test uses different namespace (collection, database, key prefix)
- **Clean**: Automatic cleanup after test session
- **Portable**: Works everywhere (local, CI/CD)

### Performance:
- First test: ~5-10s (container pull + start)
- Subsequent tests: <1s (reuse existing container)
- Cleanup: Automatic (container removed after session)

---

## Alternative 1: Function-Scoped (Maximum Isolation)

**Status**: Available but not default

Use when you need complete isolation per test:

```python
@pytest.fixture(scope="function")  # Fresh container per test
def chroma_container():
    with DockerContainer("...") as container:
        yield container
```

### Benefits:
- **Maximum isolation**: No shared state between tests
- **Debugging**: Easier to debug single test failures
- **Independence**: Tests can run in any order

### Drawbacks:
- **Slow**: 5-10s overhead per test (start + stop container)
- **Resource intensive**: More Docker containers created/destroyed
- **Not recommended**: Unless you have state pollution issues

---

## Alternative 2: Persistent Reusable Containers

**Status**: ⚠️ **NOT RECOMMENDED** - Resource consumption risk

Testcontainers supports keeping containers running between test runs:

```python
@pytest.fixture(scope="session")
def chroma_container():
    with DockerContainer("...") as container:
        container.with_kwargs(labels={"reuse": "true"})  # Mark as reusable
        yield container
```

Then set environment variable:
```bash
export TESTCONTAINERS_REUSE_ENABLE=true
pytest tests/
```

### ⚠️ CRITICAL: How Persistent Containers Work

**Important clarifications:**

1. **Containers stay running BETWEEN pytest runs** (not just within one run)
   - Run `pytest` at 2pm → containers start
   - Tests finish at 2:05pm → **containers stay running** ❌
   - Run `pytest` again at 3pm → reuses same containers (fast!)
   - Run `pytest` again tomorrow → **still using same containers** ❌

2. **NOT automatically cleaned up**
   - Normal session scope: Cleans up after each `pytest` run ✓
   - Persistent reusable: **NEVER cleans up automatically** ❌
   - Containers run forever until you manually stop them

3. **Resource consumption**
   ```bash
   # After 1 week of development with persistent containers:
   docker ps | grep testcontainers
   # chroma-container      (running 7 days)
   # redis-container       (running 7 days)
   # postgres-container    (running 7 days)

   # Each consuming:
   # - Memory: 50-500MB per container
   # - Disk: Logs growing over time
   # - CPU: Background processes
   ```

4. **Forgotten containers accumulate**
   - Easy to forget to clean up
   - Multiple developers = multiple orphaned containers
   - Can slow down Docker daemon
   - Can fill disk with logs

### Benefits:
- **Very fast**: 0s startup on subsequent `pytest` runs
- **Development speed**: Instant test reruns

### Drawbacks:
- **❌ Manual cleanup required**: Must remember to stop containers
- **❌ Resource waste**: Containers run indefinitely (memory, CPU, disk)
- **❌ Stale state**: Old data persists across runs (hard to debug)
- **❌ CI incompatible**: Containers accumulate in CI, causing failures
- **❌ Not portable**: Requires env variable + manual cleanup discipline
- **❌ Team confusion**: Other developers may not know containers are running

### Required Manual Cleanup:

**You MUST manually clean up** persistent containers:

```bash
# Check what's running
docker ps | grep testcontainers

# Stop all testcontainers (do this daily!)
docker rm -f $(docker ps -a -q --filter "label=org.testcontainers")

# Or stop specific container
docker rm -f chroma-testcontainer

# Check resource usage
docker stats  # See memory/CPU consumption
```

### When to use (rarely):
- ✓ Active debugging session (1-2 hours)
- ✓ Rapid iteration on single test file
- ✓ You will remember to clean up immediately after

### When NOT to use (most of the time):
- ❌ Regular development workflow
- ❌ CI/CD pipelines
- ❌ Shared development environments
- ❌ If you forget to clean up often
- ❌ If team members don't understand the setup

### Better Alternative:

**Instead of persistent containers, use session scope + fast Docker:**

```bash
# Enable Docker layer caching
# Containers start in ~2s instead of ~5s after first pull

# Run specific test file (faster than full suite)
pytest tests/integration/agents/tools/test_rag.py -v

# Use pytest-xdist for parallel tests
pytest tests/ -n auto  # Run tests in parallel
```

---

## ⚠️ OUR RECOMMENDATION: Do NOT use persistent containers

**Stick with session scope (current default)** unless you have a specific reason.

**Why:**
- Session scope is fast enough (5s startup, then <1s per test)
- Automatic cleanup prevents resource waste
- No manual intervention required
- Works in CI/CD without modification
- No risk of forgotten containers consuming resources

**If you really need speed:**
- Run specific test files (not full suite)
- Use pytest-xdist for parallelization
- Upgrade Docker (newer versions have faster startup)

---

## Alternative 3: Module-Scoped (Per Test File)

**Status**: Available alternative

Use when test files have different requirements:

```python
@pytest.fixture(scope="module")  # One container per test file
def chroma_container():
    with DockerContainer("...") as container:
        yield container
```

### Benefits:
- **Balanced**: Reuse within file, isolated between files
- **Good for**: Large test files with many related tests
- **Faster than function**: Less overhead than per-test containers

### Drawbacks:
- **Slower than session**: More containers than session scope
- **Less common**: Session scope usually sufficient

---

## Recommended Approach by Use Case

### ✅ Default (Current): Session Scope
**Use for**: 95% of tests

```python
@pytest.fixture(scope="session")
def chroma_container():
    ...
```

**Isolation via**: Unique collection names, database names, key prefixes per test

---

### ⚠️ NOT RECOMMENDED: Persistent Reusable
**Use for**: ❌ Avoid unless actively debugging

```bash
# ❌ DO NOT USE for regular development
export TESTCONTAINERS_REUSE_ENABLE=true
pytest tests/integration/

# ⚠️ CRITICAL: Must manually cleanup daily
docker rm -f $(docker ps -a -q --filter "label=org.testcontainers")
```

**Problems**:
- Containers run forever (consume memory/CPU/disk)
- Manual cleanup required (easy to forget)
- Stale data between runs (hard to debug)

**Alternative**: Use session scope + run specific test files

---

### 🐛 Debugging: Function Scope
**Use for**: Debugging specific test failures with state pollution

```python
# Override in specific test file
@pytest.fixture(scope="function")
def chroma_container():
    ...
```

**Benefits**: Maximum isolation, easier debugging

---

## Our Choice: Session Scope (Default)

**Why session scope is our default:**

1. **Performance**: Fast enough for CI/CD and local development
2. **Simplicity**: No environment variables or manual cleanup required
3. **Isolation**: Each test uses unique namespace (sufficient for our needs)
4. **Portability**: Works everywhere without configuration
5. **Best practice**: Recommended by testcontainers documentation

**Container startup times** (measured):
- Redis: ~2s
- PostgreSQL: ~3s
- ChromaDB: ~5s (first pull ~30s)

**With session scope**, these costs are paid once per test session, making the entire test suite run fast.

---

## Example: Isolation with Session Scope

Even with shared containers, tests are isolated:

```python
# Test 1
def test_rag_fastapi(rag_pipeline):
    # Uses collection "test_rag_tool"
    result = rag_pipeline.query("What is FastAPI?")

# Test 2
def test_rag_react(rag_pipeline):
    # Uses same container, different collection
    # Or can use collection cleanup between tests
    result = rag_pipeline.query("What is React?")
```

**Isolation strategies:**
1. **Unique collection names** per test (e.g., `f"test_{uuid.uuid4()}"`)
2. **Cleanup fixtures** that drop collections/databases after tests
3. **Namespace prefixes** (Redis keys: `test1:*`, `test2:*`)

---

## Performance Comparison

| Scope | Startup Time | Total for 10 tests | Use Case |
|-------|--------------|-------------------|----------|
| **session** | 5s | ~6s | ✅ Default |
| module | 5s per file | ~10-15s | Files need different config |
| function | 5s per test | ~50s | Debugging state issues |
| persistent (reuse) | 0s (after first) | ~1s | 🔧 Local dev iterations |

---

## Migration Path

If session scope becomes too slow (>100 tests):

1. **First**: Profile tests to find slow tests
2. **Then**: Consider persistent reusable for local dev
3. **Finally**: Module or function scope only for problematic tests

Current test count: <10 integration tests → session scope is optimal.

---

## Summary & Final Recommendation

### ✅ USE THIS: Session Scope (Default)
```python
@pytest.fixture(scope="session")  # ✅ Recommended
def chroma_container():
    ...
```

**Characteristics:**
- ✅ Fast: 5s startup, then <1s per test
- ✅ Clean: Auto cleanup after each `pytest` run
- ✅ Simple: No configuration needed
- ✅ Portable: Works in CI/CD and local dev
- ✅ Isolated: Via unique collection names per test

**Lifecycle:**
1. Run `pytest tests/` → Container starts
2. All tests run → Container reused
3. Tests finish → **Container automatically removed** ✓

---

### ⚠️ AVOID THIS: Persistent Reusable
```bash
export TESTCONTAINERS_REUSE_ENABLE=true  # ❌ Not recommended
```

**Why avoid:**
- ❌ Containers run forever (until manual cleanup)
- ❌ Consumes memory/CPU/disk indefinitely
- ❌ Easy to forget cleanup
- ❌ Stale data between runs
- ❌ Not suitable for CI/CD
- ❌ Team confusion

**Lifecycle:**
1. Run `pytest tests/` → Container starts
2. Tests finish → **Container keeps running** ❌
3. Run `pytest` again tomorrow → **Still running** ❌
4. **You must manually run:** `docker rm -f ...` ❌

**Only use if:**
- Active debugging (1-2 hours max)
- You WILL remember to clean up immediately
- You understand the risks

---

### ❌ RARELY USE: Function Scope
```python
@pytest.fixture(scope="function")  # ❌ Slow
def chroma_container():
    ...
```

**Why avoid:**
- Too slow (5s overhead per test)
- Only for debugging state pollution

---

## Quick Decision Guide

**Normal development?** → ✅ Session scope (current default)

**Tests are slow?** → Run specific files: `pytest tests/integration/agents/tools/test_rag.py -v`

**Debugging state issues?** → Function scope (temporarily)

**Want faster reruns?** → ❌ Don't use persistent containers! Instead:
- Run specific test file (not full suite)
- Use `pytest -k test_name` to run single test
- Use `pytest-xdist` for parallel execution

---

## Resource Usage Comparison

| Strategy | Memory (3 containers) | Cleanup | Risk |
|----------|----------------------|---------|------|
| **Session scope** | ~300MB (during tests only) | Automatic ✓ | None ✓ |
| Persistent reusable | ~300MB (forever) | Manual ❌ | High ❌ |
| Function scope | ~300MB (during tests only) | Automatic ✓ | None ✓ |

---

## Final Word

**Our recommendation: Stick with session scope.**

It's fast, clean, and requires no manual intervention. Persistent containers seem appealing for speed, but the manual cleanup burden and resource consumption risks outweigh the benefits.

If tests feel slow, optimize by running specific test files rather than introducing persistent container complexity.
