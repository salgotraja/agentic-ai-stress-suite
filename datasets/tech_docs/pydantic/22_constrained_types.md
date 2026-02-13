# Constrained Types

Constrained types in Pydantic allow developers to impose additional validation logic beyond basic type checking. These types are particularly useful when you need to enforce value ranges, patterns, or other constraints that cannot be captured by standard type annotations alone. Pydantic provides several built-in constrained types such as `conint`, `constr`, and `confloat`, which offer a declarative and expressive way to define these constraints. This approach helps ensure data integrity and reduces the need for custom validation logic in models.

## Built-in Constrained Types

Pydantic offers a set of constrained types that are instances of `conint`, `constr`, `confloat`, and `conset`, among others. These are defined in `pydantic.constr`, `pydantic.conint`, and so on. They are particularly useful when you want to apply constraints like minimum and maximum values, length limits, regex patterns, or element sets without writing custom validators.

### `conint` and `confloat`

The `conint` and `confloat` types allow you to define constraints on numeric types. For example, you might want to ensure a value is between 1 and 100, or that a float is at least 0.5 but less than or equal to 1.0. Here’s how you can define these types:

```python
from pydantic import conint, confloat, BaseModel

class UserSettings(BaseModel):
    volume_level: conint(ge=1, le=100)  # Volume must be between 1 and 100
    confidence_score: confloat(ge=0.0, le=1.0)  # Score must be between 0.0 and 1.0
```

In this example, `conint(ge=1, le=100)` ensures that the `volume_level` field is an integer between 1 and 100, inclusive. Similarly, `confloat(ge=0.0, le=1.0)` ensures the `confidence_score` is a float within the [0.0, 1.0] range.

### `constr`

The `constr` type is used to enforce string constraints such as minimum and maximum length, regex patterns, and allowed characters. For example, you might want to validate an email format or enforce a specific password policy.

```python
from pydantic import constr

class UserInput(BaseModel):
    username: constr(min_length=3, max_length=20, regex=r'^[a-zA-Z0-9_]+$')  # Username must be alphanumeric and underscores only
    email: constr(min_length=5, max_length=254, regex=r'^[\w\.]+@[\w\.]+\.\w+$')  # Simple email regex
```

In this case, the username must be between 3 and 20 characters long and only include alphanumeric characters and underscores. The email must match a basic email pattern. These constraints help catch invalid user input early.

## Validated Ranges and Pattern Matching

Pydantic’s constrained types are especially useful when you want to enforce validated ranges or pattern matching that goes beyond standard type checks. These types are not only expressive but also optimize performance by reducing the need for custom validation functions.

Here’s a more complex example involving ranges and a regex-based pattern:

```python
from pydantic import conint, constr, confloat, BaseModel

class Product(BaseModel):
    product_id: conint(ge=1000, le=9999)  # Product ID must be a 4-digit number
    description: constr(min_length=10, max_length=500)  # Description must be at least 10 characters
    price: confloat(ge=0.0, lt=10000.0)  # Price must be non-negative and less than 10,000
    tags: list[constr(min_length=1, max_length=20)]  # Each tag must be 1-20 characters long
```

This `Product` model ensures that the `product_id` is a valid four-digit integer, the `description` is sufficiently descriptive, the `price` is realistic, and all `tags` conform to length constraints. These constraints help maintain data consistency across your application.

### Edge Cases and Error Handling

When using constrained types, it's important to consider how errors are raised and handled. Pydantic performs these validations at model initialization time, and if any constraint is violated, a `ValidationError` is raised with detailed information about the failure.

```python
try:
    product = Product(
        product_id=999,  # Too small
        description="Too short",  # Too short
        price=-5.0,  # Negative price
        tags=["toolongtagname12345678901234567890"]  # Tag length exceeds 20 characters
    )
except Exception as e:
    print(e)
```

This will raise a `ValidationError` with multiple error messages, each pointing to the specific constraint violation. Understanding how these errors are structured helps you write more robust validation logic and user feedback systems.

## Practical Use Cases and Best Practices

### Real-World Use Cases

Constrained types are ideal for enforcing business rules in APIs, configuration management, or data ingestion pipelines. For example, in a financial application, you might need to enforce that certain transaction amounts fall within acceptable ranges. In a user management system, you might need to validate that usernames follow a specific format.

A real-world example from an e-commerce application might look like this:

```python
from pydantic import conint, BaseModel

class InventoryItem(BaseModel):
    item_id: conint(ge=10000, le=99999)  # 5-digit product ID
    quantity: conint(ge=0, le=10000)  # Quantity must be non-negative and realistic
    warehouse: str = "Main"  # Default warehouse
    reorder_threshold: conint(ge=10, le=1000)  # Threshold for reorder
```

This model ensures that the `item_id` is a 5-digit integer, the `quantity` is within a realistic range, and the `reorder_threshold` is a reasonable number to prevent overstocking or understocking.

### Best Practices

1. **Use Constrained Types for Common Patterns**: Instead of writing custom validators for every field, use `conint`, `constr`, and `confloat` to reduce boilerplate and maintain consistency.
2. **Combine with Default Values**: When appropriate, provide default values to avoid required fields while still enforcing constraints.
3. **Avoid Over-Constraining**: While constraints are useful, overuse can lead to rigid models. Evaluate whether a constraint truly adds value or if a simple type check is sufficient.
4. **Leverage Regex for Complex Patterns**: For strings, use regex patterns to enforce complex rules such as password policies, email validation, or custom naming conventions.
5. **Document Constraints Clearly**: Especially in collaborative environments, document the constraints in your model to help other developers understand and maintain them.

## Troubleshooting and Common Pitfalls

### Common Errors

- **Incorrect Use of Constraints**: Forgetting to apply constraints to the correct type (e.g., using `conint` on a float field).
- **Regex Pattern Errors**: Forgetting to escape characters or using incorrect regex syntax.
- **Unexpected Coercion**: Pydantic may attempt to coerce values to the correct type, leading to silent constraint violations. Be explicit about required types.
- **Missing Constraints on Optional Fields**: Optional fields can still benefit from constraints; ensure that even optional fields have constraints applied when necessary.

### Debugging Tips

- **Inspect the `ValidationError`**: The error object provides detailed information about which fields failed and why.
- **Use the `json_schema_extra` attribute** (Pydantic 2.x) to document constraints in your API specs.
- **Write Unit Tests for Constraints**: Automate tests for each model to catch constraint violations during development.

## Cross-References and Further Reading

- **Field types**: Refer to the documentation on field types for a deeper understanding of how Pydantic handles field annotations and validations.
- **Custom field types**: For advanced use cases where built-in constrained types are not sufficient, consider reading about custom field types to create reusable validation logic.

By leveraging Pydantic’s constrained types, you can create more robust and self-validating data models that enforce business rules and domain constraints directly in your code. This leads to fewer runtime errors, cleaner code, and a more predictable data flow in production systems.