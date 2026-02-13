# Model Copying and Updating

In applications that rely on Pydantic `BaseModel` for data modeling and validation, it's common to need to create modified versions of existing models without mutating the original. Pydantic provides two key methods for this: `model_copy()` and `model_update()`. These functions allow developers to manage state and evolve data structures in a clean, predictable way. Understanding the differences between shallow and deep copies and how to effectively apply partial updates is essential for maintaining data integrity and immutability in production systems.

## Copying Models with `model_copy()`

The `model_copy()` method is used to create a new instance of a model from an existing one. This method supports both shallow and deep copying, depending on use case and performance requirements.

### Shallow Copy

A shallow copy duplicates the top-level model instance but does not recursively copy nested objects. If the model contains nested models or collections, these will reference the same objects in memory as the original.

```python
from pydantic import BaseModel

class User(BaseModel):
    name: str
    settings: dict

user1 = User(name="Alice", settings={"theme": "dark", "language": "en"})
user2 = user1.model_copy()

# Modifying the nested dict in the copy affects the original
user2.settings["theme"] = "light"
print(user1.settings)  # Output: {'theme': 'light', 'language': 'en'}
```

Shallow copies are useful when you want to avoid copying large nested structures and are okay with shared references. However, they can introduce unintended side effects if the nested objects are mutable.

### Deep Copy

A deep copy creates a fully independent replica of the model and all its nested objects. This is ideal when you want to modify the copy without affecting the original.

```python
user3 = user1.model_copy(deep=True)
user3.settings["theme"] = "dark"
print(user1.settings)  # Output: {'theme': 'light', 'language': 'en'}
```

Deep copies are essential for working with nested models and mutable data structures. However, they can be more computationally expensive, especially with large models.

## Updating Models with `model_update()`

The `model_update()` method allows developers to update a model with new field values while preserving the rest of the data. This is particularly useful for partial updates in APIs or state management systems.

### Partial Updates

You can provide a dictionary of field-value pairs to update a subset of the model's attributes. This helps maintain immutability by returning a new instance instead of modifying the original.

```python
class UserSettings(BaseModel):
    theme: str = "light"
    language: str = "en"

class User(BaseModel):
    name: str
    settings: UserSettings

user1 = User(name="Alice", settings=UserSettings(theme="dark", language="fr"))
user2 = user1.model_update({"settings": UserSettings(theme="light")})
print(user2.settings.theme)  # Output: light
print(user1.settings.theme)  # Output: dark
```

### Nested Updates

When updating nested models, it's important to ensure that the nested structures are themselves models. This ensures that Pydantic can perform proper validation and copy operations.

```python
class Address(BaseModel):
    city: str
    country: str

class User(BaseModel):
    name: str
    address: Address

user1 = User(name="Bob", address=Address(city="New York", country="USA"))
user2 = user1.model_update({"address": Address(city="San Francisco")})
print(user2.address.city)  # Output: San Francisco
print(user1.address.city)  # Output: New York
```

## Best Practices

### Immutability and State Management

Using `model_copy()` and `model_update()` together is a powerful way to manage state while preserving immutability. This pattern is especially useful in stateful applications such as web services or data transformation pipelines.

- **Always use `deep=True`** when copying nested models to avoid unintended side effects.
- **Prefer `model_update()`** for partial changes to ensure validation and immutability.
- **Avoid mutating models in-place** by using `model_update()` instead of direct assignment or in-place operations.

### Error Handling and Validation

When updating models, especially from external sources like API requests, it's important to handle validation errors gracefully.

```python
try:
    user2 = user1.model_update({"settings": {"theme": 123}})  # Invalid type
except ValueError as e:
    print(f"Validation failed: {e}")
```

### Performance Considerations

Deep copies can be expensive for models with large or deeply nested structures. Consider the following strategies to optimize performance:

- **Profile your model copies**: Use timing tools to identify bottlenecks.
- **Use shallow copies when possible**: If nested fields are immutable (e.g., strings, tuples), shallow copies are safe and faster.
- **Cache copies**: If the same data is copied repeatedly, consider caching the result.

### Cross-Framework Comparison

In comparison to other data modeling libraries such as Marshmallow or Django Models, Pydantic's approach to copying and updating is more aligned with functional programming principles. Unlike Django models, which are tied to a database and often mutate in-place, Pydantic models are designed to be immutable and copied when updated. This makes them ideal for use in APIs, data transformation, and microservices architectures.

## Real-World Use Cases

### Data Transformation Pipeline

In a data transformation pipeline, you might read a raw dataset, clean it, and output a transformed version. Using `model_update()` ensures that each step works on a new instance, preserving the original data and making debugging easier.

```python
def clean_user_data(data: dict) -> User:
    user = User.model_validate(data)
    user = user.model_update({"email": data.get("email").strip()})  # Clean email
    user = user.model_update({"is_active": data.get("is_active", False)})
    return user
```

### API Versioning

When handling multiple API versions, you may need to upgrade data from an older format to a new one. Using `model_update()` allows you to add new fields or transform existing ones without modifying the original input.

```python
def upgrade_v1_to_v2(data: dict) -> UserV2:
    user_v1 = UserV1.model_validate(data)
    user_v2 = UserV2.model_update(user_v1, {"new_field": "default_value"})
    return user_v2
```

## Troubleshooting and Common Pitfalls

### Nested Models Not Updating

If a nested model isn't updating as expected, ensure that the nested model is also a `BaseModel`. Pydantic does not automatically cast dictionaries into models when using `model_update()`.

```python
# ❌ This will fail with a type error
user = User(name="Alice", settings={"theme": "dark"})
user = user.model_update({"settings": {"language": "fr"}})

# ✅ This is correct
user = User(name="Alice", settings=UserSettings(theme="dark", language="en"))
user = user.model_update({"settings": UserSettings(language="fr")})
```

### Confusing Shallow and Deep Copies

If modifying a copy also changes the original, you may have made a shallow copy instead of a deep one. Always use `deep=True` if modifying nested data structures.

### Performance Bottlenecks

Deep copies can be slow for large models. If you're experiencing performance issues, consider profiling the copy operation and identifying which parts are most expensive.

## Conclusion

Model copying and updating are essential operations in any data modeling system. Pydantic’s `model_copy()` and `model_update()` provide flexible, type-safe tools to manage these operations. Understanding the difference between shallow and deep copies and knowing when to use each is crucial for building robust, maintainable code. By leveraging these patterns, developers can ensure immutability, reduce side effects, and build scalable data handling systems.