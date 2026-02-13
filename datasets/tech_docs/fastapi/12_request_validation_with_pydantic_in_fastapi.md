# Request Validation with Pydantic in FastAPI

Request validation is a foundational aspect of building robust APIs with FastAPI. FastAPI leverages Pydantic models for request validation, which allows for automatic data parsing, validation, and documentation generation. This document explores how to use Pydantic for validating request bodies, query parameters, and path parameters, including custom validation logic, field-level constraints, and best practices for production-grade applications.

---

## Basic Field Constraints

Pydantic provides a rich set of field-level constraints that can be used to enforce data types, formats, and ranges in request models. These constraints are declarative and concise, making them ideal for modeling API inputs.

```python
from fastapi import FastAPI
from pydantic import BaseModel, Field
from typing import Optional

app = FastAPI()

class Item(BaseModel):
    name: str
    description: Optional[str] = None
    price: float = Field(..., gt=0, description="The price must be greater than zero")
    tax: Optional[float] = Field(None, ge=0)
    quantity: int = Field(..., ge=1, le=10, description="Quantity between 1 and 10")

@app.post("/items/")
async def create_item(item: Item):
    return item
```

In this example, `Field` is used to specify validation rules such as `gt=0` (greater than zero), `ge=0` (greater than or equal to zero), and `ge=1, le=10` for ensuring a range. These rules are automatically enforced by FastAPI, and any invalid input results in a 422 Unprocessable Entity error.

---

## Custom Validators with Pydantic

For more complex validation logic that cannot be expressed through standard field constraints, Pydantic provides validator functions. These are defined using the `@validator` decorator and can perform cross-field validation.

```python
from pydantic import BaseModel, validator

class User(BaseModel):
    username: str
    password: str
    confirm_password: str

    @validator('confirm_password')
    def passwords_match(cls, v, values):
        if 'password' in values and v != values['password']:
            raise ValueError("Passwords do not match")
        return v

    @validator('username')
    def username_length(cls, v):
        if len(v) < 3:
            raise ValueError("Username must be at least 3 characters")
        return v
```

Here, `passwords_match` ensures that the `confirm_password` field matches the `password`. `username_length` checks if the username is at least three characters long. These validators are automatically invoked during model instantiation.

---

## Combining Field Constraints and Custom Validators

Field constraints and custom validators can be used together to provide fine-grained control over the validation process. This approach is especially useful when a field must satisfy multiple conditions.

```python
from pydantic import BaseModel, Field, validator
from datetime import datetime

class Order(BaseModel):
    order_id: str = Field(..., min_length=6, max_length=10)
    order_date: datetime
    total_amount: float = Field(..., gt=0, description="Total amount must be positive")
    customer_name: str = Field(..., max_length=100)

    @validator('order_id')
    def valid_order_id(cls, v):
        if not v.isalnum():
            raise ValueError("Order ID must be alphanumeric")
        return v

    @validator('order_date')
    def valid_date_range(cls, v):
        if v < datetime(2020, 1, 1) or v > datetime(2025, 12, 31):
            raise ValueError("Order date must be between 2020 and 2025")
        return v
```

This example combines `Field` constraints (like `min_length`, `max_length`, and `gt`) with custom validation logic for checking if the order ID is alphanumeric and if the order date falls within a specific time window. This ensures the model enforces both general and business-specific constraints.

---

## Cross-Field Validation

In some cases, validation logic must span multiple fields rather than being confined to a single one. Pydantic supports this through `@validator` with `pre=True` or `each_item` as needed.

```python
from pydantic import BaseModel, validator

class Product(BaseModel):
    name: str
    price: float
    discount: float = Field(..., ge=0, le=1)

    @validator('price', 'discount')
    def valid_discounted_price(cls, v, values):
        if 'price' in values and 'discount' in values and v < (values['price'] * values['discount']):
            raise ValueError("Discounted price cannot exceed the original price")
        return v
```

This validator ensures that the discounted price is never higher than the original price. It checks the relationship between `price` and `discount` fields and raises an error if the condition is violated.

---

## Nested Models and Complex Validation

FastAPI supports nested Pydantic models, enabling complex data structures to be validated in a single step. This is particularly useful for APIs that receive hierarchical data.

```python
from fastapi import FastAPI
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

class Address(BaseModel):
    street: str
    city: str
    state: str
    zip_code: str

class Customer(BaseModel):
    name: str
    age: int = Field(..., ge=18)
    email: str
    addresses: List[Address]

@app.post("/customers/")
async def create_customer(customer: Customer):
    return customer
```

In this example, the `Customer` model includes a list of `Address` models. Each `Address` is validated independently, and the `Customer` model enforces that the user is at least 18 years old.

---

## Reusable Validators and Configurations

For large applications, it's common to define reusable validators and configurations. Pydantic allows this via base models or shared validation logic.

```python
from pydantic import BaseModel, validator, Field

class BaseRequestModel(BaseModel):
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    status: str = Field(default="pending", pattern="^pending|approved|rejected$")

    @validator('status')
    def valid_status(cls, v):
        if v not in ("pending", "approved", "rejected"):
            raise ValueError("Invalid status")
        return v

class Submission(BaseRequestModel):
    title: str
    content: str
```

`BaseRequestModel` introduces shared logic for `created_at`, `updated_at`, and `status`. This reduces duplication and ensures consistency across models.

---

## Error Handling and Custom Messages

When validation fails, FastAPI returns a 422 response with an error message. You can customize these messages using the `error` parameter in `Field` and validator functions.

```python
from pydantic import BaseModel, Field, validator

class AccountRequest(BaseModel):
    username: str = Field(..., min_length=6, max_length=20, description="Username must be 6-20 characters")
    password: str = Field(..., min_length=8, description="Password must be at least 8 characters")

    @validator('password')
    def check_password_strength(cls, v):
        if not any(c.isdigit() for c in v):
            raise ValueError("Password must contain at least one digit")
        if not any(c.isupper() for c in v):
            raise ValueError("Password must contain at least one uppercase letter")
        return v
```

Custom error messages help developers and users understand what went wrong, beyond the generic "Input not valid".

---

## Best Practices

### 1. Use Field Constraints for Simple Validation
Leverage Pydantic's field constraints for basic validation tasks. These are efficient and easy to maintain.

### 2. Keep Validation Logic in Models
Encapsulate validation rules within Pydantic models to promote reusability and clarity. Avoid mixing validation logic with routing logic.

### 3. Validate Across Related Models
Use cross-field validation to ensure logical consistency between fields, especially in nested or hierarchical data structures.

### 4. Provide Clear Error Messages
Customize error messages to guide users toward fixing invalid input. Avoid generic or cryptic messages.

### 5. Use Root Validators for Global Logic
For validation that depends on multiple fields or the model as a whole, consider using `@validator('*', True)`, which acts as a root validator.

---

## Troubleshooting and Common Pitfalls

### 1. Misusing `pre=True` in Validators
Using `pre=True` tells Pydantic to run the validator before any others. This can lead to incomplete data when accessing other fields, unless handled carefully.

### 2. Forgetting to Return Values
All validator functions must return the validated value. Failing to return it results in `None` being assigned, which often causes runtime errors.

### 3. Overusing Root Validators
While powerful, root validators should be used sparingly. They can make models harder to test and maintain.

### 4. Confusing `Field` vs. `Optional`
Using `Field(None)` vs `Optional` can affect validation behavior. Always use `Optional` when a field may be omitted.

---

## Comparison with Other Validation Approaches

### 1. Manual Validation with `if` Statements
Manually checking inputs with `if` statements is error-prone and hard to maintain, especially for nested or complex data.

### 2. Django REST Framework (DRF)
DRF also uses schema-based validation but is more verbose and less performant than Pydantic in FastAPI.

### 3. `dataclasses` and `jsonschema`
While `dataclasses` can model data, they lack built-in validation. `jsonschema` provides schema validation but lacks integration with Python types and auto-documentation.

---

## Real-World Use Cases

### E-commerce API
A product creation endpoint may require:
- Name and description with max lengths
- Price validation with currency formatting
- Stock quantity to be non-negative

### User Management System
User registration requires:
- Strong password policies
- Email format validation
- Age restrictions

### Document Processing API
Document upload requires:
- File size limits
- Supported format checks
- Metadata consistency checks

---

## Conclusion

Request validation in FastAPI, powered by Pydantic, is a powerful mechanism for ensuring data integrity and API correctness. By combining field constraints, custom validators, nested models, and thoughtful error handling, developers can build robust and maintainable APIs. Adhering to best practices ensures your validation logic remains clean, extensible, and aligned with real-world requirements.