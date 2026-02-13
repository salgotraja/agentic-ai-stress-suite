# Discriminated Unions

Discriminated unions, also known as tagged unions or sum types, are a powerful pattern in type systems that allow a type to represent a set of alternative forms. Each form is typically identified by a specific field called a *discriminator*, which allows the type system to infer the exact shape of the data. This pattern is particularly useful in scenarios involving API responses, event handling, and validation workflows where data can take on different forms depending on context.

In Python, Pydantic offers robust support for modeling these types through the use of `Union` and `TaggedUnion` constructs. This allows developers to build type-safe systems that reduce error-prone manual checks and enable clearer code structure.

---

## Core Concepts of Discriminated Unions

A discriminated union is a hybrid type that can represent one of several distinct data shapes. Each shape is identified by a *discriminator field*—a specific attribute whose value determines which type of data is present.

Pydantic simplifies the modeling of these types by using the `Union` keyword alongside `discriminator` metadata. When a field is annotated with `Union`, Pydantic can infer the correct type based on the value of the specified field.

### Example: Base Structure

```python
from pydantic import BaseModel, Field, TaggedUnion

class SuccessResponse(BaseModel):
    status: str = Field(default="success")
    data: dict

class ErrorResponse(BaseModel):
    status: str = Field(default="error")
    message: str

# Union of both types with 'status' as the discriminator
Response = TaggedUnion('status', {
    'success': SuccessResponse,
    'error': ErrorResponse
})
```

In this example, the `status` field serves as the *discriminator*. Depending on whether the value is `"success"` or `"error"`, Pydantic will instantiate the appropriate class.

---

## Type Narrowing and Runtime Behavior

Type narrowing is a key advantage of using discriminated unions. When the value of the discriminator is known, the type system can infer the rest of the structure, allowing for safe access to nested fields.

This is particularly useful in scenarios like API response parsing, event handling, or validation logic, where the shape of the data depends on the context.

### Example: API Response Handling

```python
from typing import Union
from pydantic import BaseModel, Field

class User(BaseModel):
    id: int
    name: str

class UserCreateSuccess(BaseModel):
    action: str = "create"
    status: str = "success"
    user: User

class UserCreateError(BaseModel):
    action: str = "create"
    status: str = "error"
    message: str

# Discriminated union on 'action' and 'status'
Response = TaggedUnion(('action', 'status'), {
    ('create', 'success'): UserCreateSuccess,
    ('create', 'error'): UserCreateError
})
```

At runtime, Pydantic uses the combination of `action` and `status` to determine the correct type:

```python
response_data = {
    "action": "create",
    "status": "success",
    "user": {"id": 123, "name": "Alice"}
}

response = Response(**response_data)
if isinstance(response, UserCreateSuccess):
    print(f"User created: {response.user.name}")
```

This pattern reduces the need for manual type checks and enables cleaner, more readable code.

---

## Event Type Handling with Discriminated Unions

Discriminated unions are also ideal for modeling event-driven systems where different types of events may trigger different behaviors.

### Example: Event Modeling

```python
from pydantic import BaseModel, Field, TaggedUnion

class LoginEvent(BaseModel):
    type: str = "login"
    user_id: int
    timestamp: float

class LogoutEvent(BaseModel):
    type: str = "logout"
    user_id: int
    timestamp: float

class ErrorEvent(BaseModel):
    type: str = "error"
    code: int
    message: str

Event = TaggedUnion('type', {
    'login': LoginEvent,
    'logout': LogoutEvent,
    'error': ErrorEvent
})
```

In this model, each event type is identified by the `type` field. This makes it easy to write handlers that can route events to appropriate functions.

```python
def handle_event(event: Event):
    if isinstance(event, LoginEvent):
        print(f"User {event.user_id} logged in at {event.timestamp}")
    elif isinstance(event, LogoutEvent):
        print(f"User {event.user_id} logged out at {event.timestamp}")
    elif isinstance(event, ErrorEvent):
        print(f"Error {event.code}: {event.message}")
```

---

## Best Practices for Discriminated Unions

### Use Discriminator Fields That Are Stable and Unique

The choice of a discriminator field is critical. It must be:

- **Stable**: Not subject to change unless the type changes.
- **Unique**: Each variant must have a distinct value for the discriminator.

For example, in the `ErrorResponse` and `SuccessResponse` example, the `status` field is a good candidate because it is consistent and clearly identifies the type of the response.

### Favor Union Over Inheritance

Although Pydantic supports inheritance, using `Union` with `TaggedUnion` is more appropriate for modeling variants that are structurally distinct. Inheritance implies a parent-child relationship and shared fields, which is not always appropriate for different types that only share a tag.

### Include a Discriminator Field in All Variants

Each variant in a union should define the same discriminator field. This makes parsing and validation predictable and ensures the type system can correctly infer the variant.

For example, in the `ErrorResponse` and `SuccessResponse` example, both include a `status` field.

### Add Exhaustiveness Checks

When writing code that uses type narrowing, ensure that all possible variants are considered in `if/elif` chains or `match` statements. This helps catch logic errors during development.

```python
def handle_event(event: Event):
    match event.type:
        case "login":
            # handle login
        case "logout":
            # handle logout
        case "error":
            # handle error
        case _:
            raise ValueError(f"Unknown event type: {event.type}")
```

This pattern enforces completeness and helps avoid runtime bugs.

---

## Advanced Patterns and Use Cases

### Nested Discriminated Unions

Discriminated unions can be nested or combined with other types to create complex data structures. This is common in API responses with multiple layers of data.

```python
class UserCreateSuccess(BaseModel):
    action: str = "create"
    status: str = "success"
    user: User

class UserUpdateSuccess(BaseModel):
    action: str = "update"
    status: str = "success"
    user: User

class UserDeleteSuccess(BaseModel):
    action: str = "delete"
    status: str = "success"
    message: str

ActionResponse = TaggedUnion(('action', 'status'), {
    ('create', 'success'): UserCreateSuccess,
    ('update', 'success'): UserUpdateSuccess,
    ('delete', 'success'): UserDeleteSuccess,
})
```

This allows for handling different actions on the same resource while preserving type safety.

### Union with Validation Rules

Pydantic also supports validation rules such as `root_validator` and `model_validator`, which can be used in conjunction with discriminated unions to enforce complex validation logic.

```python
from pydantic import BaseModel, Field, TaggedUnion, validator

class SuccessModel(BaseModel):
    status: str = "success"
    data: dict

    @validator('data')
    def validate_data(cls, v):
        if not v:
            raise ValueError("Data must not be empty")
        return v

class ErrorModel(BaseModel):
    status: str = "error"
    message: str

    @validator('message')
    def validate_message(cls, v):
        if not v.strip():
            raise ValueError("Message must not be empty")
        return v

ResponseModel = TaggedUnion('status', {
    'success': SuccessModel,
    'error': ErrorModel
})
```

This ensures that each variant adheres to specific rules, maintaining consistency and correctness.

---

## Cross-Reference with Other Concepts

### Field Types and Validation

When using discriminated unions, it’s important to consider how each variant’s fields are defined. See the **Field Types (03)** section for details on using Pydantic’s rich field types and annotations effectively.

Validation logic should be carefully written to handle all possible variants. The **Validation (03)** section provides more information on model validation and error handling strategies.

---

## Common Pitfalls and Troubleshooting

### Incorrect Discriminator Usage

A common mistake is using a field that changes between variants. This breaks the type system’s ability to infer the correct model.

For example, using a `status` field that can vary between `"success"`, `"warning"`, and `"error"` without defining a clear mapping can lead to ambiguous unions.

### Missing Discriminator Field

If a variant in a union does not define the required discriminator field, Pydantic will throw a validation error. Always ensure that all models in the `TaggedUnion` include the same set of required fields.

### Discriminator Values Not Matching

If the actual data contains a discriminator value that doesn’t match any variant, Pydantic will raise an error. This is expected behavior, but it’s essential to handle it gracefully, especially in production code.

---

## Conclusion

Discriminated unions are a powerful pattern for modeling data that can take on multiple forms. With Pydantic, you can build type-safe systems that enforce structure, reduce error-prone code, and improve maintainability.

By leveraging unions with a clear discriminator field, developers can write clean, expressive code that handles complex scenarios like API responses, event handling, and validation workflows with confidence.

Always ensure that your unions are well-structured, use stable discriminators, and validate data appropriately to maintain robustness and correctness in your applications.