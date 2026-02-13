# Dependencies - Dependency Injecting

In modern application development, especially when using Python-based frameworks like FastAPI, managing dependencies efficiently is a cornerstone of building scalable, testable, and maintainable applications. Dependency injection (DI) is a design pattern that allows us to decouple components by injecting their dependencies from the outside. This pattern is particularly powerful in web APIs where components such as database sessions, authentication systems, and configuration parameters are frequently reused across the codebase.

This document provides a deep dive into dependency injection in FastAPI, covering key concepts like reusable dependencies, dependency hierarchies, and advanced usage patterns. Through practical examples and best practices, we'll demonstrate how to manage dependencies effectively in a production-grade API.

---

## What is Dependency Injection?

Dependency injection is the practice of passing dependencies to a component rather than having the component create or locate them. This leads to loosely coupled, more testable, and modular systems.

In FastAPI, dependencies are often used to encapsulate logic that is reused across multiple endpoints, such as retrieving a database session, validating user authentication, or parsing query parameters.

---

## Key Concepts in FastAPI Dependency Injection

### Reusable Dependencies

FastAPI allows you to define dependencies as functions decorated with `Depends`, which can be reused across multiple routes. A reusable dependency is a function that returns an object or value and optionally performs side effects like validation or logging.

### Dependency Hierarchy

Dependencies can be nested, forming a hierarchy where one dependency depends on another. This allows for complex logic to be broken down into smaller, composable parts.

---

## Example: Database Sessions as a Reusable Dependency

A common scenario in web APIs is managing database sessions. Using FastAPI’s dependency system, we can ensure that a session is created per request, used throughout the endpoint, and properly closed afterward.

```python
from fastapi import Depends, FastAPI
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

app = FastAPI()

# Database setup
SQLALCHEMY_DATABASE_URL = "sqlite:///./test.db"
engine = create_engine(SQLALCHEMY_DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Dependency to get a database session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/items/")
def read_items(db: Session = Depends(get_db)):
    # Use `db` to query the database
    return {"status": "items retrieved"}
```

In this example, `get_db` is a generator-based dependency that yields a database session and ensures it is closed after the request is processed. This pattern is efficient and avoids potential resource leaks.

---

## Example: Authentication Dependency

Authentication is another common use case where dependency injection shines. Let’s create a basic token-based authentication dependency.

```python
from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

app = FastAPI()

# Simulated valid token
VALID_TOKEN = "super-secret-token"

# Define the API key header
api_key_header = APIKeyHeader(name="X-API-Key")

def get_current_user(api_key: str = Depends(api_key_header)):
    if api_key != VALID_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key",
        )
    return {"username": "john_doe"}

@app.get("/secure-data")
def get_secure_data(user: dict = Depends(get_current_user)):
    return {"message": f"Welcome, {user['username']}"}
```

This `get_current_user` function is a reusable dependency that validates the presence and correctness of an API key. It can be reused in any endpoint that requires authentication.

---

## Example: Configuration as a Dependency

Configuration values, such as API keys, database URLs, or feature toggles, often need to be injected into dependencies. Using environment variables and dependency injection ensures clean separation of configuration and logic.

```python
from fastapi import Depends, FastAPI
from pydantic import BaseSettings

app = FastAPI()

class Settings(BaseSettings):
    API_KEY: str
    DB_URL: str

    class Config:
        env_file = ".env"

def get_settings():
    return Settings()

@app.get("/config")
def get_config(settings: Settings = Depends(get_settings)):
    return {
        "api_key": settings.API_KEY,
        "db_url": settings.DB_URL
    }
```

This example leverages Pydantic for type-safe configuration loading. The `get_settings` dependency provides the `Settings` object to any route that needs access to environment variables.

---

## Advanced Dependency Patterns

### Dependency Hierarchies and Composition

Dependencies can be composed to form complex logic. For example, an endpoint may require both a valid API key and a valid user session.

```python
from fastapi import Depends, FastAPI, HTTPException, status

app = FastAPI()

def get_api_key(api_key: str = Depends(api_key_header)):
    if api_key != "valid-key":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid API Key")
    return api_key

def get_user(api_key: str = Depends(get_api_key)):
    # Simulate user lookup based on API key
    if api_key == "valid-key":
        return {"username": "admin"}
    raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")

@app.get("/protected")
def protected_route(user: dict = Depends(get_user)):
    return {"message": f"Hello {user['username']}"}
```

In this example, the dependencies form a chain: `get_user` depends on `get_api_key`, which in turn depends on the header. This modularity makes it easy to adjust or replace parts of the authentication logic without affecting the entire system.

---

## Error Handling in Dependencies

FastAPI allows dependencies to raise HTTP exceptions, which can halt the request processing and return an error response directly.

```python
from fastapi import Depends, FastAPI, HTTPException

app = FastAPI()

def validate_feature_flag(feature: str):
    if feature not in ["alpha", "beta", "stable"]:
        raise HTTPException(status_code=400, detail="Invalid feature flag")

@app.get("/feature/{feature}")
def get_feature(feature: str = Depends(validate_feature_flag)):
    return {"feature": feature}
```

Here, the `validate_feature_flag` dependency checks the validity of a feature flag. If invalid, it raises an HTTP 400 error immediately.

---

## Best Practices

### 1. Use Dependencies for Reusability

Any logic that is used across multiple endpoints should be encapsulated into a dependency. This includes database access, authentication, logging, and configuration.

### 2. Prefer Composition Over Inheritance

Compose dependencies using `Depends()` rather than creating monolithic functions. This allows for modular and composable logic.

### 3. Keep Dependencies Idempotent

Avoid side effects in dependencies unless they are critical to the request lifecycle (e.g., session creation). Side effects should be predictable and minimal.

### 4. Use Async Dependencies for Async Endpoints

When writing asynchronous routes, ensure dependencies are async-aware. For example:

```python
from fastapi import Depends, FastAPI
import httpx

app = FastAPI()

async def fetch_external_data():
    async with httpx.AsyncClient() as client:
        response = await client.get("https://api.example.com/data")
        return response.json()

@app.get("/external")
async def get_external_data(data: dict = Depends(fetch_external_data)):
    return data
```

### 5. Document Dependencies Clearly

Use docstrings or inline comments to explain what each dependency does, what it returns, and any exceptions it may raise.

### 6. Avoid Overusing Dependencies

While dependencies are powerful, overusing them can lead to performance issues or hard-to-debug code. Use them for shared logic, not for trivial tasks.

---

## Cross-Reference to Advanced Topics

- **Advanced Dependencies (15)**: For more complex scenarios like dependency overrides, sub-dependency resolution, and middleware integration, refer to the advanced section of the FastAPI documentation.
- **Security (10)**: For secure authentication and authorization patterns, see the security section, which includes OAuth2, JWT, and API key examples.

---

## Troubleshooting Common Dependency Issues

### 1. Dependency Not Being Called

Ensure the dependency is imported correctly and used with `Depends()` in the route. Circular imports can also prevent dependencies from being resolved.

### 2. Unexpected Behavior in Async Dependencies

If an async route uses a synchronous dependency, FastAPI will run it in the event loop, which should be fine. However, for performance, prefer async dependencies in async routes.

### 3. Stateful Dependencies

Avoid using mutable objects in dependencies without careful management. Use scoped dependencies (like the database session example) to ensure isolation between requests.

---

## Real-World Use Case: Multi-Tenant Application

Consider a multi-tenant application where each tenant has its own database schema or configuration. A reusable dependency can extract the tenant identifier from the request and inject the correct database session.

```python
from fastapi import Depends, FastAPI, Request
from sqlalchemy.orm import sessionmaker

app = FastAPI()

def get_tenant_session(request: Request):
    tenant_id = request.headers.get("X-Tenant-ID")
    if not tenant_id:
        raise HTTPException(400, "Missing tenant ID")
    # Simulate tenant-specific DB session
    return sessionmaker(bind=schema_to_engine(tenant_id))()

@app.get("/tenant/data")
def get_tenant_data(db: Session = Depends(get_tenant_session)):
    return db.query(...)
```

This setup allows a single API to serve multiple tenants using the same codebase, with tenant-specific dependencies injected at runtime.

---

## Conclusion

FastAPI’s dependency injection system is a powerful tool for building clean, modular, and testable APIs. By reusing dependencies across endpoints, encapsulating logic, and composing them into complex hierarchies, you can manage application complexity effectively.

Whether you're dealing with authentication, configuration, or database sessions, the patterns and examples in this document provide a solid foundation for building production-ready APIs. Always aim for clarity, testability, and separation of concerns when designing your dependencies.