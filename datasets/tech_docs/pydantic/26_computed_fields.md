# Computed Fields

Computed fields are a powerful pattern in data modeling that allow you to derive or compute values from other fields within a data structure. In the context of Pydantic models, computed fields are virtual attributes that are not stored as regular fields but are instead calculated dynamically upon access. These fields are particularly useful for enriching data models with derived logic, performing calculations, or formatting data for serialization without mutating the original data structure.

Computed fields are typically implemented using decorators like `@property` or, in more recent Pydantic versions (v2+), using `@computed_field`. These fields are not persisted when serializing the model unless explicitly specified, and they do not participate in validation in the same way as regular fields.

---

## Calculated Properties with `@property`

The most common way to implement computed fields in Pydantic is using Python’s built-in `@property` decorator. This allows you to define a method that appears as a regular attribute.

```python
from pydantic import BaseModel
from datetime import datetime

class User(BaseModel):
    full_name: str
    birthdate: datetime

    @property
    def age(self) -> int:
        today = datetime.now().date()
        return today.year - self.birthdate.year - (
            (today.month, today.day) < (self.birthdate.month, self.birthdate.day)
        )
```

In this example, the `age` is a computed field derived from the birthdate. It is not a regular model field but is available for access and can be used in downstream logic.

This pattern is particularly useful for:

- Avoiding redundant data storage
- Keeping models clean and focused on their core attributes
- Performing lightweight calculations that are not worth storing separately

---

## API Enrichment with `@computed_field` (Pydantic v2+)

Starting with Pydantic v2, the `@computed_field` decorator provides a more structured way to define computed fields that integrate better with Pydantic’s model system. It also supports defining the return type and allows the field to be serialized.

```python
from pydantic import BaseModel, computed_field
from datetime import datetime

class Product(BaseModel):
    name: str
    price: float
    discount: float = 0.0

    @computed_field
    @property
    def discounted_price(self) -> float:
        return self.price * (1 - self.discount)
```

This `discounted_price` field is not stored explicitly in the model, but it is computed on the fly. When the model is serialized, this field will be included unless explicitly excluded.

One of the major benefits of `@computed_field` over `@property` is that it integrates with the model’s `model_dump()` and `model_serialize()` methods. This means you can include computed fields in JSON outputs or API responses seamlessly.

---

## Field Serialization and Computed Fields

Computed fields behave differently from standard fields when it comes to serialization. By default, computed fields are not included in the model’s serialized output unless they are explicitly declared as serializable.

In Pydantic v2, the `@computed_field` decorator allows you to define the field as serializable by including a `repr` or `json` configuration.

```python
from pydantic import BaseModel, computed_field, ConfigDict

class Item(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    name: str
    quantity: int
    unit_price: float

    @computed_field
    @property
    def total_price(self) -> float:
        return self.quantity * self.unit_price
```

In this case, `total_price` will be included in the output of `model_dump()` or `model_json()` because it is a computed field decorated with `@computed_field`. The field is not a model attribute but is available for serialization.

---

## Use Cases and Practical Examples

Computed fields are best suited for scenarios where the data is derived from existing fields and does not need to be persisted to storage or passed back to the client in unprocessed form.

### Example: API Response Enrichment

In web applications, computed fields can enrich data before sending it to the client. For example, in a user management system:

```python
from pydantic import BaseModel, computed_field
from datetime import datetime

class UserResponse(BaseModel):
    id: int
    name: str
    created_at: datetime

    @computed_field
    @property
    def user_since(self) -> str:
        return self.created_at.strftime("%B %Y")
```

This `user_since` field is computed and formatted as a string, ready to be displayed in the UI. The original `created_at` field remains in ISO 8601 format for machine consumption.

### Example: Business Logic Integration

In financial applications, computed fields can encapsulate business rules that are too complex to store in raw form.

```python
from pydantic import BaseModel, computed_field

class Transaction(BaseModel):
    amount: float
    tax_rate: float
    discount: float = 0.0

    @computed_field
    @property
    def net_amount(self) -> float:
        tax_amount = self.amount * self.tax_rate
        return (self.amount + tax_amount) * (1 - self.discount)
```

This `net_amount` field combines tax and discount logic, providing a clean and reusable property that represents the final amount to be paid.

---

## Best Practices

Here are some best practices for working with computed fields in Pydantic:

### 1. Avoid Side Effects in Computed Fields

Computed fields should be pure functions of the model’s attributes. Avoid including side effects such as modifying external state, making API calls, or writing to files. These should be handled elsewhere in the application.

### 2. Use Descriptive Names

Computed fields should have clear and descriptive names that indicate their purpose. Avoid abbreviations if clarity is impacted.

### 3. Consider Caching for Performance

If a computed field is expensive to compute and does not change often, consider caching the result using `functools.lru_cache` or a custom memoization pattern.

### 4. Use in Read-Only Contexts

Computed fields are best used in read-only contexts. Avoid using them to mutate or update other fields in the model.

### 5. Document Computed Fields

Provide inline documentation or docstrings for computed fields to explain their purpose and logic. This is especially important for team collaboration and maintenance.

---

## Cross-Reference with Field Types and Serialization

Computed fields are closely related to the concepts of [Field Types](03) and [Serialization](11) in Pydantic.

- From a field type perspective, computed fields can return any valid Python type and are not constrained by the same validation rules as regular fields.
- From a serialization perspective, computed fields offer flexibility in how data is rendered in output formats like JSON, XML, or APIs.

---

## Comparison with Alternative Approaches

### 1. Regular Fields

Regular fields are stored in the model and participate in validation. They are ideal for data that is directly provided or persisted. Computed fields, on the other hand, are derived and not stored.

### 2. Dataclasses with `@property`

Python’s `dataclass` module can also use properties for computed values. However, Pydantic provides more robust validation, type checking, and integration with serialization tools.

### 3. ORM-Level Computed Columns

In frameworks like SQLAlchemy, ORM models may define computed columns. However, these are typically database-specific and not as flexible in application-level logic.

---

## Troubleshooting Common Issues

### 1. Computed Field Not Serializable

If a computed field is not included in the output, ensure that it is decorated with `@computed_field`. Also, verify that the model config allows it to be serialized.

### 2. Circular Dependencies

Be cautious with computed fields that depend on one another. Circular dependencies can cause runtime errors or infinite loops.

### 3. Type Annotations for Computed Fields

Always include type annotations for computed fields. This helps with IDE support, static analysis, and clarity for other developers.

---

## Real-World Use Cases

### 1. E-commerce Pricing Logic

Computed fields are widely used in e-commerce systems to calculate final prices after taxes, discounts, and shipping.

### 2. Financial Reporting

Financial models often use computed fields to derive KPIs such as profit margin, ROI, and EBITDA from raw input data.

### 3. User Analytics

In user analytics, computed fields can combine multiple attributes into a user score or risk assessment.

---

## Conclusion

Computed fields provide a clean and powerful way to extend Pydantic models with derived logic, enrich data for API responses, and perform on-the-fly calculations. When used correctly, they can improve code readability, maintainability, and performance. Always ensure computed fields are used for read-only, derived data and avoid side effects. With `@computed_field`, Pydantic v2 offers a robust and integrated way to work with virtual attributes in production-grade applications.