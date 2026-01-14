# Request Body

When you need to send data from a client (let's say, a browser) to your API, you send it as a **request body**.

A **request** body is data sent by the client to your API. A **response** body is the data your API sends to the client.

Your API almost always has to send a **response** body. But clients don't necessarily need to send **request** bodies all the time.

To declare a **request** body, you use Pydantic models with all their power and benefits.

## Import Pydantic's `BaseModel`

First, you need to import `BaseModel` from `pydantic`:

```python
from typing import Union
from fastapi import FastAPI
from pydantic import BaseModel

class Item(BaseModel):
    name: str
    description: Union[str, None] = None
    price: float
    tax: Union[float, None] = None

app = FastAPI()

@app.post("/items/")
async def create_item(item: Item):
    return item
```

## Declare It as a Parameter

To add it to your path operation, declare it the same way you declared path and query parameters:

```python
@app.post("/items/")
async def create_item(item: Item):
    return item
```

...and declare its type as the model you created, `Item`.

## Results

With just that Python type declaration, FastAPI will:

- Read the body of the request as JSON
- Convert the corresponding types (if needed)
- Validate the data
  - If the data is invalid, it will return a nice and clear error, indicating exactly where and what was the incorrect data
- Give you the received data in the parameter `item`
  - As you declared it in the function to be of type `Item`, you will also have all the editor support (completion, etc.) for all of the attributes and their types
- Generate JSON Schema definitions for your model
  - You can also use them anywhere else you like if it makes sense for your project
- Those schemas will be part of the generated OpenAPI schema, and used by the automatic documentation UIs

## Automatic Docs

The JSON Schemas of your models will be part of your OpenAPI generated schema, and will be shown in the interactive API docs.

And they will also be used in the API docs inside each path operation that needs them.

## Use the Model

Inside of the function, you can access all the attributes of the model object directly:

```python
@app.post("/items/")
async def create_item(item: Item):
    item_dict = item.dict()
    if item.tax:
        price_with_tax = item.price + item.tax
        item_dict.update({"price_with_tax": price_with_tax})
    return item_dict
```

## Request Body + Path Parameters

You can declare path parameters and request body at the same time.

FastAPI will recognize that the function parameters that match path parameters should be **taken from the path**, and that function parameters that are declared to be Pydantic models should be **taken from the request body**.

```python
@app.put("/items/{item_id}")
async def create_item(item_id: int, item: Item):
    return {"item_id": item_id, **item.dict()}
```

## Request Body + Path + Query Parameters

You can also declare **body**, **path** and **query** parameters, all at the same time.

FastAPI will recognize each of them and take the data from the correct place.

```python
@app.put("/items/{item_id}")
async def create_item(item_id: int, item: Item, q: Union[str, None] = None):
    result = {"item_id": item_id, **item.dict()}
    if q:
        result.update({"q": q})
    return result
```

The function parameters will be recognized as follows:

- If the parameter is also declared in the **path**, it will be used as a path parameter
- If the parameter is of a **singular type** (like `int`, `float`, `str`, `bool`, etc.) it will be interpreted as a **query** parameter
- If the parameter is declared to be of the type of a **Pydantic model**, it will be interpreted as a request **body**

## Without Pydantic

If you don't want to use Pydantic models, you can also use **Body** parameters. See the documentation for Body - Multiple Parameters.
