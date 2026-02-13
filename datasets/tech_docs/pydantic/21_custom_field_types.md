# Custom Field Types

In Python applications using the Pydantic framework, custom field types provide a powerful mechanism to enforce domain-specific constraints and improve code clarity. These types go beyond basic type annotations like `str`, `int`, or `float` and allow developers to define reusable, validated data models that encapsulate business logic. Pydantic supports three main patterns for defining custom field types: annotated types using `Annotated`, constrained types using `ConstrainedStr`, `ConstrainedInt`, etc., and custom types built with `BaseModel` or `NewType`. These approaches help create robust, maintainable code that aligns more closely with domain concepts than generic types.

## Annotated Types

Annotated types allow developers to add metadata alongside standard types. This metadata can be used by Pydantic and other tools to provide additional validation or documentation. The `Annotated` type from the `typing` module is used in conjunction with Pydantic's validation system to define custom behaviors.

For example:

```python
from typing import Annotated
from pydantic import BaseModel, Field, validator

class EmailAddress(str):
    @classmethod
    def validate(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Invalid email format")
        return v

class User(BaseModel):
    email: Annotated[EmailAddress, Field(description="User's email address")]
```

In this example, `EmailAddress` is a subclass of `str` that adds validation logic. The `Annotated` type is used to include this custom validation while also adding a description for documentation or API generation purposes. This pattern is useful for adding rich metadata and validation logic to standard types without creating complex models.

## Constrained Types

Pydantic provides a set of constrained types that allow for more specific validation of data fields. These include `ConstrainedStr`, `ConstrainedInt`, `ConstrainedFloat`, and `ConstrainedBytes`. These types are used to define fields with specific constraints such as minimum and maximum values, regex patterns, or allowed values.

```python
from pydantic import BaseModel, ConstrainedStr, ConstrainedInt

class Product(BaseModel):
    name: ConstrainedStr = ConstrainedStr(min_length=3, max_length=50)
    price: ConstrainedInt = ConstrainedInt(gt=0, lt=1000000)

product = Product(name="Table", price=100)
print(product)  # Outputs: name='Table' price=100
```

Here, the `name` field is constrained to be a string of at least 3 characters and at most 50 characters. The `price` field is constrained to be an integer greater than 0 and less than 1,000,000. This ensures that the data meets specific domain requirements and helps prevent invalid data from being processed.

## Custom Types with BaseModel

For more complex use cases, creating custom types using `BaseModel` is often the best approach. This allows developers to define nested, hierarchical data structures that encapsulate business rules and validation logic.

```python
from pydantic import BaseModel, Field, validator

class Address(BaseModel):
    street: str
    city: str
    postal_code: str

class User(BaseModel):
    name: str
    email: str
    address: Address

    @validator("email")
    def validate_email(cls, v):
        if "@" not in v:
            raise ValueError("Invalid email format")
        return v
```

In this example, `Address` is a custom type that represents a user's address, and `User` is a model that includes an `Address` field. The `validate_email` validator ensures that the email field is in the correct format. This approach allows for modular, reusable code where complex data structures can be validated as a whole.

## Reusable Constraints and Custom Validators

Custom validators can be defined using the `@validator` decorator in Pydantic. These validators can be reused across multiple models, promoting code reuse and consistency.

```python
from pydantic import BaseModel, validator, root_validator

class Product(BaseModel):
    name: str
    price: float
    discount: float = 0.0

    @validator("price")
    def price_must_be_positive(cls, v):
        if v <= 0:
            raise ValueError("Price must be greater than 0")
        return v

    @validator("discount")
    def discount_must_be_less_than_100(cls, v):
        if v < 0 or v > 100:
            raise ValueError("Discount must be between 0 and 100")
        return v

    @root_validator
    def discount_cannot_exceed_price(cls, values):
        price = values.get("price")
        discount = values.get("discount")
        if discount > price:
            raise ValueError("Discount cannot exceed price")
        return values
```

In this `Product` model, individual validators are used to ensure that `price` is positive and `discount` is between 0 and 100. A root validator is also defined to ensure that the discount does not exceed the price. This approach allows for both field-level and model-level validation, ensuring data integrity at multiple levels.

## Advanced Use Cases and Domain-Specific Types

Custom field types are particularly useful in domain-specific applications where data must conform to strict rules. For example, in financial systems, it is common to define custom types for monetary values that include validation for currency codes and decimal precision.

```python
from pydantic import BaseModel, Field, validator
import re

class MoneyAmount(float):
    @classmethod
    def __get_validators__(cls):
        yield cls.validate

    @classmethod
    def validate(cls, v):
        if not isinstance(v, (float, int)):
            raise ValueError("Money amount must be a number")
        if v < 0:
            raise ValueError("Money amount must be non-negative")
        return cls(v)

class Transaction(BaseModel):
    amount: MoneyAmount
    currency: str = Field(..., pattern=re.compile(r"^[A-Z]{3}$"))

    @validator("currency")
    def validate_currency(cls, v):
        valid_currencies = ["USD", "EUR", "GBP"]
        if v not in valid_currencies:
            raise ValueError(f"Currency must be one of {valid_currencies}")
        return v
```

In this example, the `MoneyAmount` type is a subclass of `float` that includes validation to ensure non-negative values. The `Transaction` model uses this custom type for the `amount` field and includes a regex pattern to validate the `currency` field against supported currency codes. This ensures that transactions are valid and conform to financial standards.

## Best Practices for Custom Field Types

When designing custom field types in Pydantic, it's important to follow best practices to ensure maintainability and clarity. Here are some key recommendations:

1. **Use Descriptive Names**: Choose names that clearly reflect the domain they represent. Instead of `str_with_regex`, consider `EmailAddress` or `PhoneNumber`.

2. **Encapsulate Validation Logic**: Keep validation logic within custom types or models to avoid scattering it across different parts of the codebase.

3. **Leverage Annotated Types for Metadata**: Use `Annotated` to include documentation, validation rules, or other metadata in a structured way.

4. **Avoid Over-Engineering**: Not every field needs a custom type. Reserve custom types for fields with complex or business-critical validation requirements.

5. **Write Clear Error Messages**: Custom validation should produce descriptive error messages that help users understand and fix their input.

6. **Test Extensively**: Ensure that custom types are thoroughly tested with a variety of inputs, including edge cases and invalid data.

7. **Document Usage**: Provide documentation or inline comments explaining when and why a custom type should be used.

8. **Use Reusable Components**: If multiple models share common constraints, extract them into reusable classes or validators.

9. **Consider Performance Implications**: While custom validation adds flexibility, it can also introduce overhead. Be mindful of performance in high-throughput applications.

10. **Use Root Validators for Cross-Field Constraints**: When validation depends on multiple fields, use `@root_validator` to ensure all dependencies are properly checked.

## Troubleshooting and Common Pitfalls

When working with custom field types, developers may encounter several common issues:

- **Validation Errors Not Triggered**: If validation logic is not correctly applied, errors may go unnoticed. Always test models with invalid input to ensure constraints are enforced.

- **Incorrect Type Inference**: Pydantic may not correctly infer the type of a custom type if it is not properly defined. Subclassing built-in types and implementing `__get_validators__` can help.

- **Overriding Core Types**: Be cautious when overriding or extending core types like `str`, `int`, or `float`, as this can lead to unexpected behavior in libraries that expect standard types.

- **Missing Dependency Checks**: When using root validators, ensure all required fields are included in the check to avoid runtime errors.

- **Ignoring Performance**: While Pydantic is generally performant, complex validation logic or deeply nested models can introduce bottlenecks. Profile your code to identify and optimize slow paths.

## Cross-Framework Comparisons

Pydantic's approach to custom types aligns well with similar features in other Python frameworks such as `marshmallow`, `dataclasses`, and `attrs`. However, Pydantic offers a unique combination of speed, flexibility, and validation capabilities that make it particularly suitable for data models in fast-paced applications.

Compared to `marshmallow`, Pydantic uses Python type annotations directly, reducing the need for separate schema definitions. In contrast to `dataclasses`, Pydantic provides built-in validation and coercion of input data, making it a more robust choice for data validation and transformation.

## Conclusion

Custom field types in Pydantic provide a powerful way to enforce domain-specific constraints and improve the clarity and reliability of data models. Whether using `Annotated`, constrained types, or custom `BaseModel` definitions, developers can create reusable, validated data structures that reflect the needs of their applications. By following best practices and carefully designing validation logic, it is possible to build robust, maintainable systems that prevent invalid data from causing errors or inconsistencies. As applications grow in complexity, custom types become an essential tool for ensuring data integrity and enforcing business rules.