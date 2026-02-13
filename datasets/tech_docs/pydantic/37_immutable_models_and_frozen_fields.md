# Immutable Models and Frozen Fields

Immutable models and frozen fields are essential patterns in software development, particularly when working with data classes or models that should not change after initialization. In Python, especially with frameworks like Pydantic, immutability ensures data integrity, simplifies reasoning about state, and enables powerful features like hashable models and safe sharing between threads.

This guide explores Pydantic’s `frozen=True` feature, immutability patterns, and how they enable value objects and hashable models. We’ll also highlight when and why immutability is useful, with practical examples.

---

## Understanding Immutability in Pydantic

Pydantic allows developers to define data models using Python type annotations. One of its most useful features is the `frozen=True` parameter available in `BaseModel`. When applied, it prevents attribute assignment after model instantiation, effectively making the model immutable.

```python
from pydantic import BaseModel

class Point(BaseModel):
    x: int
    y: int

class FrozenPoint(BaseModel, frozen=True):
    x: int
    y: int

p1 = FrozenPoint(x=1, y=2)
p1.x = 3  # Raises: AttributeError: 'FrozenPoint' object has no attribute 'x'
```

By making a model `frozen`, you enforce that instances cannot be modified after creation, which is crucial for scenarios where data integrity is paramount.

---

## Why Use Frozen Models?

### 1. **Data Integrity**
Frozen models prevent unintended modifications to the data, which is particularly important in systems where data should not be changed once created (e.g., logs, audit records, or mathematical value objects).

### 2. **Simpler Concurrency**
Immutable data is inherently thread-safe. When multiple threads access a frozen model, there’s no risk of data corruption due to simultaneous writes.

### 3. **Cache Keys and Hashing**
A frozen model can be made hashable, enabling usage as a key in dictionaries or as an element in sets.

```python
from pydantic import BaseModel
from typing import Dict

class CacheKey(BaseModel, frozen=True):
    user_id: int
    query: str

cache: Dict[CacheKey, str] = {}

key = CacheKey(user_id=123, query="search term")
cache[key] = "cached_result"
```

This becomes a powerful pattern for caching strategies, especially in microservices or distributed systems.

---

## Hashable Models and Immutability

By default, Pydantic models are not hashable. However, when a model is frozen, it becomes hashable if all of its field types are also hashable. You can explicitly add `__hash__` to enable this behavior, or rely on Python’s default hashing for immutable objects.

```python
from pydantic import BaseModel

class HashableId(BaseModel, frozen=True):
    id: int
    name: str

    def __hash__(self):
        return hash((self.id, self.name))

id1 = HashableId(id=1, name="Alice")
id2 = HashableId(id=1, name="Alice")
id3 = HashableId(id=2, name="Bob")

print(id1 == id2)  # True
print(id1 in {id1, id3})  # True
```

Note that if your model contains non-hashable types like `list`, `set`, or `dict`, you must convert them to hashable counterparts like `tuple` or `frozenset` before using the model in hash-based collections.

---

## Practical Use Cases

### Value Objects

Value objects are objects where identity is not important—only their properties matter. They are ideal use cases for frozen models.

```python
from pydantic import BaseModel

class Money(BaseModel, frozen=True):
    amount: float
    currency: str

def add(a: Money, b: Money) -> Money:
    if a.currency != b.currency:
        raise ValueError("Currencies do not match")
    return Money(amount=a.amount + b.amount, currency=a.currency)
```

By making `Money` a frozen model, we ensure that its value cannot be altered after creation, making it safe to use in financial calculations, caching, and stateless logic.

---

### Config Classes

Frozen models are also useful for defining configuration classes, especially when shared across different parts of an application.

```python
from pydantic import BaseModel

class AppConfig(BaseModel, frozen=True):
    debug: bool
    db_url: str
    rate_limit: int

config = AppConfig(debug=True, db_url="sqlite:///app.db", rate_limit=100)

# config.debug = False  # Raises: AttributeError
```

This ensures that the configuration remains consistent throughout the application lifecycle, preventing runtime changes that could lead to unexpected behavior.

---

## Cross-Reference with Other Patterns

### Config Class (13)

Frozen models are a natural fit for configuration objects. When combined with `Config` class attributes, such as `extra_forbid=True` or `validate_all=True`, you can enforce strict validation and immutability at the same time.

```python
from pydantic import BaseModel

class StrictConfig(BaseModel, frozen=True):
    class Config:
        extra_forbid = True
        validate_all = True

    env: str
    timeout: int

config = StrictConfig(env="dev", timeout=5)
```

This ensures that any attempt to pass extra or invalid parameters results in a `ValidationError`.

### Private Attributes (27)

Private attributes in Pydantic are defined with underscores and are not included in model validation or serialization by default. However, they can be combined with frozen models to encapsulate internal state.

```python
from pydantic import BaseModel, PrivateAttr

class EncryptedData(BaseModel, frozen=True):
    key: str
    _data: str = PrivateAttr()

    def __init__(self, key: str, data: str):
        super().__init__(key=key)
        self._data = data

    def decrypt(self) -> str:
        return self._data  # In a real app, this would involve decryption logic
```

This pattern allows you to expose a frozen interface while maintaining internal mutable state as private attributes.

---

## Best Practices

### 1. Use Frozen Models for Value Objects
Whenever data should not change after creation, use `frozen=True`. This is especially useful for mathematical models, identifiers, and configuration classes.

### 2. Make Sure All Fields Are Hashable
If you plan to use a model as a key in a dictionary or set, ensure all fields are hashable. This often means using `tuple`, `frozenset`, or `str` where appropriate.

### 3. Avoid Nested Mutable Types
Fields like `list`, `dict`, or `set` are mutable and not hashable. If you need to store such data in a frozen model, convert them to immutable types like `tuple` or `frozenset`.

```python
class FrozenList(BaseModel, frozen=True):
    values: tuple[int, ...]
```

### 4. Use `copy` for Modifications
If you need to create a modified version of a frozen model, use the `copy` method:

```python
from pydantic import BaseModel

class Person(BaseModel, frozen=True):
    name: str
    age: int

p1 = Person(name="Alice", age=30)
p2 = p1.copy(update={"age": 31})

print(p1.age)  # 30
print(p2.age)  # 31
```

This is a safe and idiomatic way to create new versions of immutable models.

---

## Common Pitfalls

### 1. Accidental Mutation of Nested Objects

Even if a model is frozen, if it contains mutable fields like `list`, those can still be modified:

```python
from pydantic import BaseModel

class User(BaseModel, frozen=True):
    tags: list[str]

user = User(tags=["python", "dev"])
user.tags.append("pydantic")  # This works! Mutation is possible

print(user.tags)  # ["python", "dev", "pydantic"]
```

To avoid this, always use immutable types like `tuple` for such fields.

### 2. Confusing `frozen=True` with `dataclass(frozen=True)`

While Pydantic and Python’s `dataclass` both support freezing, Pydantic adds validation, type checking, and parsing. In Pydantic, `frozen=True` works with `BaseModel`, not `dataclass`.

---

## Conclusion

Immutable models and frozen fields are powerful tools for maintaining data integrity and enforcing safe usage in applications. With Pydantic, using `frozen=True` not only makes models immutable but also enables hashability, safe concurrency, and clean API design.

By applying these patterns, developers can build reliable and predictable systems that are easier to test, debug, and maintain. Whether you’re building value objects, configuration classes, or cache keys, the principles of immutability offer both safety and clarity in production systems.