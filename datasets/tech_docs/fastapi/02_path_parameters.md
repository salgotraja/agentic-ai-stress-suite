# Path Parameters

You can declare path "parameters" or "variables" with the same syntax used by Python format strings:

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"item_id": item_id}
```

The value of the path parameter `item_id` will be passed to your function as the argument `item_id`.

## Path Parameters with Types

You can declare the type of a path parameter in the function using standard Python type annotations:

```python
@app.get("/items/{item_id}")
async def read_item(item_id: int):
    return {"item_id": item_id}
```

With type annotations, FastAPI gives you:

- **Editor support**: error checks, completion, etc.
- **Data parsing**: the value will be converted to the declared type
- **Data validation**: if the data is not valid, a clear error will be returned
- **API documentation**: the type will be shown in the auto-generated docs

## Order Matters

When creating path operations, you can find situations where you have a fixed path.

Like `/users/me`, let's say that it's to get data about the current user.

And then you can also have a path `/users/{user_id}` to get data about a specific user by their ID.

Because path operations are evaluated in order, you need to make sure that the path for `/users/me` is declared before the one for `/users/{user_id}`:

```python
@app.get("/users/me")
async def read_user_me():
    return {"user_id": "the current user"}

@app.get("/users/{user_id}")
async def read_user(user_id: str):
    return {"user_id": user_id}
```

Otherwise, the path for `/users/{user_id}` would match also for `/users/me`, "thinking" that it's receiving the parameter `user_id` with a value of `"me"`.

## Predefined Values

If you have a path operation that receives a path parameter, but you want the possible valid path parameter values to be predefined, you can use a standard Python `Enum`.

### Create an Enum Class

Import `Enum` and create a sub-class that inherits from `str` and from `Enum`:

```python
from enum import Enum

class ModelName(str, Enum):
    alexnet = "alexnet"
    resnet = "resnet"
    lenet = "lenet"
```

### Declare a Path Parameter

Then create a path parameter with type annotations using the enum class you created:

```python
@app.get("/models/{model_name}")
async def get_model(model_name: ModelName):
    if model_name is ModelName.alexnet:
        return {"model_name": model_name, "message": "Deep Learning FTW!"}

    if model_name.value == "lenet":
        return {"model_name": model_name, "message": "LeCNN all the images"}

    return {"model_name": model_name, "message": "Have some residuals"}
```

The value of the path parameter will be an enumeration member.

## Path Parameters Containing Paths

Let's say you have a path operation with a path `/files/{file_path}`.

But you need `file_path` itself to contain a path, like `home/johndoe/myfile.txt`.

So, the URL for that file would be something like: `/files/home/johndoe/myfile.txt`.

You can do that using an option directly from Starlette:

```python
@app.get("/files/{file_path:path}")
async def read_file(file_path: str):
    return {"file_path": file_path}
```

The parameter could have a value of `/home/johndoe/myfile.txt`, with a leading slash (`/`).

In that case, the URL would be: `/files//home/johndoe/myfile.txt`, with a double slash (`//`) between `files` and `home`.
