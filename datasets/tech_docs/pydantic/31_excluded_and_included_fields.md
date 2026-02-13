# Excluded and Included Fields

In Pydantic, field inclusion and exclusion determine how data is modeled, validated, and serialized. These concepts are fundamental in scenarios like API response filtering, privacy control, and partial model usage. By leveraging `exclude` and `include` parameters, developers can shape the output and input of data models to meet specific requirements without requiring additional model definitions.

Proper use of field inclusion and exclusion allows for cleaner APIs, enhanced security, and more efficient data processing. This document explores the mechanisms, use cases, and best practices for managing fields in Pydantic models.

## Field Selection Basics

Pydantic models provide a powerful mechanism for field selection using `include` and `exclude` options in functions like `model_dump`, `model_validate`, and when serializing for APIs. These parameters accept either a `set` or `Mapping`, enabling either field inclusion or omission.

### Example: Excluding Sensitive Data

Consider a user model where sensitive information like passwords must be excluded from API responses:

```python
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str
    email: str
    password: str

user_data = {
    "id": 1,
    "name": "Alice",
    "email": "alice@example.com",
    "password": "shhh"
}

user = User.model_validate(user_data)

# Exclude sensitive field from output
public_user = user.model_dump(exclude={"password"})
print(public_user)
# Output: {'id': 1, 'name': 'Alice', 'email': 'alice@example.com'}
```

Here, `exclude={"password"}` ensures that the `password` field is never returned in API responses, improving privacy and reducing the risk of data leakage.

### Example: Including Only Necessary Fields

In some cases, it may be more efficient to only include the fields that are relevant for the current use case. This is useful in partial data loading, especially for large models or slow data sources.

```python
class Product(BaseModel):
    id: int
    name: str
    price: float
    description: str
    created_at: str
    updated_at: str

product_data = {
    "id": 101,
    "name": "Laptop",
    "price": 999.99,
    "description": "High-performance laptop",
    "created_at": "2023-01-01",
    "updated_at": "2023-04-05"
}

product = Product.model_validate(product_data)

# Include only name and price for a lightweight response
product_summary = product.model_dump(include={"name", "price"})
print(product_summary)
# Output: {'name': 'Laptop', 'price': 999.99}
```

This pattern is common in APIs that return "summary views" where only essential data is needed, reducing bandwidth and improving performance.

## Advanced Field Selection with Nested Models

Pydantic supports nested models, and field selection can be applied recursively. This is particularly useful in complex, hierarchical data models.

### Example: Nested Exclusion

Suppose we have a user model that contains a nested address model. We may want to exclude parts of the address for privacy.

```python
class Address(BaseModel):
    street: str
    city: str
    country: str
    postal_code: str

class UserWithAddress(BaseModel):
    id: int
    name: str
    address: Address

user_data_with_address = {
    "id": 2,
    "name": "Bob",
    "address": {
        "street": "123 Main St",
        "city": "Springfield",
        "country": "USA",
        "postal_code": "12345"
    }
}

user = UserWithAddress.model_validate(user_data_with_address)

# Exclude postal_code from the nested Address model
public_user = user.model_dump(exclude={"address__postal_code"})
print(public_user)
# Output: {'id': 2, 'name': 'Bob', 'address': {'street': '123 Main St', 'city': 'Springfield', 'country': 'USA'}}
```

This technique is useful when exposing data through public APIs while maintaining privacy of sensitive fields in nested structures.

## API Response Filtering and Privacy Control

One of the most common use cases for field inclusion and exclusion is in API response shaping. REST or GraphQL APIs often require different representations of the same model depending on user roles or context.

### Example: Role-Based Field Inclusion

In a multi-tenant application, administrators might see more details than regular users. This can be modeled using field inclusion:

```python
class FileModel(BaseModel):
    id: int
    name: str
    owner_id: int
    created_at: str
    updated_at: str
    access_level: str

def get_file_summary(file: FileModel, is_admin: bool) -> dict:
    if is_admin:
        return file.model_dump()
    else:
        return file.model_dump(exclude={"owner_id", "access_level"})

# Example usage
file = FileModel(id=5, name="report.pdf", owner_id=10, created_at="2024-01-01", updated_at="2024-02-01", access_level="private")
admin_view = get_file_summary(file, is_admin=True)
user_view = get_file_summary(file, is_admin=False)

print("Admin View:", admin_view)
print("User View:", user_view)
```

This approach ensures that sensitive fields like `owner_id` are not exposed to non-privileged users, enhancing security and compliance.

## Best Practices

Managing fields effectively requires a thoughtful approach to prevent common pitfalls:

### 1. Use `exclude_unset` for Default Values

When serializing, using `exclude_unset=True` can prevent unnecessary data from being sent, especially when many fields have default values.

```python
class ConfigModel(BaseModel):
    log_level: str = "INFO"
    debug_mode: bool = False
    timeout: int = 30

config = ConfigModel()

# Only output fields that have been explicitly set
serialized = config.model_dump(exclude_unset=True)
```

This reduces the size of responses and avoids sending default values unless necessary.

### 2. Avoid Hardcoding Field Names

For maintainability, avoid hardcoding field names directly in `include` or `exclude`. Instead, use constants or configuration files to manage field visibility.

### 3. Document Field Policies

When designing APIs or models, document which fields are included or excluded under different conditions. This improves clarity for developers and users.

### 4. Consider `model_config` for Global Behavior

Use `model_config` to define field inclusion/exclusion globally if the same pattern is repeated across many instances.

```python
from pydantic import BaseModel, ConfigDict

class PublicModel(BaseModel):
    model_config = ConfigDict(exclude={"private_field"})

    private_field: str
    public_field: str
```

This reduces boilerplate and enforces consistent behavior across models.

## Troubleshooting and Common Pitfalls

- **Incorrect field names**: Misspelled field names in `include` or `exclude` are silently ignored.
- **Nested field syntax**: Nested fields must be referenced with double underscores (`__`) to work correctly.
- **Unexpected behavior in validation**: `exclude` affects serialization but not validation. Always validate data before filtering.
- **Performance impact**: Overuse of `include`/`exclude` might affect performance if applied repeatedly on large models. Cache results when possible.

## Conclusion

Field selection in Pydantic is a powerful mechanism for controlling data visibility and modeling behavior in different contexts. Whether for privacy, efficiency, or API design, the ability to include or exclude fields dynamically enhances the flexibility and safety of your data models. By applying these patterns thoughtfully, you can build more robust, secure, and maintainable applications.