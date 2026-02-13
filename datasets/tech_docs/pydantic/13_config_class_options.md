# Config Class Options

In Pydantic, the `Config` class is a powerful mechanism to customize the behavior of your data models. It provides control over validation, serialization, and other features that are essential for building robust and maintainable applications. By configuring the `Config` class, developers can tailor Pydantic models to suit specific use cases, including handling extra fields, enforcing immutability, or managing strict input validation. This document explores key configuration options like `extra fields handling`, `strict mode`, and `frozen models`, with a focus on production-ready patterns and best practices.

---

## Customizing Model Behavior with `model_config`

Starting from Pydantic v2, the `model_config` system is used to configure model behavior. It is a class-level attribute that defines the configuration options for a given `BaseModel`. The configuration can be set using the `model_config` class variable, or using the `@model_validator` or `@field_validator` decorators for more granular control.

The `model_config` attribute supports a wide range of configuration options. These include how to handle unexpected input fields, whether to allow extra fields, whether to enforce strict validation, and whether to make the model instance immutable after creation.

```python
from pydantic import BaseModel, ConfigDict

class ExampleModel(BaseModel):
    model_config = ConfigDict(extra = 'ignore', frozen = False, strict = False)
    
    name: str
    age: int
```

In this example, the `model_config` class variable defines the configuration for the `ExampleModel`. The `extra` option is set to `'ignore'`, meaning any extra fields provided in input will be ignored. The `frozen` and `strict` options are set to `False`, which means the model instances can be modified after creation, and inputs are not strictly validated.

Understanding and customizing `model_config` is essential for building models that are both flexible and predictable in behavior.

---

## Handling Extra Fields

One of the most common configuration decisions involves how to handle extra fields—those that are not explicitly defined in the model schema.

Pydantic provides three main `extra` options in the `model_config`:

- `'allow'`: permits extra fields to be included in the model instance.
- `'ignore'`: ignores extra fields during model creation.
- `'forbid'`: raises a validation error when extra fields are present.

```python
from pydantic import BaseModel, ConfigDict, ValidationError

class User(BaseModel):
    model_config = ConfigDict(extra = 'forbid')
    
    name: str
    age: int

try:
    user = User(name='Alice', age=30, role='admin')
except ValidationError as e:
    print(e)
```

In this example, the `extra` option is set to `'forbid'`. When the model instance is created with an extra field (`role`), a `ValidationError` is raised, ensuring that the model adheres strictly to its defined schema.

Choosing the appropriate `extra` setting depends on the use case. In APIs that expect strict schemas, `'forbid'` is ideal for catching misformatted payloads. In more flexible use cases, such as data processing pipelines, `'ignore'` or `'allow'` can be more suitable.

---

## Strict Mode

Strict mode is another powerful configuration that enforces stricter input validation. When enabled via `strict = True`, Pydantic will not attempt to coerce input values into the correct type. Instead, inputs must match the expected type exactly. This is particularly useful when dealing with untrusted or malformed input data.

```python
class StrictSettings(BaseModel):
    model_config = ConfigDict(strict = True)
    
    rate_limit: int

try:
    settings = StrictSettings(rate_limit="10")
except ValidationError as e:
    print(e)
```

In this example, the `rate_limit` field is expected to be an `int`, but the input is a `str`. With strict mode enabled, Pydantic raises a `ValidationError` instead of attempting to convert `"10"` to `10`.

Strict mode should be used in scenarios where data integrity is critical. It’s particularly useful in applications that receive input from external sources, such as APIs, where type coercion could mask errors or lead to subtle bugs.

---

## Frozen Models: Immutable Data Structures

Frozen models are models whose instances cannot be modified after creation. This is controlled using the `frozen = True` configuration option. When a model is frozen, any attempt to assign to an attribute will raise an `AttributeError`.

```python
class FrozenUser(BaseModel):
    model_config = ConfigDict(frozen = True)
    
    name: str
    email: str

user = FrozenUser(name="Bob", email="bob@example.com")
user.name = "Charlie"  # Raises AttributeError
```

Frozen models are ideal for representing data that should not change after initialization, such as configuration settings or immutable DTOs (Data Transfer Objects). They also help in building thread-safe code and prevent accidental modifications to critical data.

When using frozen models, it’s important to ensure that all required data is provided at construction time. Since no attributes can be modified afterward, all fields must be initialized in the constructor.

---

## Combining Configuration Options

Pydantic allows multiple configuration options to be combined in a single model. This is useful for defining models that are strict, immutable, and reject extra fields.

```python
class ConfigurableModel(BaseModel):
    model_config = ConfigDict(
        extra = 'forbid',
        strict = True,
        frozen = True
    )
    
    key: str
    value: int
```

In this example, the model is configured to forbid extra fields, enforce strict input validation, and disallow modification of instance attributes. This combination is ideal for use cases that require robust validation and immutability, such as configuration management or API request validation.

When combining options, it’s important to test thoroughly, as stricter validation can lead to more frequent validation errors in real-world scenarios. However, this also ensures that models are predictable and less prone to data corruption.

---

## Practical Use Cases and Best Practices

### Immutable Configuration Objects

Frozen models are excellent for representing immutable configuration objects. They ensure that once a configuration is loaded, it cannot be accidentally modified.

```python
class AppConfig(BaseModel):
    model_config = ConfigDict(frozen = True)
    
    app_name: str
    debug_mode: bool
    db_url: str

config = AppConfig(app_name='MyApp', debug_mode=True, db_url='sqlite:///dev.db')
```

In this use case, the configuration is loaded from a file or environment variables and stored in a frozen model. This ensures that the configuration remains consistent throughout the application lifecycle.

### API Request and Response Models

For APIs that require strict validation and immutability of request/response data, combining frozen and strict mode is ideal.

```python
class RequestModel(BaseModel):
    model_config = ConfigDict(frozen = True, strict = True)
    
    user_id: str
    action: str
```

This ensures that the request data is validated against the schema and cannot be modified after validation, which is important for maintaining data integrity in distributed systems.

### Customizing Validation Logic with `model_validator`

For more complex validation logic, Pydantic allows using `model_validator` to define custom validation rules. This is particularly useful when you need validation logic that spans multiple fields or requires external data.

```python
from pydantic import BaseModel, ConfigDict, model_validator

class Product(BaseModel):
    model_config = ConfigDict(extra = 'forbid')
    
    name: str
    price: float
    is_available: bool

    @model_validator(mode='after')
    def check_price_availability(self):
        if self.price <= 0 and self.is_available:
            raise ValueError("Product is available but has non-positive price")
        return self

product = Product(name='Laptop', price=1200, is_available=True)
```

In this example, a custom validation rule ensures that a product marked as available cannot have a non-positive price. This kind of logic is important in e-commerce or inventory systems where data consistency is critical.

---

## Cross-Reference & Advanced Topics

- **BaseModel basics (02)**: For foundational knowledge on creating and using models.
- **Validation (03)**: For deeper insights into field validation and custom validation logic.

### Comparison with Alternative Approaches

While Pydantic provides a rich and flexible configuration system, other data validation libraries such as `dataclasses` or `attrs` offer different trade-offs. `dataclasses` lacks built-in validation and configuration options, while `attrs` provides validation through attributes and converters but is not as tightly integrated with type annotations as Pydantic.

Pydantic shines in its ability to combine type annotations with powerful configuration options, making it particularly well-suited for modern Python applications that require both flexibility and correctness.

---

## Troubleshooting Common Issues

- **Unexpected `ValidationError`:** Ensure that all required fields are included in the input data. If using `'forbid'` for extra fields, no additional fields should be present.
- **Frozen model modification issues:** When working with frozen models, avoid mutating instances after creation. Use `.copy()` to create mutable copies if needed.
- **Strict validation errors:** If using `strict = True`, ensure that input types exactly match the model schema. Avoid relying on type coercion in such cases.

---

## Conclusion

The `Config` class in Pydantic is a critical tool for customizing and controlling the behavior of data models. By configuring options such as `extra fields handling`, `strict mode`, and `frozen models`, developers can build models that are robust, predictable, and suitable for production environments.

When designing models for APIs, configuration management, or data validation, it is important to carefully consider how each configuration option affects the model's behavior. Combining options such as `extra = 'forbid'`, `strict = True`, and `frozen = True` can result in models that are both safe and performant.

Understanding these options is key to leveraging Pydantic's full capabilities and ensuring that your models are aligned with the needs of your application.