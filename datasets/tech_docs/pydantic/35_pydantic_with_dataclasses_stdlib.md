# Pydantic with Dataclasses (stdlib)

Pydantic offers a powerful mechanism for data validation, serialization, and deserialization using Python type hints. The standard library's `dataclasses` module provides a convenient way to define classes with minimal boilerplate. While Pydantic's native dataclasses (`pydantic.dataclasses.dataclass`) offer additional validation and settings management features, it's often necessary or desirable to interoperate with the standard library's `dataclass` in production scenarios. This section explores how to integrate Pydantic with standard dataclasses, when and why to do it, and provides practical patterns for migration and compatibility.

---

## Interoperability Patterns

Pydantic can work alongside `dataclasses.dataclass` through conversion and inheritance. This allows for gradual migration from standard dataclasses to Pydantic models while maintaining backward compatibility and leveraging existing libraries that expect standard dataclasses.

### Conversion Between Dataclasses and Pydantic Models

Converting between the two forms is straightforward. Pydantic provides a `Model` interface, and standard dataclasses can be converted using the `model_construct` or `model_validate` methods.

```python
from dataclasses import dataclass
from pydantic import BaseModel, model_validator
from typing import Optional

@dataclass
class StdDataclass:
    name: str
    age: Optional[int] = None

class PydanticModel(BaseModel):
    name: str
    age: Optional[int] = None

# Convert from a standard dataclass to Pydantic
std_instance = StdDataclass(name="Alice", age=30)
pydantic_instance = PydanticModel.model_validate(std_instance)

# Convert back to standard dataclass
std_instance_2 = PydanticModel.model_validate(pydantic_instance).model_dump()

assert std_instance_2 == std_instance
```

This pattern is especially useful in systems where some components expect `BaseModel` and others rely on standard dataclasses. It also supports serialization and validation in Pydantic-aware frameworks.

---

## Gradual Migration Strategies

When moving from standard dataclasses to Pydantic, a phased approach is recommended to avoid breaking existing workflows or dependencies.

### 1. **Parallel Definition with Inheritance**

One common strategy is to define both a standard dataclass and a Pydantic model, with the Pydantic model inheriting from the standard one. This allows you to retain the existing structure while adding validation logic.

```python
from dataclasses import dataclass
from pydantic import BaseModel

@dataclass
class UserDC:
    id: int
    name: str
    email: str

class UserPydantic(UserDC, BaseModel):
    @model_validator(mode='after')
    def validate_email(self) -> 'UserPydantic':
        if '@' not in self.email:
            raise ValueError("Invalid email format")
        return self

# Usage
user_std = UserDC(id=1, name="Bob", email="bob@domain.com")
user_pydantic = UserPydantic.model_validate(user_std)
user_pydantic.validate_email()
```

This pattern is particularly useful when you want to add validation logic incrementally. The standard dataclass can still be used where needed, while Pydantic models are used in validation, serialization, or when interacting with other Pydantic-based components.

---

## Integration with Libraries and Frameworks

Many libraries, especially in the data engineering and serialization domains, are built to work with standard dataclasses. Pydantic's interoperability ensures that you can continue using these libraries while benefiting from Pydantic's features.

### Example: JSON Serialization with `json`

Standard dataclasses can be serialized using the `json` module. When paired with Pydantic, you can use `model_dump_json()` for richer output, including type hints and validation.

```python
import json
from dataclasses import dataclass
from pydantic import BaseModel

@dataclass
class User:
    name: str
    age: int

class UserPydantic(BaseModel):
    name: str
    age: int

# Serialize using standard dataclass
user_std = User(name="Charlie", age=25)
json.dumps(user_std.__dict__)  # Standard serialization

# Serialize using Pydantic
user_pydantic = UserPydantic.model_validate(user_std)
json_output = user_pydantic.model_dump_json()
print(json_output)  # {"name": "Charlie", "age": 25}
```

In this case, the Pydantic model can be used to enforce validation and add custom JSON schemas, while the standard dataclass remains the source of truth for library integrations.

---

## Best Practices for Production Use

When integrating Pydantic with standard dataclasses in production systems, consider the following best practices:

### 1. **Use Pydantic for Validation, Not Just Serialization**

Even if your data is initially defined in a standard dataclass, use Pydantic when you need to validate data from external sources such as APIs, databases, or user input.

```python
from dataclasses import dataclass
from pydantic import BaseModel, Field

@dataclass
class ProductDC:
    id: int
    name: str
    price: float

class ProductPydantic(BaseModel):
    id: int
    name: str
    price: float = Field(gt=0)  # Price must be > 0

# Validate incoming API data
raw_data = {"id": 101, "name": "Widget", "price": -5.99}
product = ProductPydantic.model_validate(raw_data)  # Raises ValueError
```

This pattern ensures that invalid data is caught early in the request pipeline.

### 2. **Avoid Mixing Pydantic and Dataclass Decorators**

Do not apply both `@dataclass` and `@pydantic.dataclass` to the same class. Doing so can lead to unexpected behavior. Choose one form based on your validation and usage needs.

### 3. **Use Pydantic for Complex Validation Logic**

When validation logic becomes complex or involves cross-field checks, prefer Pydantic's `model_validator` or `root_validator` over ad-hoc checks in standard dataclasses.

```python
from pydantic import BaseModel, model_validator, ValidationInfo

class Order(BaseModel):
    quantity: int
    price: float

    @model_validator(mode='after')
    def validate_total(self) -> 'Order':
        if self.quantity * self.price < 10:
            raise ValueError("Total order value must be at least $10")
        return self
```

---

## Common Pitfalls and Troubleshooting

- **TypeError: 'dataclass' object is not iterable**: This error usually occurs when trying to pass a standard dataclass instance directly to a function expecting a dictionary. Use `.__dict__` or `model_dump()` when converting.

- **Missing fields during validation**: Ensure that the standard dataclass and Pydantic model have identical fields and types. Mismatches will raise `ValidationError`.

- **Performance overhead**: While Pydantic adds validation, it can introduce overhead. For high-throughput systems, consider using standard dataclasses for internal structures and Pydantic only at the edges (e.g., API input/output).

---

## Production-Ready Patterns

For robust, maintainable code, consider the following patterns:

### 1. **Layered Architecture with Validation at the Edge**

Use standard dataclasses for internal domain objects and Pydantic models for external interfaces. This decouples business logic from validation concerns and helps maintain a clean API surface.

### 2. **Pydantic as a Middleware Layer**

In web frameworks like FastAPI or Starlette, use Pydantic models as request and response models while keeping domain models as standard dataclasses.

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class InputModel(BaseModel):
    name: str
    quantity: int

class OutputModel(BaseModel):
    id: int
    name: str
```

This approach ensures that your API is strongly typed and validated, while internal logic remains efficient and modular.

---

## Conclusion

Pydantic's ability to interoperate with standard library `dataclass` enables flexible and scalable data modeling strategies. By understanding the trade-offs between the two systems and applying appropriate migration and integration patterns, you can build robust, maintainable data workflows that leverage the best of both worlds. Whether incrementally upgrading existing systems or building new ones from scratch, Pydantic provides the tools needed to manage data with confidence and precision.