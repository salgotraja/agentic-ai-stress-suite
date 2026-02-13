# Pydantic V2 Migration Guide

The transition from Pydantic V1 to V2 is a significant step that affects not only how models are defined but also how validation, serialization, and error handling are structured. While Pydantic V2 retains core functionality, such as data validation using Python type hints, it introduces several breaking changes, performance improvements, and a more Pythonic API. This guide provides a comprehensive overview of the migration process, including key differences, migration patterns, and tools to facilitate the upgrade.

---

## Key Changes in Pydantic V2

Pydantic V2 brings a number of architectural changes, including a new `BaseModel` implementation based on Python’s dataclass features, a more robust validation system, and the introduction of `model_validator` for custom validation logic. Here are the most impactful changes:

- **BaseModel is now a dataclass**: This change allows for better integration with Python’s standard library and enables more flexible object creation.
- **Validation is more flexible and powerful**: V2 allows for field-level and model-level validation using `model_validator`, which can be applied to multiple fields or the model as a whole.
- **Config is now a class attribute**: The `Config` class replaces the previous `Config` dictionary and supports more structured configuration.
- **Removed support for `parse_obj`, `parse_raw`, etc.**: These have been replaced with a unified interface via `model_validate()` and `model_dump()` methods.
- **Field defaults are now set using `__init__`**: This means that default values must be set in the constructor, which can change behavior if not handled correctly.

---

## Migrating Code from V1 to V2

Migrating from V1 to V2 often involves minimal code changes but requires understanding the new model lifecycle and validation workflow. Below is a step-by-step guide along with code examples.

### Step 1: Update `BaseModel` Usage

In Pydantic V1, `BaseModel` was a base class with a custom metaclass. In V2, it’s now a dataclass under the hood, which affects how defaults and initializations are handled.

**V1 Example:**
```python
from pydantic import BaseModel

class UserV1(BaseModel):
    name: str
    age: int = 30
```

**V2 Equivalent:**
```python
from pydantic import BaseModel

class UserV2(BaseModel):
    name: str
    age: int = 30
```

Though the code looks the same, under the hood, V2 uses a more standard Python object model, which can lead to subtle behavioral changes. For example, `__slots__` are now supported, and instance creation is faster.

---

### Step 2: Replace `parse_obj` with `model_validate`

In V1, `parse_obj` was used to create a model from a dictionary. In V2, this is now replaced with `model_validate`.

**V1 Example:**
```python
user_v1 = UserV1.parse_obj({"name": "Alice", "age": 35})
```

**V2 Equivalent:**
```python
user_v2 = UserV2.model_validate({"name": "Alice", "age": 35})
```

This change is part of a broader effort to make the API more consistent and aligned with Python’s built-in methods.

---

### Step 3: Use `model_dump()` instead of `dict()`

In V1, calling `dict()` on a model instance returned a dictionary of the model's attributes. In V2, this has been replaced with `model_dump()`.

**V1 Example:**
```python
data_v1 = user_v1.dict()
```

**V2 Equivalent:**
```python
data_v2 = user_v2.model_dump()
```

The `model_dump()` method is more flexible and allows for options like `exclude_unset`, `exclude_defaults`, and `exclude_none`.

---

### Step 4: Move Validation Logic to `model_validator`

In V1, validation was often done using `root_validator` and `validator`. In V2, these are replaced with `model_validator` and `field_validator`.

**V1 Example:**
```python
from pydantic import BaseModel, validator

class UserV1(BaseModel):
    name: str
    age: int

    @validator('age')
    def check_age(cls, v):
        if v < 0:
            raise ValueError('age must be positive')
        return v
```

**V2 Equivalent:**
```python
from pydantic import BaseModel, field_validator

class UserV2(BaseModel):
    name: str
    age: int

    @field_validator('age')
    def check_age(cls, v):
        if v < 0:
            raise ValueError('age must be positive')
        return v
```

Note that `field_validator` is used for field-specific validation, while `model_validator` is used for model-wide validation logic.

---

### Step 5: Refactor Config Settings

In V1, `Config` was a dictionary-like object. In V2, it’s a class attribute with its own configuration options.

**V1 Example:**
```python
class UserV1(BaseModel):
    name: str
    age: int

    Config = ConfigDict(orm_mode=True)
```

**V2 Equivalent:**
```python
class UserV2(BaseModel):
    name: str
    age: int

    model_config = ConfigDict(orm_mode=True)
```

Also note that `orm_mode` is now called `from_attributes` in V2.

---

## Migration Tools and Compatibility Shims

To ease migration, Pydantic provides tools and shims to help migrate large codebases incrementally.

### Compatibility Shims

The `pydantic.v1` module is available in V2 to import V1 classes and functions for backward compatibility. This allows you to gradually migrate your codebase without rewriting everything at once.

```python
from pydantic.v1 import BaseModel as BaseModelV1

class LegacyModel(BaseModelV1):
    name: str
    age: int
```

This approach is useful when integrating new code with older libraries or APIs that still depend on V1.

---

### Migration Script Example

Here's a simple script to migrate a model from V1 to V2 by replacing `BaseModel` and validation decorators:

```python
from pydantic import BaseModel, field_validator
from typing import Optional

# V1-style model
class UserV1:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age

    @property
    def is_adult(self) -> bool:
        return self.age >= 18

# V2-style model
class UserV2(BaseModel):
    name: str
    age: int

    @field_validator('age')
    def check_age(cls, v: int) -> int:
        if v < 0:
            raise ValueError("Age must be positive")
        return v

    @property
    def is_adult(self) -> bool:
        return self.age >= 18
```

The V2 version is more robust, as it includes validation and supports serialization and deserialization out of the box.

---

## Best Practices for Migration

### 1. Start Small

Begin by migrating a small model or a section of your application. This allows you to identify issues and adjust your code incrementally.

### 2. Use Compatibility Imports

When parts of your codebase can't be migrated immediately, use `pydantic.v1` to avoid rewriting everything at once.

### 3. Refactor Validation Logic

Take the migration opportunity to refactor validation logic using `model_validator` and `field_validator`. This leads to cleaner, more maintainable code.

### 4. Test Thoroughly

Ensure that all validation and data transformation logic still works after migration. Pay special attention to error messages and field exclusions.

### 5. Update Third-Party Dependencies

Check that your external libraries and dependencies are compatible with Pydantic V2. Some may require updates or patches.

---

## Troubleshooting Common Issues

### 1. Missing `model_validate` or `model_dump`

If you see an `AttributeError` about missing attributes like `model_validate` or `model_dump`, make sure you are using Pydantic V2 and that you imported the correct `BaseModel`.

### 2. Validation Errors Not Triggering

If validation isn’t working as expected, verify that your `field_validator` or `model_validator` is correctly decorated and that it raises `ValueError` for invalid data.

### 3. ORM Mode Not Working

If `from_attributes=True` isn't working in `model_config`, ensure that your database model is compatible with Pydantic’s ORM integration. V2 uses the `dataclass` model for ORM compatibility, so ensure fields match and are accessible.

---

## Migration Patterns and Production-Ready Code

Here’s a more complex example of a V2 model that integrates with a database and includes field validation, error handling, and serialization:

```python
from pydantic import BaseModel, field_validator
from typing import Optional, List
from datetime import datetime

class BlogPost(BaseModel):
    id: int
    title: str
    content: str
    author_id: int
    created_at: datetime
    tags: List[str] = []

    @field_validator('title')
    def title_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Title cannot be empty")
        return v

    @field_validator('tags')
    def tags_lowercase(cls, v: List[str]) -> List[str]:
        return [tag.lower() for tag in v]

blog_post = BlogPost.model_validate({
    'id': 1,
    'title': "My First Post",
    'content': "Hello world!",
    'author_id': 123,
    'created_at': datetime.now(),
    'tags': ["PYTHON", "TUTORIAL"]
})
```

In production, consider wrapping model instantiation in try-except blocks to handle validation errors gracefully:

```python
from pydantic import ValidationError

try:
    blog_post = BlogPost.model_validate(data)
except ValidationError as e:
    print("Validation failed:", e)
```

---

## Cross-Reference with V2 Features

Pydantic V2 introduces new features such as:

- **Unions and Discriminated Unions**: Easier handling of multiple model types.
- **Custom Root Models**: For handling JSON arrays or complex root structures.
- **Serialization and Deserialization Hooks**: Fine-grained control over data conversion.
- **Improved JSON Schema Support**: Better integration with OpenAPI and JSON Schema tools.
- **Performance Improvements**: Models are faster to validate and serialize due to the use of dataclasses.

These features should be leveraged to build robust, scalable applications.

---

## Conclusion

Migrating from Pydantic V1 to V2 is a worthwhile investment that unlocks performance improvements, better validation, and a more Pythonic API. While the migration involves some code changes, it is typically manageable with the help of compatibility tools and incremental refactoring. By following best practices and leveraging new features, you can ensure a smooth transition and build more reliable data models for your applications.