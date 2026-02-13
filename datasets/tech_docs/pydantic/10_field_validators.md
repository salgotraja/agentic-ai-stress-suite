# Field Validators

In Pydantic, field validators are essential tools for enforcing business rules, data consistency, and input integrity in your models. They are functions that run after a field is initialized and validated, allowing you to perform custom validation logic on specific fields. In Pydantic V2, the `@field_validator` decorator provides a flexible and powerful mechanism to define field-level validation logic. This document explores the key concepts of field validation, shows how to implement validators using `@field_validator`, and explains best practices for integrating them into production-grade applications.

## Core Concepts of Field Validation

Field validation in Pydantic is centered around the `@field_validator` decorator. It is applied to functions that validate a specific field in a model. These validators are executed after the basic type-checking and parsing are done, giving you a hook to perform more complex checks, such as validating ranges, checking format rules, or ensuring consistency across multiple fields.

The `@field_validator` decorator provides a clear separation between field validation and general model validation (`@model_validator`). This makes the code easier to maintain and test, especially in large applications.

### Key Parameters of `@field_validator`

- `mode`: Can be `"before"` or `"after"` (default is `"after"`), determining whether the validator runs before or after the value is assigned to the model.
- `each_item`: When `True`, the validator applies to each item in a list or sequence.
- `check_fields`: When `False`, the validator runs even if the field is not present in the input.

## Practical Use of `@field_validator`

Let's look at a real-world example to understand how to use `@field_validator` in practice. Suppose you are building a user management system and need to validate email and password fields.

```python
from pydantic import BaseModel, field_validator
from typing import Optional
import re

class UserCreateModel(BaseModel):
    email: str
    password: str
    first_name: Optional[str] = None
    last_name: Optional[str] = None

    @field_validator('email')
    def validate_email_format(cls, value: str) -> str:
        if not re.match(r'[^@]+@[^@]+\.[^@]+', value):
            raise ValueError("Invalid email format")
        return value

    @field_validator('password')
    def validate_password_strength(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password must be at least 8 characters long")
        if not any(c.isupper() for c in value):
            raise ValueError("Password must contain at least one uppercase letter")
        return value
```

In this example:
- The `validate_email_format` validator ensures the email has the correct format.
- The `validate_password_strength` validator checks for length and presence of an uppercase letter.

These validators are tightly coupled to their respective fields, making the model easy to understand and maintain.

## Advanced Patterns and Reusability

### Reusable Validator Functions

You can extract validation logic into reusable functions and apply them across multiple models. This is particularly useful when multiple models share the same constraints. For example, if multiple models require a password validation rule, you can define a shared function and apply it via `@field_validator`.

```python
from pydantic import field_validator, validate_call

def validate_password_strength(value: str) -> str:
    if len(value) < 8:
        raise ValueError("Password must be at least 8 characters long")
    if not any(c.isupper() for c in value):
        raise ValueError("Password must contain at least one uppercase letter")
    return value

class UserSettingsModel(BaseModel):
    password: str

    @field_validator('password')
    def validate_password(cls, value: str) -> str:
        return validate_password_strength(value)
```

This approach reduces duplication and ensures consistent behavior across models.

### Validation Across Multiple Fields

While `@field_validator` is field-specific, you might need to perform validation that depends on multiple fields. For such cases, consider using `@model_validator(mode='after')`. For example, validating that a `start_date` is before an `end_date`.

```python
from datetime import date
from pydantic import model_validator

class EventModel(BaseModel):
    name: str
    start_date: date
    end_date: date

    @model_validator(mode='after')
    def validate_dates(cls, instance):
        if instance.start_date > instance.end_date:
            raise ValueError("Start date must be before end date")
        return instance
```

While this is not a field validator, it demonstrates how to handle cross-field validation when necessary.

## Error Handling and Custom Messages

Proper error handling is crucial in production applications. Pydantic allows you to raise `ValueError` with descriptive messages. These are automatically converted into user-friendly error messages in API responses.

```python
@field_validator('email')
def validate_email(cls, value: str) -> str:
    if not value.endswith('@example.com'):
        raise ValueError("Only example.com email addresses are allowed")
    return value
```

This ensures that any external consumer of the model’s API receives clear and actionable feedback when validation fails.

## Best Practices for Field Validation

### 1. Keep Validations Simple and Focused

Each field validator should focus on a single validation rule. If a field requires multiple checks, split them into separate validators or combine them logically within the same function.

### 2. Use External Validation Libraries

For complex validation patterns, consider using external libraries like `email-validator` for email validation or `password-validator` for password rules. This ensures robustness and reduces the risk of introducing bugs in your custom logic.

```python
from email_validator import validate_email
from email_validator import EmailNotValidError

@field_validator('email')
def validate_email(cls, value: str) -> str:
    try:
        valid = validate_email(value)
        return valid.email
    except EmailNotValidError as e:
        raise ValueError("Invalid email") from e
```

### 3. Avoid Side Effects in Validators

Field validators should avoid side effects such as logging, database calls, or I/O operations. They are meant to validate data, not to execute business logic. If you need to perform actions based on validation, consider using `@model_validator` or event hooks.

### 4. Test Thoroughly

Each validator should be tested with a variety of inputs, including edge cases and invalid data. Consider using Pydantic’s `model_validate` function in unit tests to simulate different scenarios.

```python
from pydantic import ValidationError

def test_user_validation():
    with pytest.raises(ValidationError) as exc_info:
        UserCreateModel(email='invalid-email', password='1234')
    assert "Invalid email format" in str(exc_info.value)

    with pytest.raises(ValidationError) as exc_info:
        UserCreateModel(email='user@example.com', password='1234567')
    assert "Password must be at least 8 characters long" in str(exc_info.value)
```

### 5. Use Descriptive Error Messages

Custom error messages should be clear, actionable, and helpful. Avoid generic messages like `"Invalid value"`; instead, provide specific guidance such as `"Password must contain at least one uppercase letter"`.

## Troubleshooting and Common Pitfalls

### 1. Validator Not Triggered

If a validator is not being called, double-check the decorator syntax and ensure the function is properly attached to the field. Also, verify that the field is included in the model and that the model is being instantiated correctly.

### 2. Overriding or Modifying Input Values

Avoid modifying the value unless it is necessary for the model. If you must modify a value, return the transformed version from the validator. For example, trimming whitespace or converting to lowercase.

```python
@field_validator('username')
def normalize_username(cls, value: str) -> str:
    return value.strip().lower()
```

### 3. Confusing `@field_validator` with `@model_validator`

Make sure to use `@field_validator` for single-field validation and `@model_validator` for cross-field or model-level logic. Mixing them can lead to confusion and errors.

## Cross-Reference with Other Concepts

For more information on writing custom validation logic outside the scope of fields, see [Custom validators (08)](link). To learn about how field types affect validation, read [Field types (03)](link).

## Comparison with Alternative Approaches

Some developers may be familiar with using `@validator` in Pydantic V1. In V2, `@validator` is deprecated in favor of `@field_validator`, which is more consistent with the new validation system and integrates better with the rest of the framework.

Compared to raw type-checking or manual validation, `@field_validator` provides a declarative and reusable way to express validation rules, reducing boilerplate and improving code readability.

## Real-World Use Cases

1. **User Input Validation in Web APIs**  
   When building REST APIs using FastAPI or similar frameworks, field validators are used to sanitize and validate incoming data before performing business logic or database operations.

2. **Data Import Pipelines**  
   When importing large datasets, validators ensure that each record meets the required format and constraints before being processed further.

3. **Form Validation in Applications**  
   In GUI or form-based applications, validators can be used to provide immediate feedback to users when invalid data is entered.

4. **Configuration Management**  
   When parsing configuration files or environment variables, validators help ensure that all required settings are present and correctly formatted.

## Conclusion

Field validation is a critical aspect of building robust and reliable applications. Pydantic’s `@field_validator` provides a powerful and flexible way to define validation logic at the field level, making your models more expressive and easier to maintain. By following best practices such as writing focused validators, reusing logic, and testing thoroughly, you can ensure that your validation code is both robust and maintainable in the long term.