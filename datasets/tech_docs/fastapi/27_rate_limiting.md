# Rate Limiting

Rate limiting is a crucial mechanism used in scalable web applications to control the number of requests a client can make within a specific time window. It helps prevent abuse, ensures fair usage, and protects backend systems from potential denial-of-service (DoS) attacks. In the context of web frameworks like FastAPI, implementing rate limiting effectively is essential for maintaining performance, security, and user experience.

This documentation explores various rate limiting strategies including token bucket and sliding window, and provides practical examples using in-memory and Redis-based implementations. It also covers how to extend these patterns for distributed systems.

---

## Key Rate Limiting Strategies

### Token Bucket Algorithm

The token bucket algorithm allows requests to be processed at a steady rate, even if they arrive in bursts. It works by maintaining a "bucket" of tokens. Each request consumes a token, and tokens are refilled at a set rate. If the bucket is empty, requests are denied until tokens become available.

**Advantages**:
- Handles bursty traffic by allowing temporary spikes within limits.
- Easy to implement.

**Example Use Case**: A payment API might use token bucket to allow a burst of transactions during peak hours but still enforce a maximum throughput.

```python
from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.middleware import Middleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPI
from starlette.responses import JSONResponse

app = FastAPI()
limiter = Limiter(key_func=get_remote_address)

@app.get("/token-bucket")
@limiter.limit("10/minute")
async def token_bucket(request: Request):
    return JSONResponse(content={"status": "success", "message": "Token bucket limit applied"})
```

### Sliding Window Log

The sliding window algorithm tracks all requests and enforces limits over a rolling window of time. Unlike fixed window counters, sliding window avoids the "spike" issue that occurs at the start of a new window.

**Advantages**:
- Prevents abuse during window transitions.
- More accurate in high-traffic scenarios.

**Example Use Case**: An authentication endpoint might use sliding window to prevent brute force attacks.

```python
from datetime import datetime, timedelta

class SlidingWindowLimiter:
    def __init__(self, limit: int, window: int):  # window in seconds
        self.limit = limit
        self.window = window
        self.requests = []

    def check_limit(self, ip: str):
        now = datetime.now()
        self.requests = [req for req in self.requests if now - req < timedelta(seconds=self.window)]
        if len(self.requests) >= self.limit:
            return True  # Rate limit exceeded
        self.requests.append(now)
        return False
```

To integrate this with FastAPI, you can create a middleware to inspect the client IP and apply this logic.

```python
from fastapi import FastAPI, Request, Response
from fastapi.middleware.base import BaseHTTPMiddleware

app = FastAPI()

class SlidingWindowMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: FastAPI):
        super().__init__(app)
        self.limiter = SlidingWindowLimiter(limit=5, window=60)  # 5 requests per minute

    async def dispatch(self, request: Request, call_next):
        ip = request.client.host
        if self.limiter.check_limit(ip):
            return Response(status_code=429, content="Too Many Requests")
        response = await call_next(request)
        return response

app.add_middleware(SlidingWindowMiddleware)
```

---

## In-Memory Rate Limiting in FastAPI

For small-scale applications or local development, in-memory rate limiting is often sufficient. FastAPI supports in-memory rate limiting using libraries like `slowapi`, which provides decorators for applying rate limits to routes.

```python
from fastapi import FastAPI
from slowapi import Limiter
from slowapi.util import get_remote_address

app = FastAPI()
limiter = Limiter(key_func=get_remote_address)

@app.get("/")
@limiter.limit("10/minute")
async def root():
    return {"message": "Rate limiting applied in memory"}
```

**Considerations**:
- In-memory rate limiting does not persist across server restarts.
- Not suitable for distributed environments unless all workers share the same memory space (e.g., using `gunicorn` with a single worker).

---

## Redis-Based Rate Limiting

Distributed applications require a shared, persistent store to track rate limiting across multiple nodes. Redis is a popular choice due to its fast key-value operations and built-in support for atomic increments and TTLs.

### Using Redis with FastAPI

Here’s an example using Redis alongside `slowapi` to implement rate limiting across a distributed cluster:

```python
from slowapi import Limiter
from slowapi.stores.redis import RedisStore
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI, Depends
import os
import redis

app = FastAPI()

# Connect to Redis
redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")
redis_client = redis.from_url(redis_url)
store = RedisStore(redis_client)
limiter = Limiter(key_func=get_remote_address, storage=store)

app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)

@app.get("/secure-endpoint")
@limiter.limit("10/minute")
def secure_endpoint():
    return {"message": "This is a secure endpoint with Redis-based rate limiting"}
```

**Key Features**:
- Uses Redis atomic operations for thread safety.
- Configurable rate limits per user, IP, or route.
- Centralized tracking across multiple instances.

---

## Custom Rate Limiting Strategies

In some cases, the built-in strategies may not meet your needs. FastAPI allows full customization of rate limiting logic by defining custom key functions or using middleware.

### Per-User Rate Limiting

If your API requires authentication, you can base rate limits on the user ID instead of the IP address.

```python
from fastapi import Depends, FastAPI, HTTPException, Request
from slowapi import Limiter
import uuid

app = FastAPI()

def get_user_id(request: Request):
    # In a real app, this would get the authenticated user ID
    return request.headers.get("X-User-ID", "anonymous")

limiter = Limiter(key_func=get_user_id)

@app.get("/user-specific")
@limiter.limit("100/day", "20/hour")
async def user_specific(request: Request):
    return {"message": "User-specific rate limiting"}
```

### Exponential Backoff for Retry Logic

When clients exceed rate limits, it’s recommended to return a `429 Too Many Requests` response and include `Retry-After` header to guide clients on when to retry.

```python
@app.get("/retryable")
@limiter.limit("5/minute")
async def retryable(request: Request):
    return JSONResponse(content={"message": "Try again later"}, headers={"Retry-After": "60"})
```

---

## Distributed Rate Limiting with Redis

For microservices or cloud-deployed applications, Redis provides a shared store for rate limiting across multiple instances.

### Redis Cluster Considerations

- Ensure Redis is configured for high availability (e.g., using Redis Cluster).
- Use Redis pipelines for efficient batch operations.
- Set appropriate timeouts to avoid stale locks.

```python
from redis import Redis
from redis.exceptions import ConnectionError

redis_url = os.getenv("REDIS_URL", "redis://redis-cluster:6379")

try:
    redis_connection = Redis.from_url(redis_url)
except ConnectionError:
    raise RuntimeError("Unable to connect to Redis for rate limiting")
```

### Sharding for Performance

In very high-traffic scenarios, consider sharding rate limit buckets by user ID, endpoint, or other dimensions to reduce Redis contention.

```python
def get_key(ip: str, endpoint: str) -> str:
    return f"rate_limit:{ip}:{endpoint}"

# Example usage
key = get_key(ip, request.url.path)
redis_client.incr(key)
redis_client.expire(key, 60)  # Reset every minute
```

---

## Best Practices for Rate Limiting

### Choose the Right Strategy

- **Token bucket** is ideal for APIs that can tolerate bursty traffic.
- **Sliding window** is better for high-security services where strict limits are needed.
- **Redis-based** is the only viable option for distributed systems.

### Monitor and Alert

Set up monitoring for:
- Rate limit hit frequency.
- Redis connection health.
- Rate limit configuration drift.

```python
from prometheus_client import Counter

rate_limit_hits = Counter('rate_limit_hits_total', 'Total number of rate limit hits')

@app.middleware("http")
async def rate_limit_monitoring(request: Request, call_next):
    response = await call_next(request)
    if response.status_code == 429:
        rate_limit_hits.inc()
    return response
```

### Use Headers for Transparency

Always return the following headers in rate limit responses:
- `X-RateLimit-Limit`
- `X-RateLimit-Remaining`
- `X-RateLimit-Reset`
- `Retry-After`

These help clients understand their usage and avoid future violations.

### Test with Realistic Load

Use tools like `locust` to simulate traffic and verify that rate limits are enforced correctly.

---

## Troubleshooting Common Issues

### Rate Limits Not Applied

- Ensure the middleware is added before route handlers.
- Confirm that the key function (e.g., `get_remote_address`) is correctly implemented.
- Validate Redis connectivity for distributed setups.

### False Positives

- Misconfigured TTLs can cause stale rate limits.
- Use atomic operations (`INCR`, `EXPIRE`) to prevent race conditions.

### Performance Bottlenecks

- Use Redis pipelines for bulk operations.
- Avoid using locks unless necessary.
- Consider asynchronous Redis clients for non-blocking I/O.

---

## Cross-Framework Comparisons

| Framework     | Built-in Rate Limiting | Redis Support | Distributed Support |
|---------------|--------------------------|----------------|----------------------|
| **FastAPI**   | Yes (via `slowapi`)     | Yes            | Yes                  |
| **Flask**     | No (requires middleware)  | Yes            | Yes                  |
| **Express.js**| No (requires middleware)  | Yes            | Yes                  |

FastAPI provides a modern, Pythonic API and integrates seamlessly with Redis and middleware, making it a top choice for APIs requiring scalable rate limiting.

---

## Conclusion

Rate limiting is a fundamental part of building secure, performant web APIs. FastAPI provides powerful tools to implement both in-memory and Redis-based rate limiting using patterns like token bucket and sliding window. By understanding when and how to apply these strategies, you can build scalable, resilient applications that are resistant to abuse and misuse.

Always test your implementations under load, monitor for anomalies, and adapt your limits based on usage patterns. With thoughtful design and robust code, rate limiting becomes a powerful ally in maintaining service reliability and user trust.