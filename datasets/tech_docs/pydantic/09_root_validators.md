# Root Validators

In Pydantic, **root validators** (`@root_validator`) are used to perform model-level validation that spans multiple fields or involves complex, cross-field logic. Unlike field-specific validators that operate on individual attributes, root validators can inspect and validate the state of the entire model instance. They are essential when data integrity depends on the relationship between fields or when conditional logic requires checking the combined values of multiple fields.

This document explores how to implement root validators effectively, including when to use them, how to write conditional and consistency checks, and the best practices for ensuring robust validation logic in real-world scenarios.

---

## Understanding Model-Level Validation

Pydantic's validation system is primarily based on type hints and field-level validators. However, certain validation rules are not confined to a single field. For example, the presence of one field might depend on the value of another, or multiple fields must be consistent with each other.

This is where `@root_validator` becomes essential. It allows you to define logic that operates on the entire model's data at once. The validator can access the model's values, modify them if necessary, or raise a `ValueError` if the validation fails.

A key benefit of root validators is that they enable **cross-field validation**, which is not possible with standard field validators.

---

## Syntax and Basic Usage

The syntax for defining a root validator is as follows:

```python
from pydantic import BaseModel, root_validator, validator

class MyModel(BaseModel):
    field1: str
    field2: int

    @root_validator
    def check_cross_field_values(cls, values):
        if values["field1"] == "special" and values["field2"] > 100:
            raise ValueError("field1 being 'special' requires field2 <= 100")
        return values
```

In this example, the `check_cross_field_values` root validator ensures that if `field1` is set to `"special"`, then `field2` cannot exceed `100`.

### Parameters and Return Values

- The method receives the class (`cls`) and a `values` dictionary containing the model's data.
- It must return the modified or unchanged `values` dictionary.
- If any validation logic fails, a `ValueError` must be raised.

Root validators can also be used with the `pre=True` flag to run *before* field-level validation:

```python
@root_validator(pre=True)
def preprocess_values(cls, values):
    # perform any preprocessing or normalization
    return values
```

This is useful for cases where you want to clean or normalize input data before individual fields are validated.

---

## Conditional Field Requirements

One common use case for root validators is enforcing **conditional field requirements**, where the presence or value of one field depends on another.

### Example: Conditional Field Dependency

Suppose you're modeling a payment system where a transaction must include a `reference_id` if the amount exceeds a certain threshold:

```python
class Transaction(BaseModel):
    amount: float
    reference_id: str = None

    @root_validator
    def validate_reference_dependency(cls, values):
        amount = values.get("amount")
        reference_id = values.get("reference_id")

        if amount > 1000 and not reference_id:
            raise ValueError("reference_id is required when amount exceeds 1000")

        return values
```

In this example, if `amount` is greater than `1000`, the `reference_id` must be provided. This ensures that large transactions are always traceable.

### Use Cases and Patterns

- Enforcing required fields based on other fields (e.g., `password_confirmation` must match when `password` is present).
- Conditional validation based on the model's context (e.g., `discount_code` must be valid if `is_discounted` is `True`).
- Deprecating or hiding fields conditionally (e.g., `legacy_field` must be `None` if `new_field` is present).

---

## Consistency Checks Across Fields

Another powerful use of root validators is to ensure **consistency among multiple fields**. This includes checking for logical contradictions, ensuring fields are mutually exclusive, or validating ranges together.

### Example: Ensuring Consistent Time Intervals

Consider a model where `start_time` must be before `end_time`, and both must be in the future:

```python
from datetime import datetime

class Event(BaseModel):
    start_time: datetime
    end_time: datetime

    @root_validator
    def validate_time_consistency(cls, values):
        start_time = values.get("start_time")
        end_time = values.get("end_time")

        if start_time and end_time:
            if start_time > end_time:
                raise ValueError("start_time must be before end_time")
            if start_time < datetime.now():
                raise ValueError("start_time must be in the future")
        return values
```

This validator ensures that:
- The event does not start after it ends.
- The event does not start in the past.

---

## Best Practices for Root Validators

When implementing root validators, it's important to follow best practices to ensure clarity, maintainability, and correctness.

### 1. Keep Root Validators Focused

Each root validator should address one specific validation concern. Avoid creating monolithic validators that handle multiple unrelated checks. Instead, split them into multiple smaller validators with distinct responsibilities.

### 2. Use `pre=True` for Data Normalization

Use `@root_validator(pre=True)` to normalize or clean input data before it reaches field validation. For example, converting string representations of numbers to actual integers or handling case sensitivity in strings.

### 3. Avoid Side Effects

Root validators should not modify external state or have side effects beyond adjusting the `values` dictionary. They should be pure functions that only validate or preprocess data.

### 4. Prioritize Error Messages

Provide clear and actionable error messages. Instead of generic errors like `"invalid data"`, include specific field names and conditions that failed validation:

```python
raise ValueError("When is_discounted is True, discount_code must be provided")
```

### 5. Combine with Field-Level Validators

Use field-level validators for simple, per-field checks and fall back to root validators for complex, cross-field logic. This keeps your validation logic modular and scalable.

### 6. Test Root Validators Thoroughly

Because root validators operate on the entire model, they can be more complex and harder to reason about. Write comprehensive unit tests covering all edge cases, especially those involving conditional logic and field dependencies.

---

## Cross-Validator Integration and Custom Validation

Root validators can be used alongside custom field-level validators (`@validator`) to create a layered validation strategy. For example:

```python
class User(BaseModel):
    email: str
    password: str
    password_confirmation: str

    @validator("password_confirmation")
    def passwords_match(cls, v, values):
        if v != values.get("password"):
            raise ValueError("passwords do not match")
        return v

    @root_validator
    def check_password_strength(cls, values):
        password = values.get("password")
        if len(password) < 8:
            raise ValueError("password must be at least 8 characters long")
        return values
```

In this example:
- A field-level validator ensures that the password and confirmation match.
- A root validator enforces a minimum password length.

This combination provides a robust validation strategy that is both modular and extensible.

---

## Comparison with Other Validation Approaches

In contrast to field-level validators or custom validation logic in application code, root validators offer **model-level validation** that is declarative, reusable, and tightly integrated with Pydantic's data model.

For example, in Django's `ModelForm`, you might write:

```python
def clean(self):
    cleaned_data = super().clean()
    if cleaned_data.get('start_time') > cleaned_data.get('end_time'):
        raise forms.ValidationError("Start time must precede end time.")
    return cleaned_data
```

This approach is functionally similar to Pydantic's `@root_validator`, but Pydantic's integration with Python type hints and model-based validation provides a more modern and Pythonic interface.

---

## Advanced Use Cases and Edge Cases

### 1. Field Presence and Optional Fields

When dealing with optional fields, be cautious about `KeyError`s in the `values` dictionary. Always use `.get()` or check for field presence before accessing:

```python
@root_validator
def validate_optional_fields(cls, values):
    if "optional_field" in values and values["optional_field"] == "":
        raise ValueError("optional_field cannot be an empty string")
    return values
```

### 2. Conditional Logic Based on Multiple Fields

You can validate combinations of field values, such as validating a `role` in conjunction with `permissions`:

```python
class User(BaseModel):
    role: str
    permissions: list[str]

    @root_validator
    def validate_role_permissions(cls, values):
        role = values.get("role")
        permissions = values.get("permissions", [])

        if role == "admin" and "delete" not in permissions:
            raise ValueError("Admin role must have 'delete' permission")
        return values
```

### 3. Cross-Model Validation

In more complex scenarios, you might need to validate relationships between multiple models. For example, ensuring a `User` model has a `Team` model with matching `team_id`:

```python
class Team(BaseModel):
    team_id: str
    name: str

class User(BaseModel):
    user_id: str
    team_id: str

    @root_validator
    def validate_team_exists(cls, values):
        user_team_id = values["team_id"]
        # Assume a lookup function that fetches existing teams
        if not get_team_from_db(user_team_id):
            raise ValueError(f"Team with ID {user_team_id} does not exist")
        return values
```

---

## Troubleshooting and Common Pitfalls

### 1. Field Not Present in `values`

If a field is optional and not always present, accessing it directly in the `values` dictionary can raise a `KeyError`. Always use `.get()` or check for presence.

### 2. Conflicts with Field-Level Validators

Field-level validators run *after* root validators (unless `pre=True` is used). Be aware of the order of validation to avoid unexpected behavior.

### 3. Over-validated Models

Avoid overusing root validators for simple validations. This can lead to complex, hard-to-maintain models. Use them only when cross-field logic is necessary.

### 4. Poor Error Message Design

Vague or generic error messages can make debugging difficult. Always provide context-aware messages that clearly identify the cause of validation failure.

---

## Conclusion

Root validators are a powerful tool in Pydantic for implementing model-level validation logic that spans multiple fields or involves complex conditions. By understanding their role in the validation lifecycle and applying best practices, you can build robust, maintainable, and scalable data models.

When used appropriately, root validators help enforce data integrity and business rules at the model level, reducing the need for additional validation logic in application code.

By combining root validators with field-level validators and custom logic, you can create a comprehensive validation strategy that ensures correctness, clarity, and consistency in your applications.