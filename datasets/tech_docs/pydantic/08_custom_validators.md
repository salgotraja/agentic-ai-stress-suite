# Custom Validators

Custom validators in Pydantic allow developers to enforce complex validation rules that go beyond simple type checking and built-in validation. When working with models that require domain-specific logic, such as enforcing business rules or performing cross-field validations, custom validators provide the flexibility and control needed to ensure correctness and data integrity.

Pydantic offers two primary types of custom validators: **field validators** and **model validators**. These can be applied at the pre or post validation stage, depending on the logic being implemented.

This document explores how to define and apply these validators, highlights the use of the `@validator` decorator, and discusses best practices for writing robust and maintainable validation logic.

---

## Field Validators vs. Model Validators

### Field Validators

Field validators are applied to a specific model field and are used to validate that field individually. They are useful for enforcing constraints that are specific to a single attribute of the model.

For example, you might want to ensure that an email field is in the correct format or that a username contains only alphanumeric characters.

Pydantic uses the `@validator` decorator to define field validators. The validator function receives the current value of the field and returns the validated or transformed value.

```python
from pydantic import BaseModel, validator, ValidationError

class User(BaseModel):
    email: str

    @validator('email')
    def validate_email_format(cls, v):
        if '@' not in v:
            raise ValueError('Email must contain an @ symbol')
        if '.' not in v.split('@')[1]:
            raise ValueError('Email domain must contain a dot')
        return v

# Usage
try:
    user = User(email='invalid-email')
except ValidationError as e:
    print(e)

# Correct usage
user = User(email='user@example.com')
```

In this example, the `validate_email_format` method checks that the email contains an `@` and a valid domain. If validation fails, a `ValueError` is raised, which Pydantic captures and formats into a `ValidationError`.

### Model Validators

Model validators operate on the entire model and are used for validations that involve multiple fields or the model as a whole. These validators are useful for enforcing business rules or relationships between fields.

For example, you might want to ensure that a user's `birth_date` is before their `start_date` in an employment model.

```python
from datetime import date
from pydantic import BaseModel, validator, ValidationError

class EmploymentRecord(BaseModel):
    name: str
    birth_date: date
    start_date: date

    @validator('start_date')
    def start_date_after_birth(cls, v, values):
        if 'birth_date' in values and v < values['birth_date']:
            raise ValueError('Start date must be after birth date')
        return v

# Correct usage
record = EmploymentRecord(
    name='John Doe',
    birth_date=date(1990, 1, 1),
    start_date=date(2010, 1, 1)
)

# This will raise a ValidationError
try:
    record = EmploymentRecord(
        name='Jane Doe',
        birth_date=date(2000, 1, 1),
        start_date=date(1995, 1, 1)
    )
except ValidationError as e:
    print(e)
```

In this example, the `start_date_after_birth` validator checks that the `start_date` is after the `birth_date`. The function uses the `values` dictionary to access previously validated fields.

---

## Pre and Post Validation

Pydantic allows you to define when a validator runs: **before** or **after** the model is initialized. This is controlled using the `pre` and `each_item` parameters of the `@validator` decorator.

- **Pre validation** (`pre=True`): Useful for transforming data before it is assigned to the model, such as normalizing strings or parsing raw data.
- **Post validation** (`pre=False`): Used to validate data after it has been assigned to the model, ensuring that all other fields have already been processed.

### Pre Validation Example: Normalizing Data

```python
from pydantic import BaseModel, validator
import re

class User(BaseModel):
    name: str

    @validator('name', pre=True)
    def normalize_name(cls, v):
        return v.strip().lower()

# Usage
user = User(name='  John DOE  ')
print(user.name)  # Output: 'john doe'
```

This validator normalizes the `name` field by stripping whitespace and converting it to lowercase. Because it's a pre-validator, it runs before any other validations or assignments.

### Post Validation Example: Cross-Field Check

```python
from pydantic import BaseModel, validator
from datetime import date

class User(BaseModel):
    name: str
    birth_date: date
    is_adult: bool

    @validator('is_adult', pre=False)
    def check_adult_status(cls, v, values):
        if 'birth_date' not in values:
            return v
        today = date.today()
        age = today.year - values['birth_date'].year
        if age < 18:
            return False
        return v

user = User(name='Alice', birth_date=date(2000, 1, 1), is_adult=True)
print(user.is_adult)  # Output: True

user = User(name='Bob', birth_date=date(2010, 1, 1), is_adult=True)
print(user.is_adult)  # Output: False
```

In this case, the `check_adult_status` validator modifies the `is_adult` field based on the `birth_date`. It can also be used to enforce that `is_adult` is always consistent with the user's age.

---

## Practical Use Cases

### Email and Password Matching

A common requirement in user registration forms is to ensure that the password and password confirmation fields match.

```python
from pydantic import BaseModel, validator

class RegisterForm(BaseModel):
    email: str
    password: str
    confirm_password: str

    @validator('confirm_password')
    def passwords_match(cls, v, values):
        if 'password' in values and v != values['password']:
            raise ValueError('Passwords do not match')
        return v

form = RegisterForm(
    email='user@example.com',
    password='s3cr3t',
    confirm_password='s3cr3t'
)

try:
    form = RegisterForm(
        email='user@example.com',
        password='s3cr3t',
        confirm_password='wrong'
    )
except ValueError as e:
    print(e)
```

This validator ensures that the `confirm_password` matches the `password` field. Without such a check, it would be possible to accidentally register with mismatched passwords.

---

### Business Rule Enforcement

Business rules often require complex validations that are not easily expressed in standard types or regex. For example, you might need to validate that a product’s price is only discounted if a certain condition is met.

```python
from pydantic import BaseModel, validator

class Product(BaseModel):
    name: str
    price: float
    is_discounted: bool
    discounted_price: float

    @validator('discounted_price')
    def validate_discounted_price(cls, v, values):
        if 'is_discounted' not in values or not values['is_discounted']:
            if v != values['price']:
                raise ValueError('Discounted price must equal actual price when not discounted')
        else:
            if v >= values['price']:
                raise ValueError('Discounted price must be less than actual price')
        return v

product = Product(
    name='Laptop',
    price=1000,
    is_discounted=True,
    discounted_price=800
)

try:
    product = Product(
        name='Laptop',
        price=1000,
        is_discounted=True,
        discounted_price=1200
    )
except ValueError as e:
    print(e)
```

This example ensures that the `discounted_price` is valid based on the `is_discounted` flag. It demonstrates how Pydantic can be used to enforce domain-specific logic.

---

## Best Practices

- **Use field validators for simple, per-field checks** and model validators for complex, cross-field logic.
- **Leverage `pre=True` for data normalization or transformation**, and `pre=False` for final validation or business rule enforcement.
- **Avoid side effects in validators**—they should not modify unrelated fields unless explicitly designed to do so.
- **Keep validator logic focused and testable**, ideally with unit tests for each validation rule.
- **Use descriptive error messages** to improve clarity for end users or downstream systems.
- **Avoid overlapping or redundant validation logic** between fields and models to maintain simplicity.

---

## Cross-Reference with Field Types and Validation

Pydantic integrates field types and validation closely. For example, the `email` field is typically a string, but its validation logic is implemented via a custom validator rather than a built-in type.

See the [Field Types documentation (03)](reference-to-03) for more details on how to define and customize field types. Similarly, the [Validation documentation (03)](reference-to-03) provides an overview of Pydantic’s validation lifecycle and how custom rules fit in.

---

## Troubleshooting and Common Pitfalls

### 1. **Validator Order Matters**

If multiple validators are defined on the same field, their order affects execution. Pydantic applies them in the order they are defined. To avoid conflicts, ensure that validators are logically ordered—transformations come first, followed by validations.

### 2. **Incorrect Use of `values`**

When accessing other fields in a validator, make sure to check that they exist in the `values` dictionary. For example, accessing `values['birth_date']` before the `birth_date` field is validated can cause errors if the field is missing or invalid.

### 3. **Overusing `@root_validator`**

In Pydantic v1, `@root_validator` was used for model-wide validations. In v2, it's replaced with `model_validator`. Be cautious about applying root validators to large models, as they can obscure the source of validation errors.

---

## Conclusion

Custom validators in Pydantic are a powerful tool for enforcing domain-specific business rules and ensuring data integrity. Whether validating a simple email format or enforcing complex relationships between fields, Pydantic provides a flexible and expressive API for building robust validation logic.

By understanding the distinction between field and model validators, and how to use `pre` and `post` stages effectively, developers can create clean, maintainable models that handle even the most complex validation scenarios.

Always consider the impact of validators on performance and readability, and strive to keep validation logic focused, predictable, and well-documented.