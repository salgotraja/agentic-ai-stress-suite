# Query Parameters

In web API development, query parameters are key-value pairs appended to the URL after a question mark (`?`). They provide a flexible way to pass optional data to an API endpoint, enabling filtering, sorting, and other common operations. In FastAPI, query parameters are handled automatically through type hints and data validation, offering a powerful combination of simplicity and robustness.

Query parameters are distinct from [path parameters (02)](#path-parameters-02) and [request body (04)](#request-body-04). While path parameters define the structure of the URL and are required for routing, query parameters enhance the functionality of a single endpoint. Understanding when and how to use query parameters effectively is essential for building clean and efficient APIs.

---

## Basic Query Parameters

To extract a query parameter in FastAPI, simply declare it as a function parameter with a default value of `None`. FastAPI will automatically parse and validate the input based on the type hint.

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/items/")
async def read_items(q: str = None):
    return {"q": q}
```

In this example, the query parameter `q` is optional. If it is provided, it must be a string. If not, the function will return `{"q": None}`.

Query parameters are particularly useful when multiple inputs can refine a result. For example, filtering a list of items by name or category:

```python
@app.get("/items/")
async def read_items(name: str = None, category: str = None):
    items = [...]  # Assume this is a database or external data source
    if name:
        items = [item for item in items if name.lower() in item["name"].lower()]
    if category:
        items = [item for item in items if category.lower() in item["category"].lower()]
    return items
```

This approach allows clients to construct flexible and expressive queries, reducing the number of endpoints needed for similar operations.

---

## Optional Parameters and Default Values

In many cases, query parameters are optional and should have sensible defaults. FastAPI supports this by allowing default values to be assigned directly.

```python
@app.get("/items/")
async def read_items(limit: int = 10, offset: int = 0):
    return {"limit": limit, "offset": offset}
```

Here, `limit` and `offset` have defaults of 10 and 0, respectively. This is ideal for pagination, where clients can request a subset of results without specifying all parameters.

If you want to distinguish between a parameter not being provided and it being explicitly set to a default, you can use the `Query` function from FastAPI:

```python
from fastapi import Query

@app.get("/items/")
async def read_items(q: str = Query(None, description="Search term")):
    return {"q": q}
```

This provides additional metadata and allows for more precise control over validation and documentation.

---

## Query Parameters for Lists

FastAPI supports query parameters that represent lists by using the `list` type hint. This is useful for filtering by multiple values, such as selecting items by multiple categories.

```python
@app.get("/items/")
async def read_items(categories: list[str] = Query([])):
    items = [...]  # Assume this is a database or external data source
    if categories:
        items = [item for item in items if item["category"] in categories]
    return items
```

In this example, the `categories` parameter expects a comma-separated list of values in the query string: `categories=books,electronics`.

You can also use the `Query` function to enforce constraints like minimum and maximum values, or to make the field required:

```python
@app.get("/items/")
async def read_items(tags: list[str] = Query(..., min_items=1, description="Item tags")):
    return {"tags": tags}
```

This ensures that at least one tag is provided, and the query will return a 422 error otherwise.

---

## Validation and Error Handling

FastAPI includes automatic validation based on type hints and query descriptions. When a query parameter fails validation, FastAPI returns a structured error message with the reason for the failure.

For example, if a client sends a non-integer value for an `int` parameter, the response will look like:

```json
{
  "detail": [
    {
      "loc": ["query", "limit"],
      "msg": "value is not a valid integer",
      "type": "type_error.integer"
    }
  ]
}
```

This allows clients to understand and correct their requests easily.

You can also define custom validation logic using Pydantic models or by using the `Query` function to add regex patterns or other constraints:

```python
@app.get("/users/")
async def read_users(username: str = Query(..., regex="^[a-zA-Z0-9_]+$")):
    return {"username": username}
```

This ensures the username contains only alphanumeric characters and underscores, preventing malformed or potentially dangerous input.

---

## Best Practices

### Use Descriptive Parameter Names

Choose meaningful names for query parameters that clearly indicate their purpose. Avoid ambiguous names like `q` unless they are widely accepted conventions.

### Provide Meaningful Defaults

Set defaults that align with the expected usage of the endpoint. For example, use `limit=10` for pagination rather than `limit=0`, which might return no data.

### Document Clearly

Use the `description` and `example` parameters in `Query` to provide helpful documentation:

```python
@app.get("/items/")
async def read_items(q: str = Query(None, description="Search term", example="fastapi")):
    return {"q": q}
```

This enhances the developer experience by making it easier to understand and test your API.

### Avoid Overloading Parameters

Avoid using query parameters for complex or hierarchical data. In such cases, consider using the request body (04) to pass structured data instead.

### Use Query Parameters for Filtering and Sorting

Query parameters are ideal for operations like filtering, sorting, and pagination. For example:

```python
@app.get("/items/")
async def read_items(sort: str = Query("name", description="Sort by name or price", enum=["name", "price"])):
    items = [...]  # Assume this is a database or external data source
    return sorted(items, key=lambda x: x[sort])
```

This shows how to use an `enum` to restrict the allowed values for `sort`, ensuring predictable behavior.

---

## Cross-Framework Comparison

In frameworks like Django or Flask, query parameters are handled via request objects and require manual parsing and validation. FastAPI, by contrast, offers automatic type validation, reducing boilerplate and improving code clarity.

For example, in Django:

```python
def read_items(request):
    q = request.GET.get('q')
    return JsonResponse({'q': q})
```

This approach lacks type safety and requires additional validation logic. FastAPI's declarative style brings type safety and validation to the forefront, making it more suitable for complex and data-driven APIs.

---

## Troubleshooting and Common Pitfalls

### Case Sensitivity in Parameters

Query parameters in HTTP are case-insensitive, but FastAPI treats them as case-sensitive by default. Ensure your client and server agree on the naming convention to avoid confusion.

### Missing Required Parameters

If you forget to include a required query parameter, FastAPI will return a `422 Unprocessable Entity` error. Always test required parameters to ensure they are properly enforced.

### Overusing Query Parameters

Avoid using query parameters for large or deeply nested data structures. In such cases, a [request body (04)](#request-body-04) is a better choice, as it allows for structured and secure data transmission.

### Performance Considerations

When using query parameters for filtering, especially in large datasets, consider the performance implications. Use indexing or database-level filtering to avoid loading excessive data into memory.

---

## Real-World Use Cases

One common use case is filtering products in an e-commerce API:

```python
@app.get("/products/")
async def read_products(
    category: str = Query(None, description="Product category"),
    min_price: int = Query(None, description="Minimum price"),
    max_price: int = Query(None, description="Maximum price"),
    sort: str = Query("name", description="Sort by name or price", enum=["name", "price"]),
    limit: int = Query(10, description="Maximum number of results", ge=1, le=100),
    offset: int = Query(0, description="Offset for pagination")
):
    # Simulated filtering and sorting logic
    return {"category": category, "min_price": min_price, "max_price": max_price, "sort": sort, "limit": limit, "offset": offset}
```

This endpoint demonstrates how multiple query parameters can be used together to create a flexible and powerful search and pagination interface.

Another example is in log analysis tools, where query parameters allow filtering logs by severity level and source:

```python
@app.get("/logs/")
async def read_logs(
    level: str = Query(None, description="Log level", enum=["DEBUG", "INFO", "WARNING", "ERROR"]),
    source: str = Query(None, description="Log source"),
    start_time: str = Query(None, description="Start time (ISO 8601 format)"),
    end_time: str = Query(None, description="End time (ISO 8601 format)")
):
    # Simulated log retrieval
    return {"level": level, "source": source, "start_time": start_time, "end_time": end_time}
```

These examples show how query parameters can be used to create powerful, user-friendly APIs with minimal code.

By mastering query parameters in FastAPI, you gain the ability to build highly flexible and expressive APIs that meet the needs of modern web applications.