# Private Attributes

In the Pydantic framework, private attributes allow you to encapsulate internal state and computed values, shielding them from direct manipulation while still providing access through public methods or properties. This is particularly useful for managing complex state logic, caching derived values, or maintaining internal consistency without exposing these details to the user of a model.

Private attributes are declared using the `ModelPrivateAttr` or `PrivateAttr` classes from Pydantic v2, and they play a crucial role in separating the public interface of a class from its internal implementation.

## Internal State Encapsulation

Private attributes are essential when you want to maintain the integrity of an object's internal state without exposing it. This is especially important in models that involve derived or computed fields, where external modification could lead to invalid data.

For example, consider a model that tracks the number of updates made to an object. You might not want the count to be mutable from the outside.

```python
from pydantic import BaseModel, PrivateAttr

class Document(BaseModel):
    name: str
    content: str
    _update_count: int = PrivateAttr(default=0)

    def update_content(self, new_content: str):
        self.content = new_content
        self._update_count += 1

    @property
    def number_of_updates(self) -> int:
        return self._update_count
```

In this model, the `_update_count` field is private, and any updates are performed through the `update_content` method. This ensures that the counter is incremented safely and consistently.

This pattern is common in systems where auditability and traceability are required, such as in versioned data models or configuration management systems.

## Computed State and Caching

In many applications, especially those involving performance-sensitive operations, computed attributes can be expensive to calculate. Pydantic's private attributes work well with cached properties, which compute a value once and store it internally for subsequent access.

```python
from pydantic import BaseModel, PrivateAttr
from functools import cached_property

class Product(BaseModel):
    base_price: float
    tax_rate: float
    _total_price: float = PrivateAttr(default=float('nan'))

    @cached_property
    def total_price(self) -> float:
        self._total_price = self.base_price * (1 + self.tax_rate)
        return self._total_price

    def update_price(self, new_price: float):
        self.base_price = new_price
        self._total_price = float('nan')  # Invalidate the cached value
```

In this example, `total_price` is a computed property that depends on `base_price` and `tax_rate`. The result is cached in `_total_price`, but it's invalidated whenever the base price changes. This ensures that the computed value reflects the latest data, while also minimizing redundant calculations.

This approach is ideal for models that handle financial data, pricing engines, or any system where derived data must be recalculated when underlying data changes.

## Best Practices for Private Attributes

When designing models that use private attributes, consider the following best practices:

1. **Encapsulate Logic**: Ensure all modifications to private attributes are done through public methods. This maintains control over the internal state and prevents invalid data states.
   
2. **Use Properties for Read Access**: Provide read-only access to private attributes via properties. This allows for computed values and validation to be applied on access.

3. **Avoid Overuse**: While private attributes are useful for internal state, overusing them can lead to models that are difficult to test and debug. Keep the public interface as minimal as possible.

4. **Document Clearly**: Clearly document the purpose of private attributes and their usage. This is especially important when working in teams or maintaining large code bases.

5. **Consider Performance Implications**: When using caching, be aware of memory usage and the cost of recomputation. Ensure that the cache is invalidated properly when dependencies change.

6. **Leverage Configurations**: Use the `Config` class to define model metadata and behavior, including `extra` and `allow_mutation` settings that can affect private attributes.

By following these best practices, you can build robust, maintainable models that efficiently manage internal state while providing a clean and predictable public interface.

## Troubleshooting and Common Pitfalls

When working with private attributes in Pydantic, certain pitfalls are common. One such issue is attempting to access a private attribute directly without a public getter, which will result in an `AttributeError`. This can be confusing if you're expecting to access the value as a regular field.

Another common mistake is forgetting to invalidate cached properties when underlying data changes. Forgetting to reset the `_total_price` field in the `update_price` method, for example, would result in stale data.

Additionally, when using `ModelPrivateAttr` in Pydantic v2, be aware that it's not part of the model's public schema, which means it won't be included in serialized output unless explicitly handled.

Here’s an example that demonstrates the correct use of `ModelPrivateAttr` with a custom getter and setter:

```python
from pydantic import BaseModel, ModelPrivateAttr

class User(BaseModel):
    username: str
    _password_hash: str = ModelPrivateAttr()

    def set_password(self, password: str):
        self._password_hash = hash(password)

    def verify_password(self, password: str) -> bool:
        return hash(password) == self._password_hash
```

In this case, the password is stored as a private attribute, and access is managed through methods. This pattern is common in authentication systems where sensitive data must be protected.

## Cross-Reference with Other Concepts

Private attributes are often used in conjunction with `BaseModel` fundamentals described in [02: BaseModel basics](#02-basemodel-basics) and the `Config` class as detailed in [13: Config class](#13-config-class). Together, these features allow for flexible model configuration and secure data handling.

In traditional object-oriented programming, private attributes are managed using double-underscore (`__`) name mangling to enforce access control. Pydantic’s approach is more explicit and integrates well with type hints and automatic validation, making it a better fit for data modeling and API design.

In conclusion, private attributes in Pydantic are a powerful tool for managing internal state and computed values in a secure and controlled manner. By encapsulating sensitive or derived data, you can design models that are both robust and maintainable, while ensuring that the public interface remains clean and predictable.