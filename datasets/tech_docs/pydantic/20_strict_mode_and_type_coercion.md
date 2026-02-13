# Strict Mode and Type Coercion

In Python, particularly with frameworks like Pydantic, understanding how data is validated and coerced is essential for building robust and type-safe applications. Type coercion refers to the automatic conversion of one data type to another, while strict mode controls whether such conversions are allowed or if strict validation is enforced. These concepts are crucial for maintaining data integrity and preventing subtle bugs in production systems.

## Understanding Strict Mode and Coercion

Strict mode is a validation configuration that affects how Pydantic handles data that doesn't exactly match the expected type. When strict mode is enabled, Pydantic will reject any input that can't be directly assigned to the expected type, without attempting coercion. Conversely, in lenient mode, Pydantic will attempt to coerce the input into the expected type.

```python
from pydantic import BaseModel, Field, StrictStr

class User(BaseModel):
    name: StrictStr
    age: int

# Strict validation example
try:
    user = User(name="John", age="30")
    print(f"Valid user: {user}")
except ValueError as e:
    print(f"Error: {e}")
```

In the example above, the `age` field is not of type `int`, but a `str`. Since `StrictStr` is used for `name`, it enforces type safety. However, the `age` field is not marked as `StrictInt`, which would disallow coercion from string to integer. Pydantic will attempt to coerce `"30"` to `30`, which is acceptable in lenient mode.

## Coercion Rules in Pydantic

Pydantic's coercion behavior is deeply integrated with Python's built-in type conversion rules. For example, it will attempt to convert strings to integers or floats, and even coerce lists or tuples to other types, depending on the field's declared type and configuration.

```python
from pydantic import BaseModel, Field
from typing import List

class Product(BaseModel):
    id: int
    tags: List[str]

# Example with coercion
product = Product(id="123", tags=["technology", "electronics"])
print(f"Processed product: {product}")
```

In this example, `id` is declared as an `int`, but the input is a string. Pydantic will coerce `"123"` to `123`, and since `tags` is a `List[str]`, it will expect and accept a list of strings. However, if `tags` were defined as an `int`, coercion would fail unless the list could be converted to an integer, which is not the case here.

## Strict Types and Type Safety Trade-Offs

Using strict types can enhance type safety at the cost of flexibility. While strict types prevent unintended data conversions, they can also make it harder to work with external data sources that may not always conform to the expected format.

```python
from pydantic import BaseModel, StrictInt, StrictStr

class Order(BaseModel):
    order_id: StrictInt
    customer_name: StrictStr
    total: float

# Attempting to process invalid data
try:
    order = Order(order_id="1001", customer_name=123, total="not a float")
    print(f"Valid order: {order}")
except ValueError as e:
    print(f"Error: {e}")
```

In this example, `order_id` is a `StrictInt`, so passing a string `"1001"` will trigger an error unless the input is an actual integer. Similarly, `customer_name` is a `StrictStr`, so passing an integer as `123` will also fail. The `total` field is a `float`, which will not accept a string unless coercion is allowed.

This strict approach ensures that only valid, correctly typed data is accepted, which is especially important in systems where data integrity is critical.

## API Design and Data Validation

When designing APIs, it's important to balance between strict validation and lenient parsing depending on the use case. For public APIs, lenient validation may be appropriate to accommodate a wide variety of inputs. For internal systems or data pipelines, strict mode is often preferred for type safety and error prevention.

```python
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional

app = FastAPI()

class PublicUserInput(BaseModel):
    name: str
    age: int

class InternalUserModel(BaseModel):
    name: StrictStr
    age: StrictInt

@app.post("/public")
def create_user(data: PublicUserInput):
    return {"user": data.model_dump()}

@app.post("/internal")
def create_strict_user(data: InternalUserModel):
    return {"user": data.model_dump()}
```

In the `PublicUserInput` model, `str` and `int` are used, allowing Pydantic to perform type coercion. In contrast, the `InternalUserModel` uses `StrictStr` and `StrictInt`, enforcing stricter validation rules. This distinction helps maintain clean, predictable data in internal systems while allowing more flexibility for public-facing endpoints.

## Best Practices

1. **Use strict types in internal systems** where data integrity is critical and inputs can be controlled.
2. **Use lenient types in public APIs** to support a wide range of input formats and improve compatibility.
3. **Validate external data sources** with strict models to prevent downstream errors.
4. **Leverage `Strict*` types** when working with data that must not be altered during parsing.
5. **Document coercion behavior** for public APIs to inform users about expected input formats.
6. **Test edge cases** such as `None`, empty strings, and non-numeric strings to ensure robust validation.
7. **Use `Field` with `default` or `default_factory`** to provide fallback values when coercion is not possible.

## Cross-Reference with Field Types and Validation

Strict mode and coercion behavior are closely tied to how field types are declared. As outlined in [Field types (03)](03), Pydantic offers a rich set of type annotations and customizable field options that affect coercion and validation. Coupled with [Validation (03)](03), strict mode becomes a powerful tool to enforce domain-specific rules and constraints.

For example, combining strict types with custom validators can help enforce complex invariants:

```python
from pydantic import BaseModel, Field, validator
from typing import List

class Team(BaseModel):
    name: str
    members: List[str]
    max_members: int = 5

    @validator("members")
    def validate_member_count(cls, value, values):
        if len(value) > values.get("max_members", 5):
            raise ValueError("Team cannot have more than 5 members")
        return value

# Example usage
try:
    team = Team(name="Alpha", members=["Alice", "Bob", "Charlie", "David", "Eve", "Frank"])
except ValueError as e:
    print(f"Validation error: {e}")
```

This example ensures that team members are strictly strings and that the number of members doesn't exceed the specified limit. Strict types ensure data consistency, while the custom validator enforces business logic.

## Common Pitfalls and Troubleshooting

- **Coercion may mask bugs**: If you're relying too heavily on coercion, invalid data might pass unnoticed. Always test with strict types in production.
- **Confusing `None` and empty strings**: Be cautious when `None` is passed to a field expecting a string. Use `Optional[str]` when appropriate.
- **Unexpected type conversion**: For example, `"123"` may be converted to `123` without error. Consider using `StrictStr` if this behavior is not desired.
- **Inconsistent validation across environments**: Ensure that strict mode is consistently applied across development, staging, and production.

## Conclusion

Strict mode and type coercion are fundamental concepts in Pydantic and Python-based data validation systems. By carefully choosing when and how to apply strict types, developers can strike a balance between type safety and flexibility. Understanding the underlying rules of coercion and how they interact with Python’s type system is essential for building reliable, scalable applications.