# Pydantic with SQLAlchemy

Using Pydantic with SQLAlchemy enables a powerful combination of ORM capabilities and data validation. SQLAlchemy provides the database layer, while Pydantic ensures data integrity and type safety at the application level. This synergy is particularly useful in REST APIs, data pipelines, and applications requiring strict data validation. By integrating these two frameworks, you can build robust applications that maintain consistency and correctness between the database and business logic layers.

This documentation will explore the integration of Pydantic with SQLAlchemy, covering key concepts like hybrid models, database models, and type mapping. We'll also demonstrate practical examples involving CRUD operations and model conversion strategies.

---

## Hybrid Models

Hybrid models are a common pattern when integrating Pydantic with SQLAlchemy. These models combine the database model (SQLAlchemy ORM) with a Pydantic model for data validation and serialization. This approach allows for clean separation of concerns—SQLAlchemy handles persistence, while Pydantic ensures that data is valid and conforms to expected structures.

```python
from sqlalchemy import Column, Integer, String, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from pydantic import BaseModel
from typing import Optional

Base = declarative_base()

class UserDBModel(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    name = Column(String)
    email = Column(String)
    age = Column(Integer)

class UserPydanticModel(BaseModel):
    id: int
    name: str
    email: str
    age: Optional[int] = None
```

In this case, `UserDBModel` is the SQLAlchemy model, while `UserPydanticModel` is the Pydantic model used for validation and serialization. The `Optional[int]` type for `age` allows for flexibility in the API layer, even if the database requires a non-null value.

## Database Models

SQLAlchemy models define the structure of the database tables and the relationships between them. They are typically used to perform CRUD operations and manage database sessions. Here’s an example of a database model for a `User` entity:

```python
engine = create_engine("sqlite:///:memory:")
Base.metadata.create_all(bind=engine)

SessionLocal = sessionmaker(bind=engine)

# Create a new user in the database
def create_user(session, name: str, email: str, age: int):
    db_user = UserDBModel(name=name, email=email, age=age)
    session.add(db_user)
    session.commit()
    session.refresh(db_user)
    return db_user
```

This function creates a new user using SQLAlchemy and commits the change to the in-memory SQLite database. The `session` object ensures that the operation is transactional and atomic.

---

## Type Mapping

One of the key challenges when integrating Pydantic with SQLAlchemy is mapping SQLAlchemy types to Pydantic types. While the core types often align, custom or complex types may require explicit conversion.

```python
from datetime import datetime

class BlogPostDBModel(Base):
    __tablename__ = "blog_posts"
    id = Column(Integer, primary_key=True)
    title = Column(String)
    content = Column(String)
    created_at = Column(String)  # Stored as ISO 8601 string in the database

class BlogPostPydanticModel(BaseModel):
    id: int
    title: str
    content: str
    created_at: datetime  # Pydantic expects a datetime object

def blog_post_db_to_pydantic(blog_post_db: BlogPostDBModel) -> BlogPostPydanticModel:
    return BlogPostPydanticModel(
        id=blog_post_db.id,
        title=blog_post_db.title,
        content=blog_post_db.content,
        created_at=datetime.fromisoformat(blog_post_db.created_at)
    )
```

In this example, SQLAlchemy stores the `created_at` field as a string, while Pydantic expects a `datetime` object. The conversion is handled in a helper function to ensure type safety and consistency. Explicit type mapping is essential when the ORM and data validation layers use different types.

---

## CRUD Operations with Pydantic Models

To perform CRUD operations using Pydantic models, it's common to convert between SQLAlchemy ORM models and Pydantic models. This ensures that input and output data are validated and structured correctly.

```python
def get_user(session, user_id: int) -> UserPydanticModel:
    user_db = session.query(UserDBModel).filter(UserDBModel.id == user_id).first()
    if not user_db:
        return None
    return UserPydanticModel.from_orm(user_db)

def update_user(session, user_id: int, user_update: UserPydanticModel) -> UserPydanticModel:
    user_db = session.query(UserDBModel).get(user_id)
    if not user_db:
        return None

    for key, value in user_update.dict(exclude_unset=True).items():
        setattr(user_db, key, value)

    session.commit()
    session.refresh(user_db)
    return UserPydanticModel.from_orm(user_db)
```

Here, `get_user` retrieves a user from the database and converts it to a Pydantic model using `from_orm`. The `update_user` function allows partial updates by using `user_update.dict(exclude_unset=True)`, which includes only the keys that were actually set in the input.

### Why Use `from_orm`?

The `from_orm` method is a Pydantic utility that creates a model instance from any class that has `__dict__`, such as SQLAlchemy ORM objects. It's the preferred method for converting ORM models to Pydantic models without manually mapping fields. This approach is both clean and maintainable.

---

## Model Conversion and Validation

Validating input and output data is a crucial part of any API or data processing pipeline. Pydantic models can be used to validate incoming data before it is persisted to the database and to ensure that output data conforms to the expected format.

```python
def create_user_from_pydantic(session, user_create: UserPydanticModel) -> UserPydanticModel:
    user_db = UserDBModel(**user_create.dict())
    session.add(user_db)
    session.commit()
    session.refresh(user_db)
    return UserPydanticModel.from_orm(user_db)

user_data = {
    "name": "Alice",
    "email": "alice@example.com",
    "age": 30
}

try:
    user_create = UserPydanticModel(**user_data)
    user_response = create_user_from_pydantic(session, user_create)
    print(user_response)
except Exception as e:
    print(f"Validation failed: {e}")
```

This example uses Pydantic’s validation capabilities to ensure that `user_data` conforms to the expected schema before attempting to create a database record. This pattern is especially valuable in web APIs where incorrect input can lead to database errors or security vulnerabilities.

---

## Best Practices

### 1. Use Hybrid Models for Separation of Concerns

Always separate your SQLAlchemy models (for persistence) and Pydantic models (for validation and serialization). This makes your codebase more maintainable and testable.

### 2. Validate Input Before Persisting

Use Pydantic to validate input data before converting it to SQLAlchemy ORM models. This reduces the risk of invalid data being written to the database.

### 3. Convert ORM Models to Pydantic Models for Output

When returning data from the database, convert SQLAlchemy ORM models to Pydantic models to ensure consistent and validated output.

### 4. Handle Optional and Default Values Carefully

Use `Optional` and default values in Pydantic models to account for nullable fields in the database. This avoids runtime errors and makes your API more resilient.

### 5. Leverage Pydantic’s `from_orm` and `dict` Methods

These methods simplify the conversion between SQLAlchemy ORM models and Pydantic models, reducing boilerplate code and improving readability.

---

## Common Pitfalls

### 1. Circular Dependencies

If your models reference each other and you use `from_orm`, you may encounter circular dependency errors. To avoid this, use forward references or import the models in a separate file.

### 2. Incorrect Type Mapping

Mismatched types between SQLAlchemy and Pydantic can lead to runtime errors. Always ensure that the types in your Pydantic models match the types returned by your ORM queries, especially for complex or custom types.

### 3. Overuse of `from_orm`

While `from_orm` is convenient, it’s not always necessary. Use it when you want to take advantage of Pydantic's validation and serialization features. If you only need to extract data, consider using `.dict()` or `.json()` instead.

---

## Troubleshooting

### 1. Validation Fails Silently

If Pydantic validation fails and you're not catching the exception, it may lead to unexpected behavior. Always wrap Pydantic model creation in a `try/except` block to handle validation errors.

### 2. SQLAlchemy Session Not Committed

If changes are not being saved to the database, ensure that `session.commit()` is called after modifying the ORM model.

### 3. Model Conversion Errors

If `from_orm` throws an error, check that all required fields exist in the ORM model and that the attributes are correctly named and typed.

---

## Cross-References

- **ORM mode (32)**: Pydantic’s ORM mode allows direct mapping from ORM models to Pydantic models using `from_orm`.
- **Serialization (11)**: Pydantic models provide rich serialization capabilities, including JSON support and format customization.

---

## Conclusion

Integrating Pydantic with SQLAlchemy provides a robust and maintainable architecture for applications that require strong data validation and database persistence. By leveraging hybrid models, careful type mapping, and Pydantic's powerful validation features, you can build applications that are both type-safe and production-ready. With these patterns in place, you can ensure that your data flows correctly between the database, business logic, and API layers, reducing bugs and improving overall code quality.