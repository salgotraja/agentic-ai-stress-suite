# Field Types and Validation

Pydantic supports a rich ecosystem of field types for comprehensive data validation. From primitive types to complex nested structures, understanding field types is crucial for building robust validation schemas. This guide covers all major field types and their validation behaviors.

## Primitive Types

Python's built-in primitive types form the foundation of Pydantic validation:

### String Types

```python
from pydantic import BaseModel

class TextData(BaseModel):
    name: str          # Any string
    description: str   # Any string
    code: str          # Any string
```

Validation behavior:

```python
# Valid
data = TextData(name="Alice", description="User profile", code="ABC123")

# Type coercion from compatible types
data = TextData(name=123, description=True, code=45.67)
# Converts to: name="123", description="True", code="45.67"
```

### Numeric Types

```python
class NumericData(BaseModel):
    count: int          # Integer
    price: float        # Floating-point
    ratio: float        # Floating-point
    complex_num: complex  # Complex number
```

Coercion rules:

```python
# String to int/float
data = NumericData(count="42", price="19.99", ratio="0.5", complex_num="1+2j")

# Float to int truncates (in loose mode)
data = NumericData(count=42.9, price=19.99, ratio=0.5, complex_num=1+2j)
# count becomes 42
```

### Boolean Types

```python
class Flags(BaseModel):
    is_active: bool
    is_admin: bool
    is_verified: bool
```

Truthy/falsy coercion:

```python
# String coercion
Flags(is_active="true", is_admin="false", is_verified="yes")
# is_active=True, is_admin=False, is_verified=True

# Numeric coercion
Flags(is_active=1, is_admin=0, is_verified=42)
# is_active=True, is_admin=False, is_verified=True

# Special string values
# "true", "yes", "y", "on", "1" → True
# "false", "no", "n", "off", "0" → False
```

## Collection Types

Pydantic validates complex collection structures with full type checking:

### Lists

```python
from typing import List

class ListExamples(BaseModel):
    tags: List[str]           # List of strings
    scores: List[int]         # List of integers
    matrix: List[List[float]] # Nested lists
```

Validation:

```python
data = ListExamples(
    tags=["python", "pydantic", "validation"],
    scores=[95, 87, 92],
    matrix=[[1.0, 2.0], [3.0, 4.0]]
)

# Type coercion in lists
data = ListExamples(
    tags=[1, 2, 3],           # Converts to ["1", "2", "3"]
    scores=["95", "87", "92"], # Converts to [95, 87, 92]
    matrix=[["1", "2"], ["3", "4"]]
)
```

### Tuples

```python
from typing import Tuple

class TupleExamples(BaseModel):
    coordinates: Tuple[float, float]        # Exactly 2 floats
    rgb: Tuple[int, int, int]              # Exactly 3 ints
    mixed: Tuple[str, int, bool]           # Mixed types
    variable: Tuple[int, ...]              # Variable length
```

Fixed-length tuples are strictly validated:

```python
# Valid
data = TupleExamples(
    coordinates=(10.5, 20.3),
    rgb=(255, 128, 0),
    mixed=("Alice", 30, True),
    variable=(1, 2, 3, 4, 5)
)

# Invalid - wrong length
# TupleExamples(coordinates=(10.5,))  # ValidationError
```

### Sets

```python
from typing import Set

class SetExamples(BaseModel):
    unique_tags: Set[str]
    unique_ids: Set[int]
```

Automatically removes duplicates:

```python
data = SetExamples(
    unique_tags=["python", "pydantic", "python"],  # Deduplicates to {"python", "pydantic"}
    unique_ids=[1, 2, 3, 2, 1]                     # Deduplicates to {1, 2, 3}
)
```

### Dictionaries

```python
from typing import Dict

class DictExamples(BaseModel):
    metadata: Dict[str, str]              # String keys and values
    scores: Dict[str, int]                # String keys, int values
    nested: Dict[str, Dict[str, float]]   # Nested dicts
```

Key and value validation:

```python
data = DictExamples(
    metadata={"author": "Alice", "version": "1.0"},
    scores={"math": 95, "english": 87},
    nested={"student1": {"math": 95.5, "english": 87.3}}
)

# Type coercion applies to both keys and values
data = DictExamples(
    metadata={1: 2, 3: 4},  # Converts to {"1": "2", "3": "4"}
    scores={"math": "95"},   # Converts value to int
    nested={"student1": {"math": "95.5"}}
)
```

## Optional and Union Types

Handle optional fields and multiple possible types:

### Optional Fields

```python
from typing import Optional

class UserProfile(BaseModel):
    username: str
    email: str
    bio: Optional[str] = None        # Can be str or None
    avatar_url: Optional[str] = None
    age: Optional[int] = None
```

Usage:

```python
# All optional fields omitted
user = UserProfile(username="alice", email="alice@example.com")

# Some optional fields provided
user = UserProfile(
    username="alice",
    email="alice@example.com",
    bio="Software engineer",
    age=30
)
```

### Union Types

```python
from typing import Union

class FlexibleModel(BaseModel):
    identifier: Union[int, str]      # Can be int or str
    value: Union[float, str, None]   # Can be float, str, or None
```

Validation attempts types in order:

```python
# First matching type wins
data = FlexibleModel(identifier=123, value=45.6)        # int, float
data = FlexibleModel(identifier="ABC", value="text")   # str, str
data = FlexibleModel(identifier="123", value=None)     # str, None
```

## Date and Time Types

```python
from datetime import datetime, date, time, timedelta
from pydantic import BaseModel

class TemporalData(BaseModel):
    created_at: datetime      # Full datetime
    birth_date: date         # Date only
    meeting_time: time       # Time only
    duration: timedelta      # Time duration
```

Flexible parsing:

```python
data = TemporalData(
    created_at="2024-01-15T10:30:00",
    birth_date="1990-05-20",
    meeting_time="14:30:00",
    duration="2 days, 3:30:00"
)

# Also accepts Unix timestamps for datetime
data = TemporalData(
    created_at=1705315800,  # Unix timestamp
    birth_date="1990-05-20",
    meeting_time="14:30:00",
    duration=7200  # Seconds
)
```

## Literal Types

Restrict values to specific literals:

```python
from typing import Literal

class Config(BaseModel):
    environment: Literal["development", "staging", "production"]
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]
```

Only specified values are valid:

```python
# Valid
config = Config(environment="production", log_level="INFO")

# Invalid
# config = Config(environment="test", log_level="INFO")  # ValidationError
```

## Enum Types

Use Python enums for better type safety:

```python
from enum import Enum

class Status(str, Enum):
    PENDING = "pending"
    ACTIVE = "active"
    INACTIVE = "inactive"
    DELETED = "deleted"

class UserAccount(BaseModel):
    username: str
    status: Status
```

Validation:

```python
# Using enum members
user = UserAccount(username="alice", status=Status.ACTIVE)

# Using string values
user = UserAccount(username="alice", status="active")

print(user.status)        # Status.ACTIVE
print(user.status.value)  # "active"
```

## Bytes Types

```python
class BinaryData(BaseModel):
    content: bytes
    encoded: bytes
```

Accepts bytes or strings (encoded as UTF-8):

```python
data = BinaryData(
    content=b"raw bytes",
    encoded="text to encode"
)
```

## Path Types

```python
from pathlib import Path

class FileConfig(BaseModel):
    input_path: Path
    output_path: Path
    config_file: Path
```

Converts strings to Path objects:

```python
config = FileConfig(
    input_path="/data/input.txt",
    output_path="/data/output.txt",
    config_file="config.json"
)

print(type(config.input_path))  # <class 'pathlib.PosixPath'>
```

## UUID Types

```python
from uuid import UUID

class Resource(BaseModel):
    id: UUID
    user_id: UUID
```

Validates and parses UUID strings:

```python
resource = Resource(
    id="123e4567-e89b-12d3-a456-426614174000",
    user_id="123e4567-e89b-12d3-a456-426614174001"
)

print(type(resource.id))  # <class 'uuid.UUID'>
```

## URL Types

```python
from pydantic import HttpUrl, AnyUrl

class LinkData(BaseModel):
    website: HttpUrl          # Must be valid HTTP/HTTPS URL
    resource: AnyUrl         # Any valid URL scheme
```

Validates URL format:

```python
data = LinkData(
    website="https://example.com/page",
    resource="ftp://files.example.com/file.txt"
)

# Invalid URLs raise ValidationError
# data = LinkData(website="not a url", resource="invalid")
```

## Email Types

```python
from pydantic import EmailStr

class Contact(BaseModel):
    email: EmailStr  # Requires pydantic[email] extra
    name: str
```

Validates email format (requires email-validator library):

```python
contact = Contact(email="alice@example.com", name="Alice")

# Invalid email raises ValidationError
# contact = Contact(email="not-an-email", name="Alice")
```

## FastAPI Integration

FastAPI leverages Pydantic's field types for automatic API documentation:

```python
from fastapi import FastAPI
from pydantic import BaseModel, EmailStr, HttpUrl
from typing import List, Optional
from datetime import datetime

app = FastAPI()

class Article(BaseModel):
    title: str
    content: str
    author_email: EmailStr
    tags: List[str]
    published_at: Optional[datetime] = None
    source_url: Optional[HttpUrl] = None

@app.post("/articles/")
async def create_article(article: Article):
    # FastAPI automatically:
    # - Validates all field types
    # - Generates OpenAPI schema with correct types
    # - Provides interactive docs with type information
    return {"message": "Article created", "title": article.title}
```

The generated OpenAPI schema includes:
- String format for email and URL
- Array type for tags
- DateTime format for published_at
- Nullable fields for optional parameters

## Any Type

When validation isn't needed:

```python
from typing import Any

class FlexibleData(BaseModel):
    validated_field: str
    raw_data: Any  # No validation, accepts anything
```

Use sparingly - defeats the purpose of Pydantic validation.

## Conclusion

Pydantic's comprehensive type system enables precise validation for any data structure. From simple primitives to complex nested collections, the type system ensures data integrity while providing helpful error messages. Understanding these field types allows you to build robust validation schemas that catch errors early and provide clear feedback to users.

When designing models, choose the most specific type that fits your data. More specific types provide better validation, clearer documentation, and fewer runtime errors. FastAPI uses these types to generate accurate API documentation automatically, making your APIs self-documenting and easier to integrate.
