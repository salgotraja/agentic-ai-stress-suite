# Model Validators (V2)

In Pydantic V2, the approach to model validation has evolved significantly from the root validators used in V1. The framework now provides a more Pythonic and flexible method using the `model_validator` decorator, which allows developers to define custom validation logic in a way that is more intuitive and integrated with the rest of the model configuration. This guide explores the key concepts behind model validators in Pydantic V2, how to migrate from V1 patterns, and how to implement validation chains effectively for robust data validation in production environments.

## Validation Modes and Decorator Usage

Pydantic V2 introduces two primary validation modes when using the `@model_validator` decorator: `mode="before"` and `mode="after"`.

- **`mode="before"`**: This mode is used when you need to perform validation or transformation *before* the model fields are assigned. It's useful for modifying or checking values before they are passed to the constructor.
- **`mode="after"`**: This mode is used for validation logic that requires the model to be fully constructed. It's ideal for checking relationships between fields or performing complex logic that depends on the model's internal state.

A `@model_validator` decorated function must receive a `data` argument in `before` mode, or an instance of the model in `after` mode. These functions must return the updated data or raise a `ValidationError` if invalid.

Here's a simple example using `before` mode to validate an email field:

```python
from pydantic import BaseModel, model_validator, EmailStr, ValidationError

class User(BaseModel):
    email: EmailStr
    password: str
    confirm_password: str

    @model_validator(mode="before")
    def passwords_match(cls, values):
        if values["password"] != values["confirm_password"]:
            raise ValueError("Passwords do not match")
        return values
```

In this case, we are ensuring that the user has provided matching passwords before the model is constructed. The `before` mode allows us to validate and potentially alter the input data before the model instance is created.

## Migration from Root Validator (V1 to V2)

In Pydantic V1, `root_validator` was used to apply validation logic that spanned multiple fields. V2 removes the `root_validator` in favor of `model_validator`, which is more aligned with Python's class-based syntax and supports both `before` and `after` validation modes.

To migrate from V1 to V2, replace `@root_validator` with `@model_validator(mode="after")`. For example:

**V1 Example:**
```python
from pydantic import BaseModel, root_validator

class User(BaseModel):
    email: str
    password: str
    confirm_password: str

    @root_validator
    def passwords_match(cls, values):
        if values["password"] != values["confirm_password"]:
            raise ValueError("Passwords do not match")
        return values
```

**V2 Equivalent:**
```python
from pydantic import BaseModel, model_validator, ValidationError

class User(BaseModel):
    email: str
    password: str
    confirm_password: str

    @model_validator(mode="before")
    def passwords_match(cls, values):
        if values["password"] != values["confirm_password"]:
            raise ValueError("Passwords do not match")
        return values
```

## Validation Chains and Composite Validation

In some scenarios, you need multiple validation rules to be applied sequentially or conditionally. Pydantic V2 supports this through multiple `@model_validator` decorated methods, which are executed in the order they are defined.

### Example: Enforcing Password Rules

```python
from pydantic import BaseModel, model_validator, ValidationError
import re

class User(BaseModel):
    username: str
    password: str
    confirm_password: str

    @model_validator(mode="before")
    def passwords_match(cls, values):
        if values["password"] != values["confirm_password"]:
            raise ValueError("Passwords do not match")
        return values

    @model_validator(mode="before")
    def password_complexity(cls, values):
        password = values["password"]
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        if not re.search(r"[A-Z]", password):
            raise ValueError("Password must contain at least one uppercase letter")
        if not re.search(r"[a-z]", password):
            raise ValueError("Password must contain at least one lowercase letter")
        if not re.search(r"[0-9]", password):
            raise ValueError("Password must contain at least one digit")
        return values
```

Here, we have two separate validation checks: one ensures the passwords match, and the second enforces a password complexity policy. These validations form a logical chain and are executed in the order the methods are defined.

## Practical Use Cases and Best Practices

### Data Transformation in `before` Mode

The `before` mode is not only for validation but also for transforming input data. For example, trimming extra whitespace from strings or parsing JSON fields embedded as strings.

```python
from pydantic import BaseModel, model_validator

class Product(BaseModel):
    name: str
    data: dict

    @model_validator(mode="before")
    def parse_data_field(cls, values):
        if "data" in values and isinstance(values["data"], str):
            try:
                values["data"] = cls._parse_json(values["data"])
            except Exception as e:
                raise ValueError(f"Invalid JSON in 'data' field: {e}")
        return values

    @staticmethod
    def _parse_json(s: str) -> dict:
        import json
        return json.loads(s)
```

### Conditional Validation in `after` Mode

In `after` mode, you can perform validation that depends on the full state of the model. This is often used to validate combinations of fields or enforce business logic.

```python
from pydantic import BaseModel, model_validator, ValidationError

class Order(BaseModel):
    product_id: int
    quantity: int
    is_paid: bool

    @model_validator(mode="after")
    def validate_order_conditions(self):
        if self.quantity <= 0:
            raise ValueError("Quantity must be greater than 0")
        if not self.is_paid and self.quantity > 100:
            raise ValueError("Unpaid orders must not exceed 100 units")
        return self
```

## Cross-Reference and Integration

- **Custom Validators (08)**: The `@field_validator` decorator is used for validating individual fields. When combined with `@model_validator`, you can create a layered validation system that is both powerful and manageable.
- **Root Validators (09)**: In V1, the `root_validator` was used for model-wide validation. In V2, `@model_validator` replaces this with a more flexible and object-oriented approach.

## Troubleshooting and Common Pitfalls

### Forgetting to Return Values in `before` Mode

A common mistake is to forget to return the modified `values` in `before` mode. This will result in missing or incorrect data in the model instance.

### Overlapping Validation Logic

Avoid placing the same validation logic in both `before` and `after` modes. This leads to redundancy and potential confusion. Choose the most appropriate mode for each validation step.

### Misusing `after` Mode for Data Transformation

While `after` mode is suitable for complex validations, it should not be used for data transformation unless absolutely necessary. Use `before` mode for such tasks to keep the model clean and maintainable.

### Incorrect Exception Types

Always raise `ValueError` or `ValidationError` in validation methods. Raising a generic `Exception` will not be handled properly by Pydantic and may lead to silent failures or confusing error messages.

## Conclusion

Pydantic V2's `@model_validator` is a powerful tool that enhances the clarity and flexibility of model validation. By understanding the distinction between `before` and `after` modes, you can implement robust, maintainable validation logic that meets the needs of your application. Whether you're migrating from V1 or starting fresh, embracing these patterns will help you write cleaner, more reliable code.