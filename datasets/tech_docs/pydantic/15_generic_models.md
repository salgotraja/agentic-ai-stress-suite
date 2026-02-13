# Generic Models

Generic models in Pydantic are a powerful mechanism for creating reusable and type-safe data models. They enable developers to define flexible structures that can be parameterized with different data types, promoting code reuse and ensuring type consistency across applications. At the core of generic models is the `Generic[T]` base class from the `typing` module, which allows models to be defined with placeholder types that are filled in at usage. This capability is especially valuable when working with collections, response wrappers, or any system that needs to support diverse data types in a consistent manner.

## Understanding Type Parameters

To create a generic model, you must first define one or more type parameters using `TypeVar` from the `typing` module. These type parameters act as placeholders for concrete types that will be specified when the model is instantiated. For example:

```python
from typing import TypeVar, Generic
from pydantic import BaseModel

T = TypeVar('T')

class Response(Generic[T], BaseModel):
    status: int
    data: T
    message: str = ''
```

In the example above, `T` is a type variable representing a generic data type. The `Response` class is a generic Pydantic model that can wrap any type of data (`T`). When using `Response`, you can specify the concrete type of `T` to ensure type safety:

```python
response = Response[int](status=200, data=42, message='Success')
print(response.data)  # Output: 42
```

This flexibility becomes essential in APIs or systems where multiple data types need to be handled consistently, such as paginated results, error responses, or API wrappers.

## Practical Use Cases for Generic Models

### Response Wrappers

One of the most common use cases for generic models is in API response design. Many APIs return a standard structure with a status code, message, and payload data. Using a generic `Response` model ensures that the payload (`data`) can be of any type, while still maintaining a consistent structure across the application.

```python
from typing import TypeVar, Generic
from pydantic import BaseModel

T = TypeVar('T')

class Response(Generic[T], BaseModel):
    status: int
    message: str
    data: T

# Example usage with different data types
class User(BaseModel):
    id: int
    name: str

def get_user(user_id: int) -> Response[User]:
    user = User(id=1, name='Alice')
    return Response(status=200, message='OK', data=user)

def get_counter() -> Response[int]:
    return Response(status=200, message='OK', data=42)

# Usage
user_response = get_user(1)
print(user_response.data.name)  # Output: Alice

counter_response = get_counter()
print(counter_response.data)  # Output: 42
```

In this example, both `get_user` and `get_counter` return a `Response` model with different `data` types. The use of `Generic[T]` ensures that the type of `data` is preserved, and the type checker (e.g., mypy or IDE) can provide accurate autocompletion and error checking based on the concrete type.

### Collection Models

Generic models are also useful when working with collections like lists, dictionaries, or sets. Pydantic supports defining models that wrap collections with type annotations, allowing for robust validation and type inference.

```python
from typing import Generic, TypeVar, List
from pydantic import BaseModel

T = TypeVar('T')

class PagedList(Generic[T], BaseModel):
    items: List[T]
    total: int
    page: int
    per_page: int

class Product(BaseModel):
    id: int
    name: str
    price: float

# Example usage
products_data = [
    {"id": 1, "name": "Laptop", "price": 1200},
    {"id": 2, "name": "Phone", "price": 600},
]

product_list = PagedList[Product](items=[Product(**item) for item in products_data], total=2, page=1, per_page=2)
print(product_list.items[0].name)  # Output: Laptop
```

In this example, `PagedList` is a generic model that can be used to represent paginated data of any type. This pattern is widely used in APIs or data-processing pipelines where the structure of the collection is consistent across different data types.

## Advanced Type Parameters and Constraints

Pydantic supports multiple type parameters and even constraints using the `bound` argument in `TypeVar`. This allows you to enforce that only certain types can be used with a generic model. For example:

```python
from typing import TypeVar, Generic, Protocol
from pydantic import BaseModel

class Identifiable(Protocol):
    id: int

T = TypeVar('T', bound=Identifiable)

class EntityResponse(Generic[T], BaseModel):
    entity: T
    status: int
    message: str

class User(BaseModel):
    id: int
    name: str

class Product(BaseModel):
    id: int
    name: str
    price: float

def get_entity(entity_id: int) -> EntityResponse[User]:
    return EntityResponse(entity=User(id=1, name='Alice'), status=200, message='OK')

# Valid
get_entity(1)

# Invalid (Product doesn't satisfy Identifiable protocol)
# EntityResponse[Product] is not allowed due to bound constraint
```

Here, `EntityResponse` is constrained to types that implement the `Identifiable` protocol. This ensures that only models with an `id` field can be used with this generic response wrapper. This is particularly useful in large codebases where maintaining consistent interfaces is critical.

## Best Practices for Using Generic Models

### 1. Prefer Generics Over Inheritance When Appropriate

While model inheritance is a valid design pattern (see [Model inheritance (05)]), generic models offer a more flexible and type-safe alternative when the structure is consistent but the data type varies. Avoid overusing inheritance unless it aligns with the natural hierarchy of your data.

### 2. Keep Generics Simple and Focused

Avoid defining generic models with too many type parameters unless it's absolutely necessary. Overly complex generics can reduce readability and increase the chances of type errors. Keep the number of type variables to a minimum and ensure they serve a clear purpose.

### 3. Document Generic Models Clearly

Include detailed type hints and documentation for each type parameter. This helps other developers understand how to use the model correctly and what constraints exist on the type parameters.

### 4. Leverage Type Checking Tools

Use type checkers like `mypy` to validate the correctness of your generic models. This can catch many common errors during development and ensure that your code remains type-consistent as it evolves.

### 5. Provide Default Values for Optional Type Parameters

If certain type parameters are optional or can be inferred, provide default values or use `Optional` and `Union` types to make the model more user-friendly.

```python
from typing import Optional, TypeVar, Generic
from pydantic import BaseModel

T = TypeVar('T')

class MaybeData(Generic[T], BaseModel):
    data: Optional[T] = None
    error: Optional[str] = None

# Usage
response = MaybeData[int](data=42)
```

### 6. Avoid Over-Generics

Not every model should be generic. Use generic models only when the model's structure is reusable across different data types. For models that represent specific domain objects, consider using concrete types instead.

## Troubleshooting Common Issues

### Type Mismatch Errors

If you encounter type mismatch errors when using generic models, ensure that the concrete types passed to the generic model match the expected type signatures. Mypy and Pydantic's validation can help catch these mismatches at build or runtime.

### Incorrect Usage of `Generic` Base Class

Forgetting to include `Generic[T]` as a base class or not using `TypeVar` properly can lead to errors. Always extend `Generic[T]` and define type variables before passing them to Pydantic models.

### Incompatible Type Constraints

When using `bound` or `Protocol` constraints, ensure that the concrete types used with the generic model satisfy the required interface. Type mismatches can cause runtime errors or validation failures.

## Cross-Framework Comparisons

### Compared to Django REST Framework (DRF)

DRF offers generic views and serializers that can be reused across different models, but these are not as type-safe or flexible as Pydantic's generic models. Pydantic's approach is more Pythonic and integrates more cleanly with type hints and static analysis tools.

### Compared to TypeScript Generics

In TypeScript, generics are a first-class feature of the language and are widely used to create reusable functions and types. Pydantic's generic models offer similar benefits but are implemented at the Python runtime level, with the help of type annotations and the `typing` module.

## Conclusion

Generic models in Pydantic are an essential tool for building type-safe, reusable, and maintainable data models. By leveraging `TypeVar`, `Generic[T]`, and Python’s type system, developers can create flexible structures that adapt to different use cases while preserving strong type guarantees. Whether you're building API response wrappers, paginated data structures, or reusable validation logic, generic models provide a foundation for writing clean, expressive, and robust code.