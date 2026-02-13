# Annotated Types and Metadata

Annotated types and metadata in Python, particularly when used with the Pydantic framework, offer a powerful way to enrich your data models with detailed information about their structure and behavior. This goes beyond simple type hints by allowing the inclusion of metadata through annotations, which can be used to describe field properties, validate input, generate documentation, and more. Pydantic supports Python's `Annotated` type and the `Field` function from its own module to provide this functionality in a clean and flexible way.

This documentation explores how to use Annotated types with Pydantic to create rich, self-documenting data models, how to attach metadata for field validation and documentation, and best practices for integrating this with other Pydantic features like JSON schema generation.

## Annotated Types and Field Metadata in Pydantic

Pydantic allows you to define models using standard Python classes and type hints. To add richer metadata, you can use the `Annotated` type from the `typing_extensions` module (or `typing` in Python 3.9+), in combination with Pydantic's `Field()` function.

The `Annotated` type lets you attach arbitrary metadata to a field's type. This metadata is then interpreted by Pydantic and can influence validation, documentation, and serialization behavior.

### Basic Usage of Annotated with Field

Here's a simple example showing how you can use `Annotated` and `Field` to define a field with custom metadata:

```python
from pydantic import BaseModel, Field
from typing_extensions import Annotated

class User(BaseModel):
    name: Annotated[str, Field(description="The user's full name", alias="full_name", max_length=100)]
    email: Annotated[str, Field(description="The user's email address", pattern=r".+@.+\..+")]
    age: Annotated[int, Field(description="The user's age", ge=18, le=100)]
```

In this example:

- The `name` field includes a description, an alias (`full_name`), and a maximum length.
- The `email` field uses a regex pattern for validation.
- The `age` field enforces a minimum and maximum value.

These annotations are not only used for validation but also for generating comprehensive documentation, such as OpenAPI or JSON schema.

### Advanced Metadata with Custom Annotations

Custom metadata can be added using `Field` in a more granular way. This is especially useful when you want to attach custom validation logic or additional documentation strings.

Consider the following example where we attach a custom validator and a description:

```python
from pydantic import BaseModel, Field, field_validator
from typing_extensions import Annotated

class Product(BaseModel):
    id: int
    name: Annotated[str, Field(description="Product name", min_length=3)]
    price: Annotated[float, Field(description="Product price in USD", ge=0.0)]

    @field_validator("name")
    def validate_name_length(cls, value: str) -> str:
        if len(value) < 5:
            raise ValueError("Product name must be at least 5 characters long")
        return value
```

In this example, `Annotated` is used to enforce a minimum length of 3 for the `name` field and a non-negative `price` value. Additionally, a custom validator is registered that enforces a stricter constraint: that the product name must be at least 5 characters long. This demonstrates how metadata and custom validation can work together to enforce complex constraints.

## Combining with JSON Schema (Cross-reference to 14)

One of the most powerful uses of metadata is in generating JSON schemas. Pydantic models automatically derive their schema from field metadata, making it easy to produce OpenAPI or JSON schema definitions that reflect the data model's constraints.

For instance, consider the following model:

```python
from pydantic import BaseModel
from typing_extensions import Annotated

class Address(BaseModel):
    street: Annotated[str, Field(description="Street address", max_length=100)]
    city: Annotated[str, Field(description="City name", pattern=r"^[a-zA-Z ]+$")]
    zipcode: Annotated[str, Field(description="Postal code", pattern=r"^\d{5}$")]
```

When you call `Address.model_json_schema()`, Pydantic generates a schema that reflects the metadata and validation rules attached to each field. This is particularly useful for APIs, where the schema is used both for validation and documentation.

Here's a sample of what the generated JSON schema might look like:

```json
{
  "title": "Address",
  "type": "object",
  "properties": {
    "street": {
      "type": "string",
      "description": "Street address",
      "maxLength": 100
    },
    "city": {
      "type": "string",
      "description": "City name",
      "pattern": "^[a-zA-Z ]+$"
    },
    "zipcode": {
      "type": "string",
      "description": "Postal code",
      "pattern": "^\\d{5}$"
    }
  },
  "required": ["street", "city", "zipcode"]
}
```

This schema is automatically derived from the metadata and can be used for both input validation and API documentation.

### Custom Metadata with Third-party Systems

In more advanced scenarios, custom metadata can be used to integrate with third-party validation systems or custom domain logic. For example, if you're using a database ORM or a message queue system, you might attach metadata indicating the database column name or queue topic.

Pydantic allows you to attach arbitrary key-value pairs using the `Field` constructor:

```python
from pydantic import BaseModel, Field
from typing_extensions import Annotated

class Order(BaseModel):
    order_id: Annotated[int, Field(description="Unique order identifier", db_column="order_id")]
    customer: Annotated[str, Field(description="Customer name", db_column="customer_name")]
    amount: Annotated[float, Field(description="Total order amount", db_column="order_total")]
```

In this model, the `db_column` metadata can be used by a custom adapter to map the model to a database table. Pydantic does not process this metadata directly, but it persists as part of the model definition and can be accessed via the model's metadata API.

## Best Practices for Annotated Models

When designing models with annotated types, it's important to follow best practices for maintainability, clarity, and correctness:

### 1. Use Descriptive Field Descriptions

Every field should have a description that explains its purpose clearly. This helps with documentation and makes the schema more user-friendly.

```python
Field(description="The user's date of birth in ISO format")
```

### 2. Validate Input with Constraints

Use validation constraints like `ge`, `le`, `min_length`, `max_length`, and regex patterns to enforce data integrity. These constraints are often more efficient than custom validation functions and are easier to maintain.

### 3. Avoid Overloading Annotated with Too Many Roles

While `Annotated` is flexible, it should primarily be used for validation and documentation. For more complex logic, consider using `@field_validator` or `@model_validator` functions.

### 4. Use Aliases for API Compatibility

If your API uses different field names than your internal model, use the `alias` argument to avoid exposing internal names:

```python
Field(alias="first_name")
```

This helps maintain a stable public interface even if the model evolves.

### 5. Cross-reference with Other Pydantic Features

Ensure that models are consistent with other Pydantic features, such as `Field`, `RootModel`, and `Config` settings. For instance, `extra = "ignore"` in `Config` can be used to handle unexpected fields gracefully.

### 6. Generate and Test JSON Schema

Always verify that the JSON schema generated from your model aligns with your expectations. You can use `model_json_schema()` to inspect the output and test it against a validation tool.

## Troubleshooting and Common Pitfalls

### 1. Metadata Not Being Picked Up

If metadata such as `Field` descriptions or validation constraints are not being applied, double-check that you're using `Annotated` correctly and that the model is being instantiated properly.

### 2. Conflicts Between Constraints and Custom Validators

When combining constraints with custom validators, ensure that the constraints are not redundant or conflicting. For example, if you have a `min_length` constraint and a custom validator that enforces a different constraint, you may get conflicting validation messages.

### 3. Type Conflicts in Annotated

If you encounter type errors when using `Annotated`, ensure that you're importing from the correct module (`typing_extensions` for versions before Python 3.9).

### 4. Misuse of Aliases

Aliases are useful for API compatibility, but should be used carefully. Avoid overuse or creating aliases that are too obscure.

## Conclusion

Annotated types and metadata in Pydantic offer a powerful way to build expressive, self-documenting data models. By combining `Annotated` with `Field`, developers can enforce validation rules, provide detailed documentation, and integrate with other systems using metadata. These features are especially valuable in APIs, serialization, and data validation pipelines.

When used correctly, annotated models reduce the need for boilerplate code and help maintain consistency across the codebase. Whether you're building a small internal service or a large public API, annotated types provide a clean, scalable approach to structuring and validating your data.