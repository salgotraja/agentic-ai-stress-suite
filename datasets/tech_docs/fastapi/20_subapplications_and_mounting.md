# Sub-Applications and Mounting

In the context of FastAPI applications, the concept of sub-applications and mounting is essential for modular and scalable API development. It allows developers to break down large APIs into smaller, self-contained components—often referred to as sub-applications or modular routers. These sub-applications can be developed, tested, and maintained independently, and then mounted into the main FastAPI app using path prefixes, creating a cohesive API structure.

Mounting sub-applications is typically done using the `FastAPI` instance's `.mount()` method or the `APIRouter` object's ability to be included under a specific path prefix. This modular approach aligns with advanced routing patterns and supports architectural strategies like microservices, domain-driven design, and BFF (Backend for Frontend) patterns.

This document explores how to organize applications using sub-applications and `APIRouter`, with practical examples for modular API organization, and discusses when and why to use such an approach.

## Modular API Organization with APIRouter

The `APIRouter` class in FastAPI is the primary tool for modularizing API routes. It acts as a sub-application that can be included into a main application under a specific path prefix. This allows you to separate routes based on functionality, domain, or team ownership.

Here is a basic example of modular API structure using `APIRouter`:

```python
from fastapi import APIRouter, FastAPI

# Create a router for user-related endpoints
user_router = APIRouter()

@user_router.get("/profile")
def get_user_profile():
    return {"message": "User Profile"}

@user_router.post("/login")
def login_user():
    return {"message": "Login Successful"}

# Create another router for product-related endpoints
product_router = APIRouter()

@product_router.get("/all")
def get_all_products():
    return {"message": "All Products"}

@product_router.get("/{product_id}")
def get_product(product_id: int):
    return {"message": f"Product {product_id}"}

# Main application
app = FastAPI()

# Include routers with path prefixes
app.include_router(user_router, prefix="/user", tags=["User"])
app.include_router(product_router, prefix="/products", tags=["Product"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
```

In this example, two routers are created: one for the user domain and one for the product domain. These routers are then included into the main FastAPI application using `include_router()`. Each router is associated with a prefix (`/user` and `/products`, respectively), ensuring that all routes defined in the router are prefixed accordingly.

### Benefits of Modular API Organization

1. **Decoupling**: Each router can be developed and maintained independently, reducing the complexity of the main application.
2. **Reusability**: Routers can be reused across projects or services, especially in microservice architectures.
3. **Scalability**: Large applications can be scaled by adding more routers without bloating a single file.
4. **Team Collaboration**: Different teams can own different routers, promoting parallel development.

## Mounting Sub-Applications

In addition to `APIRouter`, FastAPI also supports the concept of mounting sub-applications. This is useful when you want to create entirely separate API versions or microservices under a single domain or domain prefix.

For instance, you can have a separate FastAPI application for a v1 API and another for v2, both mounted under different paths.

```python
from fastapi import FastAPI

# Sub-application for v1 API
app_v1 = FastAPI()

@app_v1.get("/items")
def get_items_v1():
    return {"version": "1", "items": ["item1", "item2"]}

@app_v1.get("/items/{item_id}")
def get_item_v1(item_id: int):
    return {"version": "1", "item_id": item_id}

# Sub-application for v2 API
app_v2 = FastAPI()

@app_v2.get("/items")
def get_items_v2():
    return {"version": "2", "items": ["itemA", "itemB"]}

@app_v2.get("/items/{item_id}")
def get_item_v2(item_id: int):
    return {"version": "2", "item_id": item_id}

# Main application
main_app = FastAPI()

# Mount sub-applications with a path prefix
main_app.mount("/v1", app_v1)
main_app.mount("/v2", app_v2)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(main_app, host="0.0.0.0", port=8000)
```

In this case, the `main_app` mounts two separate FastAPI instances (`app_v1` and `app_v2`) under the `/v1` and `/v2` endpoints, respectively. This is useful for versioning APIs, or for isolating microservices that have different dependencies or middleware requirements.

### When to Use Mounting vs. APIRouter

| Use Case                          | Recommended Approach |
|-----------------------------------|----------------------|
| Separating by domain or feature   | APIRouter            |
| Versioning APIs                   | Mounting             |
| Microservices under a single domain | Mounting             |
| Centralized middleware per sub-app | Mounting             |

Mounting is suitable when the sub-application is a self-contained service or versioned endpoint. APIRouter is better suited for modularizing a single API domain, such as users, products, etc.

## Best Practices for Sub-Applications and Mounting

### 1. Use APIRouter for Domain-Based Modularization

Break your application by business logic or domain. For example, have routers for authentication, inventory, and billing. This promotes clarity and separation of concerns.

### 2. Avoid Over-Mounting

While mounting is powerful, avoid mounting too many sub-applications unless necessary. Each mounted application introduces overhead in middleware and middleware order. If the sub-applications are not completely independent, prefer `APIRouter`.

### 3. Prefix Consistency

Ensure that all sub-applications and routers use a consistent naming and versioning strategy. This helps in generating accurate OpenAPI documentation and simplifies routing.

### 4. Middleware and Dependencies

Sub-applications can have their own middleware and dependencies. When mounting multiple applications, be cautious about middleware order and shared dependencies. Middleware from the main app runs before sub-app middleware.

### 5. Error Handling

Each sub-application can define custom exception handlers. If not, errors will propagate to the main application’s exception handlers. Be consistent in your error handling strategy across all mounted components.

### 6. Documentation and Tagging

Use the `tags` parameter when including routers to categorize endpoints in the OpenAPI documentation. This improves developer and API client experience.

### 7. Testing

When testing modularized applications, ensure that each router and mounted application can be tested in isolation. This can be facilitated using pytest fixtures that instantiate the routers or sub-applications.

### 8. Versioning Strategy

If using mounting for API versions, consider adopting a semantic versioning strategy. Avoid using numeric versioning that may become obsolete quickly.

### 9. Shared Dependencies and Services

For shared services or dependencies (e.g., a database connection, a rate limiter), consider placing them at the main application level or using dependency injection patterns that allow reuse across sub-applications.

## Troubleshooting and Common Pitfalls

### 1. Path Conflicts

When mounting sub-applications or including routers, ensure that no conflicting paths are defined. FastAPI will raise an error if two routes have the same path and method.

### 2. Middleware Order

When mounting multiple sub-applications, the order in which they are mounted affects the order in which middleware is applied. Sub-application middleware is applied after the main app's middleware.

### 3. OpenAPI Conflicts

If multiple routers define the same operation with the same path and method, the last one included will override the previous definitions. Use tags and route descriptions to avoid ambiguity.

### 4. Dependency Injection Issues

When using dependency injection across sub-applications, ensure that dependencies are correctly scoped and that there are no circular dependencies between components.

## Comparisons with Other Frameworks

In comparison to frameworks like Flask or Django, FastAPI’s `APIRouter` and mounting capabilities provide more granular control over component isolation and modular API development. Unlike Flask’s blueprint system, FastAPI’s `APIRouter` supports async functions by default and integrates cleanly with Pydantic models.

Mounting in FastAPI is similar to Django’s `include()` function or Flask’s blueprint mounting, but with the added benefit of being fully asynchronous and type-safe.

## Real-World Use Case: Microservices in a Monorepo

Consider a scenario where a company operates multiple microservices under a single domain. Each team owns a sub-service: authentication, inventory, and billing. These can be developed as separate FastAPI applications and mounted under `/auth`, `/inventory`, and `/billing` in a central FastAPI gateway application.

This allows for modular development, centralized routing, and consistent error handling and middleware across services.

In conclusion, sub-applications and mounting in FastAPI are powerful tools for managing large-scale API development. By structuring your code using `APIRouter` and `mount()`, you can create scalable, maintainable, and modular APIs that align with modern software development practices.