# Path Parameters

Path parameters are a key mechanism in RESTful API design for identifying resources uniquely within an API's URL structure. In the context of FastAPI, path parameters allow route paths to include variable segments, which are then extracted and passed into the route handler for processing. These parameters are crucial for defining endpoints that interact with specific resources, such as retrieving a user by their ID or accessing an item by its unique identifier.

FastAPI extends the functionality of path parameters by integrating **type validation** and **path converters**, enabling developers to enforce data types and custom validation rules directly in the URL path. This results in cleaner code and more robust APIs that are less prone to invalid input.

---

## Path Parameter Basics

In FastAPI, path parameters are defined using curly braces `{}` in the route path. These are captured from the incoming request URL and passed into the function signature of the route handler. Here's a basic example:

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/items/{item_id}")
async def read_item(item_id: str):
    return {"item_id": item_id}
```

In this example, `item_id` is a path parameter captured as a string. FastAPI automatically maps URL segments to the function parameters.

---

## Type Validation and Path Converters

FastAPI allows type validation on path parameters by declaring the type in the function signature. This is not just for convenience—it provides automatic validation and error responses when the input does not match the expected type.

### Integer Path Parameter

If you expect a numeric ID in the path, you can declare it as an `int`:

```python
@app.get("/users/{user_id}")
async def get_user(user_id: int):
    return {"user_id": user_id}
```

FastAPI will return a `422 Unprocessable Entity` if the path includes a non-integer value for `user_id`, such as `/users/abc`.

---

### UUID Path Parameter

For globally unique identifiers, such as UUIDs, FastAPI supports the `uuid` type from the `uuid` module:

```python
from uuid import UUID

@app.get("/resources/{resource_id}")
async def get_resource(resource_id: UUID):
    return {"resource_id": str(resource_id)}
```

This ensures that only valid UUID strings are accepted. Invalid UUIDs will result in an error response.

---

### Enum Path Parameter

You can restrict path parameters to a predefined set of values using `Enum` from the standard library:

```python
from enum import Enum
from fastapi import FastAPI

class Status(str, Enum):
    active = "active"
    inactive = "inactive"
    pending = "pending"

app = FastAPI()

@app.get("/tasks/{status}")
async def get_tasks_by_status(status: Status):
    return {"status": status.value}
```

This ensures that only one of the defined enum values can be used in the path. Any other value will trigger a `422` error.

---

## Custom Path Converters

While FastAPI supports built-in types like `int`, `str`, and `UUID`, it also allows the creation of **custom path converters** for more complex use cases. For instance, you might want to accept a date in the path and convert it into a `datetime` object for processing.

```python
from datetime import datetime
from fastapi import Path, FastAPI

app = FastAPI()

def parse_date(value: str) -> datetime:
    try:
        return datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise ValueError(f"Invalid date format: {value}")

@app.get("/events/{date}")
async def get_events(date: datetime = Path(..., description="The date of the event", parser=parse_date)):
    return {"date": date.strftime("%Y-%m-%d")}
```

This example uses a custom path parser via the `parser` argument in the `Path` model. However, note that this is not part of default FastAPI functionality and may require extensions or middleware to support. A more standard approach is to use query parameters for complex parsing, as shown in cross-reference 03.

---

## Combining Path and Query Parameters

In many real-world APIs, it's common to combine path and query parameters. For example, you might retrieve a user by ID and filter their orders by status:

```python
@app.get("/users/{user_id}/orders")
async def get_user_orders(user_id: int, status: str = None):
    return {"user_id": user_id, "status": status}
```

This route uses both a path parameter (`user_id`) and a query parameter (`status`). FastAPI handles both seamlessly with built-in validation and optional parameters.

---

## Best Practices

### Use Path Parameters for Identifiers

Path parameters should be used when the parameter is part of the *resource identifier*. For example, `/users/123` should use a path parameter for the `user_id`. Avoid using path parameters for filtering unless the filter is part of the resource hierarchy.

### Keep Path Parameters Simple

Avoid using path parameters for complex or multiple values. Instead, use query parameters for additional filters or sorting. This maintains a clean and predictable API structure.

### Validate Early and Clearly

Use FastAPI's type validation to your advantage. Declaring types in path parameters helps prevent invalid input from reaching the business logic. This reduces error handling complexity further down the call stack.

---

## Troubleshooting Common Issues

### Invalid Path Parameter Errors

When a user passes an invalid type in a path parameter (e.g., a string where an integer is expected), FastAPI automatically returns a `422` response with a detailed error message. You can customize these messages using `Path` or `Field` from `pydantic`.

### Conflicting Route Patterns

FastAPI's routing system is based on matching patterns. If two routes have conflicting paths (e.g., `/items/{item_id}` and `/items/create`), the second route must be defined first. Otherwise, the path parameter route may consume the `/create` URL as a parameter.

---

## Cross-Reference and Real-World Use Cases

### Query Parameters (03)

While path parameters are used for resource identifiers, query parameters are ideal for filtering, sorting, and pagination. For example:

```
GET /users?role=admin&sort=name
```

This route can be combined with a path parameter to retrieve a list of users filtered by role.

### Request Validation (12)

FastAPI's request validation system works seamlessly with path parameters. When a path parameter fails validation, the error is automatically captured and returned in a structured format.

---

## Comparison with Other Frameworks

In comparison to Flask or Django, FastAPI's path parameter handling is more robust and type-safe. Django REST framework, for example, uses URL patterns and view functions, which can become verbose when dealing with multiple types. Flask requires manual parsing or extensions for similar functionality.

---

## Summary

Path parameters are a foundational concept in REST APIs and are essential for building scalable and maintainable web services. FastAPI elevates their use with built-in type validation, enum support, and custom path converters, providing a clean and secure way to handle input directly in the URL path.

By combining path parameters with query parameters and leveraging FastAPI's validation system, you can build APIs that are both powerful and easy to use.

Always validate path parameters early, keep route patterns simple, and use tools like enums and UUIDs where appropriate. This leads to more robust and predictable APIs that are less error-prone in production environments.