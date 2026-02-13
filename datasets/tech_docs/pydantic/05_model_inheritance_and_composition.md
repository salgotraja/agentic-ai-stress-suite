# Model Inheritance and Composition

Model inheritance and composition are foundational techniques for building scalable, maintainable, and reusable data models in complex applications. Pydantic, as a powerful data modeling framework, supports these patterns through its `BaseModel` class and flexible configuration options. This document explores how to implement inheritance and composition with Pydantic, focusing on strategies to reduce redundancy (DRY design), model polymorphism, and the use of abstract base classes.

---

## Inheriting from BaseModel

The most basic form of model inheritance in Pydantic is extending `BaseModel`. This allows you to define a base class with common fields and validation logic, which child models can build upon.

```python
from pydantic import BaseModel

class User(BaseModel):
    id: int
    name: str
    email: str

class Admin(User):
    access_level: int = 5
```

Here, `Admin` inherits all the fields and validation rules from `User` while adding its own `access_level` field. This pattern helps reduce duplication and promotes consistency across related models.

However, inheritance in Pydantic is not limited to fields. You can also inherit and override validation logic, default values, and configuration via the `Config` class.

```python
class Product(BaseModel):
    class Config:
        extra_forbid = True

    name: str
    price: float

class Book(Product):
    pages: int
```

In this example, `Book` inherits the configuration from `Product`, ensuring that only declared fields are allowed to be set. This is particularly useful in production systems where data integrity is critical.

---

## Mixin Patterns for Reusable Behavior

Pydantic supports mixin patterns by allowing models to inherit multiple base classes. This is useful when you want to reuse validation logic or additional behavior across unrelated models.

For example, consider a `TimestampMixin` that adds common timestamp fields:

```python
from datetime import datetime
from pydantic import BaseModel

class TimestampMixin(BaseModel):
    created_at: datetime
    updated_at: datetime

class Article(TimestampMixin, BaseModel):
    title: str
    content: str

class Comment(TimestampMixin, BaseModel):
    text: str
```

Both `Article` and `Comment` inherit the `created_at` and `updated_at` fields from `TimestampMixin`, enforcing consistent temporal metadata across different domain models.

This pattern also enables the reuse of validation logic. For example:

```python
class ValidatedDataMixin(BaseModel):
    def validate_data(self):
        if not self._data_verified:
            raise ValueError("Data not verified")
```

This method can be included in any model that requires a pre-validation hook before further processing.

---

## Abstract Base Classes for Interface Definition

An abstract base class in Pydantic is defined simply by not instantiating it as a model. It serves as a template for other models to follow.

```python
from abc import ABC
from pydantic import BaseModel

class ContentModel(ABC, BaseModel):
    title: str
    author: str

class BlogPost(ContentModel):
    content: str

class Video(ContentModel):
    duration: int
```

In this case, `ContentModel` is not meant to be instantiated directly. It defines a base interface that `BlogPost` and `Video` implement. While not enforced at the framework level (as in Python's `abc` module), this pattern encourages consistency and can be integrated with validation or serialization logic.

---

## Polymorphic Models with Union and Discriminator

Pydantic provides robust support for polymorphic models using `Union` and the `discriminator` field. This is especially powerful in systems where models share a common base but vary in structure.

```python
from pydantic import BaseModel, Field, create_model
from typing import Union

class BaseEvent(BaseModel):
    type: str
    timestamp: int

class LoginEvent(BaseEvent):
    type: str = Field(default='login', const=True)
    username: str

class LogoutEvent(BaseEvent):
    type: str = Field(default='logout', const=True)
    session_id: str

Event = Union[LoginEvent, LogoutEvent]
```

With `Union`, Pydantic can now validate a model based on the `type` field. This is ideal for event-based architectures or message queues.

You can further enhance this by using the `discriminator` configuration to automate type resolution:

```python
class BaseEvent(BaseModel):
    type: str
    timestamp: int
    model_config = ConfigDict(discriminator="type")

class LoginEvent(BaseEvent):
    type: str = Field(default='login', const=True)
    username: str

class LogoutEvent(BaseEvent):
    type: str = Field(default='logout', const=True)
    session_id: str
```

Now, when parsing JSON input, Pydantic will automatically map the correct event class based on the `type` field.

---

## Model Composition for Modular Design

Model composition is a powerful alternative to inheritance. Rather than defining deep inheritance hierarchies, you can build models by composing smaller, focused models together.

This is especially useful for separating concerns or encapsulating complex validation logic.

```python
class Address(BaseModel):
    street: str
    city: str
    zip_code: str

class User(BaseModel):
    name: str
    email: str
    address: Address
```

In this case, `User` includes `Address` as a nested field. This promotes modularity and allows `Address` to be reused independently in other models like `Company`.

You can also use composition to encapsulate validation:

```python
class CreditCard(BaseModel):
    number: str
    expiry: str

    @property
    def is_valid(self) -> bool:
        # Simplified validation
        return len(self.number) == 16

class PaymentModel(BaseModel):
    user: User
    credit_card: CreditCard
```

This approach keeps model responsibilities distinct and makes it easier to test and maintain each component.

---

## DRY Model Design with Configurations and Factories

DRY (Don’t Repeat Yourself) is not just about code duplication but also about configuration and validation logic. Pydantic supports this through the `Config` class and model factories.

```python
class ConfigurableModel(BaseModel):
    class Config:
        extra_forbid = True
        validate_assignment = True

class Transaction(ConfigurableModel):
    amount: float
    user_id: int
```

By centralizing configuration in a base class, you ensure that all derived models inherit consistent validation and runtime behaviors.

For more dynamic control, use a model factory function:

```python
def create_model(name: str, **kwargs) -> type[BaseModel]:
    return create_model(name, **kwargs)

User = create_model('User', id=int, name=str)
```

This is useful in systems where models must be generated dynamically, such as API clients or code generation tools.

---

## Best Practices

- **Use inheritance for shared fields and logic**. Avoid deep hierarchies that are hard to maintain.
- **Prefer composition over inheritance** for modular and testable code.
- **Leverage mixins for cross-cutting concerns** like timestamps or common validations.
- **Use `Union` and discriminators for polymorphic models** to handle multiple types in a single interface.
- **Centralize configurations** in base classes for consistent behavior across child models.
- **Avoid overuse of abstract base classes**. Pydantic does not enforce abstract methods, so use them judiciously for documentation or shared behavior.

---

## Troubleshooting and Common Pitfalls

### 1. Inheritance and Field Conflicts

Be cautious when overriding fields in child models. Pydantic will raise an error if you try to re-declare a field with different types or constraints.

### 2. Configuration Conflicts

If multiple base classes define `Config`, the last one in the inheritance chain takes precedence. Be explicit about which configuration you want to apply.

### 3. Discriminator Field Must Be Unique

When using the `discriminator` field, ensure the field is present in all polymorphic submodels and has consistent values.

### 4. Composition Can Be More Expressive

In scenarios where inheritance leads to complex hierarchies, consider using composition instead. It can often lead to simpler and more maintainable code.

---

## Conclusion

Model inheritance and composition in Pydantic provide powerful tools for building robust, scalable data models. By leveraging inheritance for shared fields, composition for modular design, and unions for polymorphic behavior, you can create systems that are both expressive and maintainable.

Understanding when to use each pattern is key. Inheritance is ideal for shared structure and logic. Composition helps keep models decoupled and testable. Mixins and abstract base classes can provide a middle ground for reusable behavior.

In production settings, these concepts are essential for handling complex domain models, ensuring data integrity, and maintaining a clean and DRY codebase.