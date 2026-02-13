# Request Body

In FastAPI, the **request body** is used to receive data sent by a client when making a POST, PUT, PATCH, or other HTTP methods that support payload transmission. The framework uses **Pydantic models** to define and validate the structure of the incoming request body, ensuring type safety and automatic parsing. This approach not only improves code clarity but also enhances API robustness by catching invalid inputs early.

## Core Concepts

At the heart of FastAPI's request body handling are **Pydantic models**, which describe the expected structure of the data. These models are defined using standard Python classes annotated with type hints. FastAPI then uses these models to parse and validate the request body automatically.

Pydantic models also support **nested objects**, **lists**, and **optional fields**, which allows for complex data structures to be safely and efficiently handled.

```python
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Item(BaseModel):
    name: str
    price: float
    is_offer: bool = False

@app.post("/items/{item_id}")
async def create_item(item_id: int, item: Item):
    return {"item_id": item_id, "item": item}
```

In the example above, `Item` is a Pydantic model that defines the expected structure of the request body. When a POST request is made to `/items/{item_id}`, FastAPI automatically parses the incoming JSON into an `Item` instance.

## Nested Models and Complex Data Structures

FastAPI supports **nested Pydantic models**, making it easy to handle complex, hierarchical data structures. This is particularly useful when your API needs to process data with deeply nested attributes.

```python
from typing import List, Optional
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Address(BaseModel):
    street: str
    city: str
    zip_code: int

class User(BaseModel):
    name: str
    age: int
    address: Address
    hobbies: List[str]
    is_active: Optional[bool] = True

@app.post("/user")
async def create_user(user: User):
    return {"user": user}
```

In this example, the `User` model includes an `Address` model as a sub-model, representing a nested structure. The `hobbies` field is a list of strings, and `is_active` is an optional boolean with a default value. FastAPI will correctly parse and validate all of these fields.

This pattern is ideal for APIs that need to manage rich user profiles or configuration forms with multiple sections.

## Lists and Collections of Models

When designing APIs that receive multiple items in a single request, such as uploading a batch of data, it’s common to send a list of objects. FastAPI handles this by allowing lists of Pydantic models directly in the function signature.

```python
class Product(BaseModel):
    id: int
    name: str
    price: float

@app.post("/products")
async def upload_products(products: List[Product]):
    return {"products": products}
```

Here, the endpoint expects a list of `Product` objects. The use of `List[Product]` (imported from `typing`) tells FastAPI to expect and parse an array of JSON objects that conform to the `Product` model.

### Edge Case: Mixed Data Types in a List

If your list includes different types of models or a mix of scalar and object values, you need to use **Union** from `typing` to define the acceptable types:

```python
from typing import Union, List

class Book(BaseModel):
    title: str
    author: str

class Magazine(BaseModel):
    name: str
    issue: int

@app.post("/readables")
async def upload_readables(readables: List[Union[Book, Magazine]]):
    return {"readables": readables}
```

This example allows the client to send a list containing either `Book` or `Magazine` objects. FastAPI will correctly parse and validate each item based on its structure.

## Optional Fields and Default Values

Optional fields in Pydantic models are declared using the `Optional` type from `typing`, and default values can be specified directly in the model. This is especially useful when certain fields are not always required.

```python
from typing import Optional

class Order(BaseModel):
    order_id: int
    customer_name: str
    total_amount: float
    discount: Optional[float] = None
    is_paid: bool = False
```

In this example, `discount` is optional and defaults to `None`, while `is_paid` defaults to `False`. These defaults are used if the client does not include the field in the request body.

## Validation and Error Handling

FastAPI integrates Pydantic's validation engine to enforce the correctness of incoming request data. If the request body doesn't conform to the expected schema, FastAPI returns a `422 Unprocessable Entity` error with detailed error messages.

```json
{
  "detail": [
    {
      "loc": ["body", "item", "price"],
      "msg": "value is not a valid float",
      "type": "type_error.float"
    }
  ]
}
```

This response includes the location of the invalid field (`loc`), a human-readable message (`msg`), and the type of error (`type`). These errors are invaluable for debugging and for clients to understand how to correct malformed requests.

### Best Practice: Use Pydantic Validation for Input Sanitization

While FastAPI and Pydantic provide strong validation, it is good practice to also sanitize and normalize user input in cases where the input may contain unexpected formatting. For example, dates can be normalized to a standard format using custom validation logic in the Pydantic model.

## Use Cases and Real-World Examples

### Example 1: Configuring a User Profile

A user profile API may require a nested structure, including personal details, contact information, and preferences.

```python
class ContactInfo(BaseModel):
    email: str
    phone: str
    address: Address  # Previously defined

class UserProfile(BaseModel):
    user_id: int
    name: str
    contact: ContactInfo
    preferences: dict
```

This model can be used in an endpoint like `/users/{user_id}/profile`, with the client providing a complete user profile in a single request.

### Example 2: Batch Uploading Product Inventory

A warehouse system might require uploading a list of products in bulk.

```python
@app.post("/inventory")
async def upload_inventory(items: List[Product]):
    return await database.save_products(items)
```

This endpoint handles a list of `Product` objects, allowing the client to send many products at once, improving performance and reducing API calls.

## Cross-Reference and Related Concepts

- **Pydantic validation (12):** For in-depth coverage of validation rules, custom validators, and field-level checks.
- **Response models (13):** For how to define and return structured responses using the same Pydantic models.

## Troubleshooting and Common Pitfalls

### 1. Invalid JSON

If a client sends malformed JSON, FastAPI will return a `400 Bad Request` before reaching your endpoint. Make sure to test with correct formatting.

### 2. Missing Required Fields

If a required field is omitted in the request body and no default is provided, FastAPI will return a `422` error. Always define required fields explicitly and document them in your API.

### 3. Type Mismatches

Pydantic performs strict type checking. For example, sending a string where a number is expected will cause a `type_error` and a `422` response.

### 4. Case Sensitivity in JSON Keys

By default, Pydantic matches JSON keys to model fields by name. If your API receives keys in different casing (e.g., `itemName` vs. `item_name`), you may need to use `alias_generator` in your model.

### 5. Handling Large Payloads

For very large request bodies (e.g., bulk uploads), consider streaming or using multipart/form-data for file uploads. FastAPI supports both strategies for handling large payloads efficiently.

## Best Practices

1. **Use Pydantic models for all request bodies.** This ensures strong typing and automatic validation.
2. **Document your models with JSON Schema.** FastAPI provides automatic OpenAPI documentation using your Pydantic models.
3. **Include default values for optional fields.** This improves flexibility and client experience.
4. **Use nested models to represent complex data.** This keeps your model structure clean and readable.
5. **Leverage Pydantic's `Config` class for advanced configuration.** For example, to allow extra fields or enforce specific JSON key naming.
6. **Always test your models with edge cases.** This includes missing fields, invalid types, and malformed JSON.
7. **Use consistent naming conventions.** This makes your API more predictable and easier to use.
8. **Use `Optional` and default values for optional fields.** This provides flexibility while maintaining correctness.

By following these best practices, you can build robust, maintainable APIs that are both easy to use and hard to misuse.