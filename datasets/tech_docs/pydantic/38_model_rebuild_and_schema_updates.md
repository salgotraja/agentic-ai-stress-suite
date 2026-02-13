# Model Rebuild and Schema Updates

In modern Python applications using frameworks like Pydantic, models are often used to represent and validate data structures. As systems evolve, models need to be updated to reflect new requirements, data formats, or schema changes. Model rebuild and schema updates offer mechanisms to dynamically adapt these models without restarting the application, ensuring that systems remain responsive and maintainable in production environments.

This documentation covers essential tools and patterns for managing model rebuilds and schema updates in Pydantic, with a focus on `model_rebuild()`, schema refreshing, and dynamic updates. These features enable plugins to reload models, apply hot updates, and maintain consistency across evolving interfaces.

## Understanding Model Rebuild with `model_rebuild()`

Pydantic's `model_rebuild()` is a powerful utility that regenerates a model's internal schema and validation logic based on its current class definition. This function is particularly useful in scenarios where model definitions change at runtime—such as when plugins or modules are reloaded dynamically.

```python
from pydantic import BaseModel, model_rebuild

class User(BaseModel):
    name: str
    email: str

# Initially, the model has these fields
print(User.model_json_schema())

# Later, we add a new field dynamically
User.model_fields["age"] = 30  # Not recommended; use model_rebuild instead
model_rebuild(User)

# Now, the schema reflects the new field
print(User.model_json_schema())
```

> **Note**: Directly manipulating `model_fields` is not advised. Instead, use subclassing or module reloading to add fields, and then call `model_rebuild()` to update the schema.

### When to Use `model_rebuild()`

You should invoke `model_rebuild()` when:

- You dynamically modify a model class (e.g., by adding or removing fields).
- You want to apply changes made in a plugin or module without restarting the application.
- You implement a hot-reloading feature that updates models in response to file changes.

Using `model_rebuild()` is essential when the model's validation logic must change in real-time, such as when configuration settings are modified via a management interface.

## Schema Refreshing and Dynamic Updates

Schema refreshing is the broader concept of ensuring that a model's schema always reflects its current class definition. While `model_rebuild()` is one tool for this, schema updates can also be triggered by other means, such as re-importing modules or using dependency injection frameworks.

### Plugin Reloading and Hot Updates

In plugin-based architectures, models are often defined in separate modules that can be loaded and unloaded dynamically. This setup requires hot update capabilities to ensure that any new or modified models are correctly validated.

Here’s a simple example of how a plugin system might implement hot updates:

```python
import importlib
from pydantic import BaseModel, model_rebuild

def reload_plugin(module_name):
    module = importlib.import_module(module_name)
    importlib.reload(module)

    # Rebuild all models in the module
    for name, obj in module.__dict__.items():
        if isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel:
            model_rebuild(obj)

# Example usage
reload_plugin("user_plugin")
```

This script reloads a module, re-imports all models, and rebuilds them using `model_rebuild()`. It ensures that any changes to model definitions are immediately reflected in the system.

### Forward References and Dynamic Models

Pydantic supports forward references using `__future__` imports or string annotations. However, when models are dynamically rebuilt, these forward references must be resolved correctly.

```python
from pydantic import BaseModel, Field, model_rebuild

class OrderItem(BaseModel):
    product_id: str
    quantity: int
    order: 'Order' = Field(..., description="The order this item belongs to")

class Order(BaseModel):
    order_id: str
    items: list[OrderItem]

# Resolve forward references
Order.model_rebuild()
OrderItem.model_rebuild()
```

> **Cross-reference**: See [Dynamic models (16)](dynamic_models) and [Forward refs (07)](forward_references) for more on how to manage these dependencies during hot reloads.

## Best Practices

### Use Versioning for Model Definitions

To avoid conflicts during schema updates, version your models. This allows for backward compatibility and controlled rollouts of new structures.

```python
class UserV1(BaseModel):
    name: str
    email: str

class UserV2(BaseModel):
    name: str
    email: str
    preferences: dict
```

By versioning models, you can apply `model_rebuild()` selectively and manage migration logic.

### Monitor Model Changes

In production systems, it's essential to track when and how models are rebuilt. Logging and monitoring the outcome of `model_rebuild()` can help detect schema inconsistencies or validation misconfigurations.

### Avoid Direct Field Mutation

While Pydantic allows for programmatic manipulation of model fields, it is safer and more maintainable to use subclassing or configuration files to define new models. Direct modifications increase the risk of unintended side effects.

```python
class EnhancedUser(User):
    access_level: int = 1

model_rebuild(EnhancedUser)
```

### Use Dependency Injection for Dynamic Model Usage

When models are used across different components, dependency injection frameworks like FastAPI or Starlette help manage dynamic model instances and rebuilds more cleanly.

## Common Pitfalls and Troubleshooting

### 1. **Forgetting to Rebuild Dependent Models**

If a model `A` references another model `B`, and `B` is rebuilt, `A` must also be rebuilt to reflect the updated schema. Failing to do so can result in outdated validation logic.

```python
class Address(BaseModel):
    street: str
    city: str

class User(BaseModel):
    name: str
    address: Address

# After modifying Address, rebuild both models
model_rebuild(Address)
model_rebuild(User)
```

### 2. **Incorrect Forward Reference Resolution**

When using forward references, ensure that models are rebuilt in the correct order to resolve dependencies. A common mistake is not rebuilding the model with the forward reference after its target model has been updated.

### 3. **State Loss During Hot Reload**

Hot reloads may cause in-memory state to be lost, especially if models are used to store transient data. Consider implementing a mechanism to persist or rehydrate state after a rebuild.

## Real-World Use Cases

### Configuration Management Systems

In systems where models represent configuration templates, `model_rebuild()` can be used to apply new configurations without downtime.

```python
# config_model.py
class ConfigModel(BaseModel):
    log_level: str
    max_connections: int

# config_loader.py
from config_model import ConfigModel
import importlib.util

def apply_config(path):
    spec = importlib.util.spec_from_file_location("config", path)
    config = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(config)
    model = ConfigModel.model_validate(config.__dict__)
    model_rebuild(ConfigModel)
    return model
```

### API Gateway with Dynamic Endpoints

In API gateways that support dynamic endpoint registration, models can be dynamically loaded and updated to reflect new API contracts.

## Conclusion

Model rebuilding and schema updates are essential patterns in applications that require runtime flexibility and dynamic behavior. Pydantic provides a robust foundation with `model_rebuild()` and schema validation features, enabling developers to implement hot updates and plugin systems with confidence.

By following best practices—such as versioning, logging, and dependency management—engineers can build scalable, maintainable systems that respond efficiently to changing requirements and evolving data structures, all without requiring application restarts.