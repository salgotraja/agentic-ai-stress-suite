# Load Testing and Benchmarking

Load testing and benchmarking are essential practices for ensuring the reliability and performance of FastAPI applications under real-world conditions. FastAPI, while optimized for speed and efficiency, still requires rigorous testing to identify bottlenecks, validate scalability, and confirm that it meets service-level objectives (SLOs). This documentation provides a comprehensive guide to load testing and benchmarking using tools like Locust, hey, and wrk, along with strategies for analyzing results and improving system performance.

---

## Load Testing Tools for FastAPI

### Locust: Pythonic Load Testing

Locust is a Python-based tool that allows developers to define user behavior in code, making it ideal for creating realistic, scenario-driven load tests. Its integration with Python aligns well with FastAPI development workflows and supports both synchronous and asynchronous testing.

#### Example: Testing a FastAPI Endpoint
```python
from locust import HttpUser, task, between

class FastAPIUser(HttpUser):
    wait_time = between(0.5, 1.5)  # Simulate user think time

    @task
    def get_item(self):
        self.client.get("/items/1", params={"detail": "true"})

    @task(3)
    def create_item(self):
        payload = {"name": "test", "price": 42}
        self.client.post("/items/", json=payload)
```

**Why Use Locust?**  
- **Realistic scenarios**: Model user behavior with Python code.
- **Async support**: Test FastAPI's async routes with `async def` tasks.
- **Web UI**: Visualize results in real time via a built-in dashboard.

Run the test with:
```bash
locust -f locustfile.py
```
Then navigate to `http://localhost:8080` to configure and start the test.

---

### Hey: Simple HTTP Benchmarking

The `hey` tool is a lightweight CLI utility for sending HTTP requests at scale. It is ideal for quick benchmarking of specific endpoints without complex user scenarios.

#### Example: Benchmarking a Read Endpoint
```bash
hey -n 1000 -c 50 -m GET http://localhost:8000/items/1
```

**Key Parameters**:
- `-n`: Total number of requests.
- `-c`: Number of concurrent requests.
- `-m`: HTTP method.

**When to Use Hey**  
- Fast validation of endpoint throughput.
- Debugging performance regressions in staging environments.

---

### wrk: High-Performance Load Testing

wrk is a modern HTTP benchmarking tool that leverages multi-threading and LuaJIT scripting for high-performance testing. It excels at generating heavy load and customizing request patterns.

#### Example: Stress Testing with wrk
```bash
wrk -t4 -c100 -d30s -s script.lua http://localhost:8000
```

**Lua Script Example (script.lua)**:
```lua
wrk.method = "POST"
wrk.body = '{"name":"load test","price":100}'
wrk.headers = {
    ["Content-Type"] = "application/json",
}
```

**Advantages of wrk**  
- Generates up to 100k+ RPS on modern hardware.
- Lua scripting for dynamic payloads.
- Lightweight and fast for CLI-driven testing.

---

## Performance Metrics and Analysis

### Key Metrics to Track

1. **Requests Per Second (RPS)**: Measures throughput capacity.
2. **Latency Percentiles (P50/P95/P99)**: Identifies latency distribution under load.
3. **Error Rates**: Tracks HTTP 5xx errors or timeouts.
4. **Resource Utilization**: CPU, memory, and database connection metrics.

**Cross-Reference**: For ongoing monitoring, integrate tools like Prometheus and Grafana (see Monitoring 33).

#### Analyzing Locust Results
Locust's web UI provides real-time graphs for:
- **RPS over time**
- **Latency distribution**
- **Request success rates**

#### Interpreting wrk Output
Example output:
```
Requests/sec:  12500
Transfer rate:  6250 MB/sec
Latency:
  50%   12 ms
  75%   15 ms
  95%   22 ms
  99%   30 ms
```

**Critical Insight**: Focus on P99 latency to avoid tail latency issues in production (see Performance 34).

---

## Scalability Testing Patterns

### Horizontal Scaling Tests
Test how your FastAPI application scales across multiple workers or servers:
```bash
# Run with 4 Uvicorn workers
uvicorn main:app --workers 4 --host 0.0.0.0 --port 8000
```

**Test Scenario**:
1. Start with 1 worker and increase concurrent users.
2. Add workers incrementally and measure RPS changes.
3. Identify diminishing returns (e.g., due to shared database connections).

### Asynchronous Endpoint Testing
Leverage FastAPI's async capabilities for I/O-bound tasks:
```python
from fastapi import FastAPI
import httpx

app = FastAPI()

@app.get("/async-data")
async def async_data():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://example.com/data")
        return response.json()
```

**When to Test Async**:
- APIs calling external APIs or databases.
- When CPU-bound tasks are offloaded to background workers.

---

## Best Practices for Production Testing

### 1. Start Small, Scale Gradually
Begin with low loads to establish a baseline, then increase concurrency in stages. This helps identify thresholds before breaking the system.

### 2. Simulate Real-World Workloads
Mirror production traffic patterns:
- Mix GET/POST/PUT/DELETE requests.
- Use realistic payload sizes and headers.

### 3. Monitor During Tests
Track application metrics in real time:
- Use Prometheus for time-series data.
- Monitor database query performance.
- Check for memory leaks (e.g., with `psutil` in Python).

### 4. Automate with CI/CD
Integrate load tests into pipelines to catch regressions early:
```yaml
# GitHub Actions example
jobs:
  load-test:
    steps:
      - run: locust --headless -u 1000 -r 100 -t 5m http://localhost:8000
```

---

## Real-World Use Cases

### Case Study: E-Commerce API
A FastAPI-based e-commerce backend needed to handle 10k concurrent users during a flash sale. Using Locust, the team simulated:

- 70% GET requests to fetch product details.
- 20% POST requests for adding to cart.
- 10% POST requests for checkout.

**Results**:
- Baseline: 1.2k RPS with P99 latency of 200ms.
- After scaling to 4 workers and optimizing database queries: 3.8k RPS with P99 latency of 45ms.

### Case Study: Real-Time Data Processing
A real-time analytics API using FastAPI's async routes was tested with wrk to handle 10k concurrent WebSocket connections. Key steps:
1. Used async database drivers (e.g., `asyncpg`).
2. Limited connection pools to prevent exhaustion.
3. Achieved 8.2k RPS with <50ms latency.

---

## Troubleshooting Common Pitfalls

### 1. Connection Limits
**Issue**: FastAPI returns 504 errors under load.  
**Solution**: Increase connection limits in the database or external services. For PostgreSQL:
```python
# Example: Use asyncpg with increased pool size
from asyncpg import create_pool

async def get_db():
    return await create_pool(min_size=5, max_size=20)
```

### 2. Memory Leaks
**Issue**: Memory usage grows during long tests.  
**Solution**: Use tools like `objgraph` or `memory_profiler` to trace leaks in dependencies.

### 3. Inaccurate Test Results
**Issue**: Locust reports high RPS but users experience slowness.  
**Solution**: Check for caching in tests and disable it:
```bash
hey -H "Cache-Control: no-cache" ...
```

---

## Cross-Framework Comparisons

| Tool       | Best For                | Async Support | Realistic Scenarios | Learning Curve |
|------------|-------------------------|---------------|---------------------|----------------|
| **Locust** | Python-based testing    | Yes           | High                | Low            |
| **wrk**    | High-throughput testing | Limited       | Medium              | Medium         |
| **hey**    | Quick benchmarks        | No            | Low                 | Low            |

---

## Conclusion

Load testing and benchmarking are critical for ensuring FastAPI applications perform reliably under real-world conditions. By combining tools like Locust, hey, and wrk with careful analysis of performance metrics, teams can identify bottlenecks, optimize resource usage, and validate scalability. Always align tests with production workloads and integrate testing into CI/CD pipelines for continuous performance validation. For deeper insights into optimization strategies, refer to the Performance documentation (34) and Monitoring documentation (33).