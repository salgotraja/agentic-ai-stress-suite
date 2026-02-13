# Async Validators and I/O

Modern applications often need to validate user inputs against external systems—such as checking if an email is already registered by querying a database or ensuring a username is unique via an external API. With Pydantic, async validation enables you to integrate such I/O-bound operations into your validation pipeline efficiently and without blocking the event loop.

This document explores how to leverage Pydantic's async validation capabilities, particularly in the context of external API calls, database checks, and concurrency management like rate limiting. The goal is to provide a production-ready, scalable approach for handling async validation in real-world applications.

---

## Understanding Async Validation in Pydantic

Pydantic supports async validation through the use of `@field_validator` and `@model_validator` decorated with `mode='after'` or `mode='before'`, and by using `@model_validator(mode='after')` for model-level validation. These validators can be defined as `async def` functions, allowing them to perform non-blocking I/O.

This is particularly useful in frameworks like FastAPI, where async routes and models can benefit from concurrent I/O.

---

## Async Uniqueness Checks

A common use case for async validation is ensuring the uniqueness of a field, such as an email or username. This typically involves a database lookup or API call to confirm that the value is not already taken.

Here’s an example of using an async field validator to check if an email is unique:

```python
from pydantic import BaseModel, field_validator
import asyncio
import httpx

class UserCreateRequest(BaseModel):
    email: str
    name: str

    @field_validator('email')
    @classmethod
    async def check_email_unique(cls, v: str) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://api.example.com/users/email/{v}")
            if response.status_code == 200:
                raise ValueError("Email already exists")
        return v
```

### Key Considerations:

- **Asynchronous HTTP Clients**: Libraries like `httpx` provide async support for external API calls.
- **Error Handling**: Ensure the validator raises `ValueError` or `ValidationError` for consistent error handling.
- **Circuit Breakers**: In production systems, consider using a circuit breaker pattern to prevent cascading failures during API outages.

---

## Model-Level Async Validation

Sometimes validation depends on multiple fields or requires access to the full model. Pydantic allows for model-level validation via `@model_validator`.

For example, checking if a password and a confirmation password match, and ensuring the username is available via an API:

```python
from pydantic import BaseModel, model_validator, ValidationInfo, Field
import asyncio
import httpx

class UserRegistrationModel(BaseModel):
    name: str
    email: str
    password: str
    password_confirm: str

    @model_validator(mode='after')
    async def check_password_match_and_username_available(self):
        if self.password != self.password_confirm:
            raise ValueError("Passwords do not match")
        if len(self.name) < 3:
            raise ValueError("Name must be at least 3 characters")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://api.example.com/users/name/{self.name}")
            if response.status_code == 200:
                raise ValueError("Username already taken")
        return self
```

### Best Practices:

- **Model-level validation** is ideal for complex checks that require multiple fields.
- **Avoid I/O in `__init__` or `__post_init__`**—prefer using async validators.
- **Use async clients** for all external service calls to maintain non-blocking behavior.

---

## Rate Limiting and Concurrency Control

When making external API calls, especially in high-throughput systems, it's essential to manage concurrency and rate limits. Pydantic validators can be wrapped in rate-limiting logic or throttled using semaphores.

Here’s an example using an async semaphore to control concurrent API calls:

```python
from pydantic import BaseModel, field_validator
import asyncio
import httpx

class EmailValidatorModel(BaseModel):
    email: str

    @field_validator('email')
    @classmethod
    async def validate_email_uniqueness(cls, v: str) -> str:
        # Create a shared semaphore (e.g., per instance or globally)
        SEMAPHORE = asyncio.Semaphore(2)  # Allow 2 concurrent calls
        
        async with SEMAPHORE:
            async with httpx.AsyncClient() as client:
                response = await client.get(f"https://api.example.com/users/email/{v}")
                if response.status_code == 200:
                    raise ValueError("Email already exists")
        return v
```

### Why It Matters:

- **Rate limiting** prevents API abuse and ensures stability during high load.
- **Semaphore usage** avoids exceeding API quotas and ensures fair resource distribution.
- **Error recovery** should be considered: retries with exponential backoff are often necessary.

---

## Async Validation with FastAPI

When combined with FastAPI, Pydantic models can be used directly in async routes. This makes it easy to build scalable APIs with integrated async validation.

Example FastAPI route using the `UserCreateRequest` model:

```python
from fastapi import FastAPI
from pydantic import BaseModel, field_validator
import httpx

app = FastAPI()

class UserCreateRequest(BaseModel):
    email: str

    @field_validator('email')
    @classmethod
    async def check_email_unique(cls, v: str) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.get(f"https://api.example.com/users/email/{v}")
            if response.status_code == 200:
                raise ValueError("Email already exists")
        return v

@app.post("/users")
async def create_user(user: UserCreateRequest):
    return {"email": user.email, "message": "User created"}
```

### Integration Tips:

- **Ensure FastAPI is configured for async**: Use `async def` for route handlers.
- **Leverage dependency injection** for shared clients or services.
- **Use Uvicorn or Hypercorn** as ASGI servers for async support.

---

## Best Practices for Async Validation

### 1. Use Async for External I/O Only
Async validation should be reserved for I/O-bound operations. CPU-bound validation should remain synchronous for clarity and performance.

### 2. Avoid Overfetching
Make sure each async validation call is minimal and purpose-specific. For example, validate one field at a time unless multiple fields must be checked together.

### 3. Implement Timeouts
Always set timeouts for external API calls. This prevents hanging requests from blocking the entire system.

### 4. Cache Where Appropriate
Caching can reduce the number of external calls, especially for frequently checked values like usernames.

### 5. Handle Errors Gracefully
Async validators should raise `ValueError` or `PydanticUserError` with clear, actionable messages.

### 6. Combine with Business Logic
Async validation is not a substitute for business logic. Ensure all rules are enforced both at the validation and business logic levels.

---

## Troubleshooting and Common Pitfalls

### 1. Blocking Calls in Async Validators
Using synchronous HTTP clients (like `requests`) in async validators is a common mistake. Always use `httpx` or similar async clients.

### 2. Missing Await in Validators
If you forget to `await` the validator function, the code will not perform the async call, leading to subtle bugs.

### 3. Overusing Async Validation
Async validation is not always necessary. For in-memory or local checks (e.g., checking password length), sync validation is more efficient.

### 4. Inconsistent Error Messages
Ensure all async validators raise consistent error types and messages to ensure compatibility with error handling and user interfaces.

### 5. Rate Limiting and Retry Logic
Without proper rate limiting and retry logic, async validation can lead to API rate-limiting and cascading failures. Implement retry strategies with exponential backoff for production use.

---

## Real-World Use Cases

### User Registration with Unique Constraints
During user registration, async validation ensures that emails and usernames are unique before persisting data.

### Integration with External Services
For example, validating a payment gateway transaction by calling an external API to confirm the payment status.

### Bulk Validation with Batching
In bulk upload scenarios, async validation can be used to validate each entry concurrently, significantly reducing processing time.

---

## Conclusion

Async validation in Pydantic enables powerful, scalable validation workflows that integrate seamlessly with external systems. By leveraging async validators, developers can ensure data integrity without blocking the event loop, making it ideal for high-throughput applications built with frameworks like FastAPI.

Whether it's checking for email uniqueness, validating against a third-party API, or managing rate limits, async validation provides the tools needed to build robust, production-ready applications. With careful implementation and best practices, async validation becomes an essential part of your data validation toolkit.