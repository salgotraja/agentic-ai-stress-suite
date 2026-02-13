# CORS Configuration Advanced in FastAPI

Cross-Origin Resource Sharing (CORS) is a critical security mechanism that controls how web browsers handle requests from one domain to another. In FastAPI, CORS is managed via Starlette's `CORSMiddleware`, but advanced configurations require a deep understanding of preflight requests, credentials, allowed origin patterns, and security trade-offs. This guide explores production-ready patterns, security implications, and best practices for advanced CORS setups.

---

## Preflight Requests and Their Role

Before browsers send sensitive HTTP requests (e.g., `POST`, `PUT`, or requests with custom headers), they first send a **preflight request** using the `OPTIONS` method to check if the server allows the actual request. This preflight mechanism is a cornerstone of CORS compliance.

### How FastAPI Handles Preflights

FastAPI automatically handles preflight requests when `CORSMiddleware` is configured. You must explicitly define allowed HTTP methods and headers to avoid unexpected rejections.

### Example Configuration
```python
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Configure allowed methods and headers
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://example.com", "https://trusted-subdomain.example.com"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Custom-Header"],
    allow_credentials=True,
)
```

**Key Parameters**:
- `allow_methods`: Define HTTP methods explicitly. Avoid `["*"]` for `POST/PUT` endpoints unless absolutely necessary.
- `allow_headers`: Specify custom headers. Omitting required headers will cause preflights to fail.
- `max_age`: Set a cache duration (in seconds) for preflight responses to reduce redundant `OPTIONS` calls. Example: `max_age=3600` caches preflights for one hour.

**Why It Matters**: Preflight handling ensures your API rejects malicious requests before they execute, reducing attack surfaces.

---

## Credentials and Trust Boundaries

When clients need to send cookies, authentication headers, or HTTP authentication, CORS requires `allow_credentials` to be enabled. However, this introduces **security risks** if not paired with strict origin validation.

### Enabling Credentials
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://trusted-app.com"],
    allow_credentials=True,
)
```

**Critical Restrictions**:
- **Never use `allow_origins=["*"]` with `allow_credentials=True`**. This combination is invalid and rejected by browsers.
- Validate origins against a **whitelist** to prevent credential theft attacks.

### Real-World Use Case
A Single Sign-On (SSO) system where a FastAPI backend must accept authenticated requests from a frontend hosted at `https://app.sso.com`. Credentials are required for session management.

---

## Allowed Origins Patterns and Security Trade-Offs

The `allow_origins` parameter is the most sensitive part of CORS configuration. Improper patterns can expose your API to cross-site request forgery (CSRF) or data leakage.

### Secure Origin Whitelisting
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://app.example.com",
        "https://api.example.com",
        "https://*.example.com",  # Allow all subdomains
    ],
    allow_origin_regex=r"^https://(.*\.)?example\.com$",
)
```

**Patterns and Wildcards**:
- Use `allow_origin_regex` for complex patterns. Example: `r"^https://(dev|prod)\.internal-api\.com$"` for environment-specific access.
- Avoid `["*"]` unless your API is public and requires no authentication.

### Security Implications
Allowing untrusted origins can lead to:
- **CSRF Attacks**: Malicious sites trick users into executing unintended actions.
- **Data Exfiltration**: Browsers may leak sensitive response data to unauthorized domains.

---

## Production-Ready CORS Setup

A robust production configuration balances accessibility and security. Here's a template for a high-traffic API:

### Full Configuration Example
```python
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Load allowed origins from environment variables
ALLOWED_ORIGINS = os.getenv("ALLOWED_ORIGINS", "").split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-Request-ID"],
    allow_credentials=False,  # Only enable for trusted apps
    max_age=600,  # Cache preflights for 10 minutes
)
```

**Environment Configuration**:
- Store `ALLOWED_ORIGINS` in a secure secret management system (e.g., HashiCorp Vault, AWS Secrets Manager).
- Use CI/CD pipelines to inject values at deployment time.

---

## Advanced Security Considerations

### 1. **Origin Validation**
Always validate incoming origins against a whitelist. Never dynamically allow origins based on user input.

```python
from fastapi import Request, HTTPException

@app.middleware("http")
async def validate_origin(request: Request, call_next):
    origin = request.headers.get("Origin")
    if origin and origin not in ALLOWED_ORIGINS:
        raise HTTPException(status_code=403, detail="Forbidden")
    response = await call_next(request)
    return response
```

### 2. **Preflight Request Debugging**
Preflight failures are often silent. Enable logging to capture invalid requests:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
```

### 3. **Cross-Framework Comparison**
- **Express.js**: Uses `cors` middleware with similar options (`origin`, `credentials`, `methods`).
- **FastAPI/Starlette**: Leverages the same middleware as Django and other ASGI apps, ensuring consistency across the Python ecosystem.

---

## Best Practices for Real-World APIs

| Practice                     | Rationale                                                                 |
|------------------------------|---------------------------------------------------------------------------|
| **Use HTTPS-only origins**   | Prevents downgrade attacks and ensures encrypted communication.         |
| **Limit `allow_headers`**  | Reduces attack surface by rejecting unexpected headers.                 |
| **Disable `allow_credentials` unless required** | Avoids credential exposure risks.                                     |
| **Audit origins quarterly**  | Ensure new domains are added only after security review.                |
| **Use `Vary: Origin` header** | Helps browsers cache responses correctly for different origins.           |

---

## Troubleshooting Common Issues

### Problem: `No 'Access-Control-Allow-Origin' header present`
- **Cause**: Middleware not added, or `allow_origins` doesn't match the client's origin.
- **Fix**: Verify middleware is added **before** route definitions.

### Problem: `The value of the 'Access-Control-Allow-Origin' header is invalid`
- **Cause**: `allow_credentials=True` with `allow_origins=["*"]`.
- **Fix**: Replace `*` with a specific origin or enable credentials cautiously.

### Problem: Preflight fails with `403 Forbidden`
- **Cause**: `OPTIONS` method not allowed for the requested endpoint.
- **Fix**: Ensure all routes support required methods or define global defaults.

---

## Edge Cases and Error Handling

### 1. **Dynamic Origin Allowance**
For APIs integrated with multiple SaaS clients, use regex patterns instead of hardcoding origins:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"^https://tenant-\w+\.api\.example\.com$",
)
```

### 2. **CORS with Proxies**
If your API sits behind a reverse proxy (e.g., NGINX, Cloudflare), ensure the proxy forwards the `Origin` header correctly. Misconfigurations here can lead to origin validation failures.

### 3. **CORS and WebSockets**
WebSockets use a different handshake (`Sec-WebSocket-Origin`) that CORS middleware does **not** handle. Implement additional validation for WebSocket connections.

---

## Conclusion

Advanced CORS configuration in FastAPI requires balancing accessibility with security. By carefully managing preflight responses, credentials, and origin patterns, you can protect your API from cross-origin attacks while maintaining compatibility with modern web clients. Always treat CORS as a critical security layer, not an afterthought, and follow the principles of least privilege and defense in depth.

For deeper insight into FastAPI middleware mechanics, refer to section [Middleware (07)](#). For broader security strategies, see [Security (10)](#).