# Pydantic Dataclasses

Pydantic dataclasses extend Python’s standard `@dataclass` decorator with powerful validation, parsing, and serialization capabilities. They allow developers to define data models using familiar Python syntax, while integrating seamlessly with Pydantic’s type-based validation system. Unlike base dataclasses, Pydantic dataclasses automatically enforce type constraints, validate inputs, and offer rich introspection and serialization features—making them ideal for data modeling in APIs, configuration systems, and data pipelines.

This documentation explains how to use Pydantic dataclasses, how they compare with standard dataclasses, and how to effectively migrate existing code to leverage Pydantic's validation and configuration features.

---

## Pydantic Dataclass Basics

Pydantic provides the `@pydantic.dataclasses.dataclass` decorator, which functions similarly to Python’s built-in `@dataclass`, but adds validation and serialization. The decorator must be imported from `pydantic.dataclasses`, and the class must define type annotations for all fields.

Here’s a basic example:

```python
from pydantic.dataclasses import dataclass
from typing import Optional

@dataclass
class User:
    id: int
    name: str
    email: Optional[str] = None
```

This class behaves like a regular dataclass, but with added validation. For example, assigning an invalid type to `id` raises a `TypeError`:

```python
user = User(id='not-an-integer', name='Alice')  # Raises TypeError
```

This behavior is controlled by Pydantic’s validation system, which enforces that all fields match their declared types.

---

## Migration from Standard Dataclasses

Migrating from standard `@dataclass` to Pydantic dataclasses is straightforward. Simply replace the import and add validation as needed.

### Example Migration

#### Standard Dataclass
```python
from dataclasses import dataclass

@dataclass
class Product:
    name: str
    price: float
```

#### Pydantic Dataclass
```python
from pydantic.dataclasses import dataclass

@dataclass
class Product:
    name: str
    price: float
```

In most cases, the code remains identical, but Pydantic adds validation. For example:

```python
p1 = Product(name='Laptop', price='not-a-number')  # Raises ValueError
```

If you want to support both types of inputs—like JSON or dictionaries—Pydantic provides `model_validate` and `model_dump` methods for conversion:

```python
Product.model_validate({'name': 'Phone', 'price': 800})  # Valid
```

---

## Hybrid Usage with BaseModel

Pydantic dataclasses can be used alongside `BaseModel` for more complex scenarios. While dataclasses are suitable for read-only or minimal validation needs, `BaseModel` offers more advanced configuration and validation features. You may use both in the same codebase for different use cases.

### Example: Using BaseModel and Dataclass Together

```python
from pydantic import BaseModel
from pydantic.dataclasses import dataclass
from typing import List

@dataclass
class User:
    id: int
    name: str

class UserGroup(BaseModel):
    users: List[User]
    created_at: str
```

This allows you to build complex models incrementally, using `BaseModel` where full validation and serialization are needed, and dataclasses for simpler use cases.

---

## Advanced Validation and Configuration

Like `BaseModel`, Pydantic dataclasses support custom validation through class attributes and methods. You can define validators using `@validator` or `@field_validator` (in Pydantic v2) for field-level checks.

### Example: Custom Field Validation

```python
from pydantic.dataclasses import dataclass
from pydantic import field_validator, Field, BaseModel

@dataclass
class Product:
    name: str
    price: float
    discount: float = 0.0

    @field_validator('price')
    def price_must_be_positive(cls, value):
        if value < 0:
            raise ValueError("Price cannot be negative")
        return value
```

This ensures that any instance of `Product` has a non-negative price. You can also define class-level validation with `model_validator`:

```python
from pydantic import model_validator

@dataclass
class Order:
    items: List[Product]
    total: float

    @model_validator(mode='after')
    def check_total_matches_items(cls, values):
        items_total = sum(item.price for item in values.items)
        if abs(values.total - items_total) > 0.01:
            raise ValueError("Total does not match item prices")
        return values
```

These validations help maintain data integrity and reduce the risk of invalid state.

---

## Best Practices

When working with Pydantic dataclasses, consider the following best practices:

- **Use type annotations**: Always annotate fields with their expected types.
- **Prefer `@pydantic.dataclasses.dataclass` over `@dataclass`** when validation and serialization are required.
- **Leverage `model_validate()`** for parsing inputs from external sources (JSON, dictionaries).
- **Use `model_dump()`** to serialize dataclasses to dictionaries or JSON.
- **Keep dataclasses immutable when possible** to avoid unintended side effects.
- **Use `BaseModel` for complex validation logic**, and `dataclass` for simpler models.

### Performance Considerations

Pydantic dataclasses are generally faster than `BaseModel` due to reduced overhead. They are ideal for use cases where full validation is not needed, such as when data is already trusted. If you need full validation and configuration features, prefer `BaseModel`.

---

## Troubleshooting and Common Pitfalls

### 1. **TypeError: Invalid Type Assignment**

When assigning a value of the wrong type to a field, Pydantic raises a `TypeError`. This is especially common when importing data from external sources:

```python
User(id='123', name='Bob')  # Raises TypeError
```

**Fix**: Use `model_validate()` to parse the input data:

```python
User.model_validate({'id': '123', 'name': 'Bob'})  # Converts id to int
```

### 2. **Missing Required Fields During Instantiation**

If a required field is not provided, Pydantic raises a `TypeError`:

```python
User(name='Alice')  # Missing 'id' raises error
```

**Fix**: Use default values or optional types (`Optional[]`) for non-required fields.

### 3. **Confusing Dataclass and BaseModel Behavior**

Pydantic dataclasses do not support all the features of `BaseModel`, such as `Config` classes or advanced validation hooks. If you need those, use `BaseModel`.

---

## Cross-Framework Comparison

| Feature | Standard Dataclass | Pydantic Dataclass | Pydantic BaseModel |
|--------|--------------------|--------------------|--------------------|
| Type Validation | ❌ | ✅ | ✅ |
| Field Validation | ❌ | ✅ | ✅ |
| Serialization | ❌ | ✅ | ✅ |
| Configurable Settings | ❌ | ⚠️ | ✅ |
| JSON Parsing | ❌ | ✅ | ✅ |
| Error Messages | ❌ | ✅ | ✅ |

Pydantic dataclasses offer a middle ground between Python’s native `@dataclass` and `BaseModel`, providing type safety and validation without the full overhead of a `BaseModel`.

---

## Real-World Use Cases

Pydantic dataclasses are particularly useful in the following scenarios:

1. **API Response Modeling**: Define expected return types for internal APIs or microservices.
2. **Data Pipeline Staging**: Intermediate data structures for ETL processes.
3. **Configuration Objects**: Settings with type-checked defaults and validation.
4. **Serialization**: When you need to convert between Python objects and JSON or other formats.

### Example: API Response Modeling

```python
@dataclass
class ApiResponse:
    status: str
    data: dict
    timestamp: float
```

This can be used to enforce the structure of an internal or external API response.

---

## Conclusion

Pydantic dataclasses are a powerful extension of Python’s standard dataclasses, providing type safety, validation, and serialization capabilities without the full complexity of `BaseModel`. They are ideal for data modeling in applications where performance and simplicity are important, but validation is still required. By understanding how to migrate from standard dataclasses, use hybrid models with `BaseModel`, and apply validation and configuration patterns, you can build robust, maintainable data models in Python.