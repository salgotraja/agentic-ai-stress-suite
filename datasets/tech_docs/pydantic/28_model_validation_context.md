# Model Validation Context

In data-driven applications, validation is more than just checking for correct types or formats—it must often respond dynamically to the context in which a model is used. In Pydantic, the **Model Validation Context** allows for **contextual validation** by passing additional information (via the `context` parameter) into the validation process. This enables validation rules to adapt based on user roles, request origins, or other runtime conditions.

At the heart of contextual validation are two key components: the `ValidationInfo` object and the `context` parameter. This object provides access to both the raw input data and the validation context during model instantiation. By leveraging these, developers can create flexible, secure, and context-aware validation logic.

---

## Contextual Validation Fundamentals

Contextual validation is essential when the validity of a field depends on external factors beyond the input itself. For example, a `username` field might need to be unique only for new user registrations, or a `password` might require stricter rules when set by an admin versus a regular user.

Pydantic introduces the `ValidationInfo` object as a parameter to custom validators and model constructors. This object contains metadata including:

- `field_name`: the name of the field being validated
- `data`: the data of the model being validated (in root validators)
- `context`: a dictionary containing context-specific values passed at validation time

The `context` parameter is optional when creating a model instance and can be passed in using the `context` keyword argument. This is particularly useful in HTTP frameworks like FastAPI, where the context can carry information about the current user or request.

---

## Practical Example: User-Specific Validation

Consider a user registration model that needs to apply different validation rules based on whether the user is an admin or a regular user.

```python
from pydantic import BaseModel, validator, ValidationError

class UserCreateModel(BaseModel):
    username: str
    password: str
    is_admin: bool = False

    @validator('password')
    def validate_password(cls, value, info):
        if info.context.get('is_admin'):
            if len(value) < 12:
                raise ValueError('Admin passwords must be at least 12 characters long')
        else:
            if len(value) < 8:
                raise ValueError('User passwords must be at least 8 characters long')
        return value

    class Config:
        validate_all = True
```

In this example, the `password` field is validated differently depending on the `is_admin` flag in the context. When creating the model, the context can be passed like so:

```python
# Regular user
user_context = {'is_admin': False}
user_model = UserCreateModel(
    username='john_doe',
    password='securepass123',
    context=user_context
)

# Admin user
admin_context = {'is_admin': True}
admin_model = UserCreateModel(
    username='admin',
    password='SuperSecureAdminPassword123',
    context=admin_context
)
```

This pattern is especially powerful when integrated with web frameworks. For example, in FastAPI, the `context` could be populated with the current request object or user session information.

---

## Contextual Validation in Root Validators

Root validators (as covered in section 09 of this documentation) can also leverage the `ValidationInfo` object to access context. This is useful when the validity of multiple fields depends on a shared condition.

For example, consider a scenario where a `start_date` and `end_date` must fall within the same fiscal year, but the fiscal year is provided in the context:

```python
from pydantic import BaseModel, root_validator
from datetime import datetime

class EventModel(BaseModel):
    name: str
    start_date: datetime
    end_date: datetime

    @root_validator
    def check_date_fiscal_year(cls, values, info):
        fiscal_year = info.context.get('fiscal_year')
        if not fiscal_year:
            raise ValueError('Fiscal year must be provided in context')

        start_date = values.get('start_date')
        end_date = values.get('end_date')

        if start_date.year != fiscal_year or end_date.year != fiscal_year:
            raise ValueError('All dates must fall within the specified fiscal year')

        return values
```

In this case, the context is used to enforce a business rule that depends on external data not present in the model itself.

---

## Use Case: Request-Based Context

In web applications, the validation context often comes from the current HTTP request. For example, a field might be optional for internal API users but required for external ones.

```python
from fastapi import Depends, Request
from pydantic import BaseModel, validator

class ItemCreateModel(BaseModel):
    name: str
    description: str

    @validator('description')
    def validate_description(cls, value, info):
        if info.context.get('request_type') == 'public':
            if not value or len(value) < 10:
                raise ValueError('Description must be at least 10 characters for public API')
        return value

def get_request_context(request: Request):
    return {'request_type': 'public' if request.client else 'internal'}

# In a FastAPI route:
@app.post("/items")
def create_item(model: ItemCreateModel = Depends(lambda: ItemCreateModel(..., context=get_request_context(request))):
    return model
```

This pattern allows for flexible validation without requiring code duplication across different API paths or user types.

---

## Best Practices for Contextual Validation

1. **Always document context usage**: Context keys should be well-known within the team and ideally encapsulated in constants or enums to avoid typos.
2. **Validate context presence**: Ensure that required context keys are present before using them. Use `get()` with defaults or raise meaningful errors.
3. **Use context sparingly**: Only include the minimal context needed for validation. Overloading the context can make validation logic hard to understand.
4. **Avoid coupling with external state**: Context should be immutable and passed explicitly. Avoid using global variables or internal state for validation logic.
5. **Test with various contexts**: When unit testing models with contextual validation, always test with different context values to ensure correct behavior.

---

## Common Pitfalls and Troubleshooting

- **Missing context keys** can lead to silent failures or incorrect validation. Always validate the presence of context keys during model creation.
- **Overuse of context** can make validation logic hard to trace and maintain. Only use context when the validation logic cannot be encapsulated within the field's own rules.
- **Incorrect field validation order** may cause dependencies to resolve incorrectly. Use `pre=False` in `validator()` if field dependencies require later validation.

---

## Comparison with Alternative Approaches

In frameworks like Django or SQLAlchemy, contextual validation is often implemented through custom clean methods or model hooks. While these approaches are powerful, they tend to be less declarative and more tightly coupled with the ORM layer.

Pydantic's context-based validation provides a more flexible and declarative API, especially in non-persistence contexts such as API input validation. When integrated with FastAPI or Starlette, it becomes a natural extension of the request lifecycle, allowing validation to respond directly to HTTP context.

---

## Real-World Use Cases

A common real-world use case is **multi-tenancy support**, where validation rules vary per organization. For instance, a SaaS application might allow different email domains for users based on the tenant.

```python
class TenantUserModel(BaseModel):
    email: str
    tenant_id: int

    @validator('email')
    def validate_email_tenant(cls, value, info):
        tenant_id = info.context.get('tenant_id')
        allowed_domains = {
            1: ['@tenant1.com'],
            2: ['@tenant2.org', '@tenant2.net']
        }

        if tenant_id not in allowed_domains:
            raise ValueError('Unknown tenant')

        domain = value.split('@')[-1]
        if domain not in allowed_domains[tenant_id]:
            raise ValueError(f'Email domain not allowed for tenant {tenant_id}')
```

This approach ensures that validation is secure, dynamic, and aligned with business-specific rules.

---

## Integration with Custom Validators and Root Validators

Custom field validators can be combined with root validators to build multi-stage validation logic. For example, a model may require the presence of one field if a context flag is set, but not otherwise.

By combining the `ValidationInfo` object with custom logic, developers can write validation rules that are both powerful and maintainable. This is particularly useful in large systems with complex business rules and conditional validation needs.

---

## Conclusion

The `context` parameter and `ValidationInfo` in Pydantic offer a robust mechanism for **contextual validation**, enabling models to adapt to the environment in which they're used. Whether you're dealing with user roles, request scope, or business rules, context-aware validation provides a flexible and secure way to enforce correctness and enforce constraints.

Using these features effectively requires a balance between clarity and complexity: while context allows for dynamic behavior, it should be used judiciously to avoid brittle or hard-to-test validation logic. By following best practices and integrating context with well-documented, modular validation logic, you can build robust, maintainable models suitable for production systems.