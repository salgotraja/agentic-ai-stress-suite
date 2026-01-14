# Dependencies - Dependency Injection

FastAPI has a very powerful but intuitive **Dependency Injection** system.

It is designed to be very simple to use, and very easy to integrate.

## What is "Dependency Injection"

"Dependency Injection" means, in programming, that there is a way for your code (in this case, your path operation functions) to declare things that it requires to work and use: "dependencies".

And then, that system (in this case FastAPI) will take care of doing whatever is needed to provide your code with those needed dependencies ("inject" the dependencies).

This is very useful when you need to:

- Have shared logic (the same code logic again and again)
- Share database connections
- Enforce security, authentication, role requirements, etc.
- And many other things...

All these, while minimizing code repetition.

## First Steps

Let's see a very simple example. It will be so simple that it is not very useful, for now.

But this way we can focus on how the **Dependency Injection** system works.

### Create a Dependency

Let's first focus on the dependency.

It is just a function that can take all the same parameters that a path operation function can take:

```python
from typing import Union
from fastapi import Depends, FastAPI

app = FastAPI()

async def common_parameters(q: Union[str, None] = None, skip: int = 0, limit: int = 100):
    return {"q": q, "skip": skip, "limit": limit}

@app.get("/items/")
async def read_items(commons: dict = Depends(common_parameters)):
    return commons

@app.get("/users/")
async def read_users(commons: dict = Depends(common_parameters)):
    return commons
```

### Declare the Dependency

The same way you use `Body`, `Query`, etc. with your path operation function parameters, use `Depends` with a new parameter:

```python
async def read_items(commons: dict = Depends(common_parameters)):
```

Although you use `Depends` in the parameters of your function the same way you use `Body`, `Query`, etc., `Depends` works a little bit differently.

You only give `Depends` a single parameter.

This parameter must be something like a function.

You don't call it directly (don't add the parenthesis at the end), you just pass it as a parameter to `Depends()`.

And that function takes parameters in the same way that path operation functions do.

## To `async` or not to `async`

As dependencies will also be called by FastAPI (the same as your path operation functions), the same rules apply while defining your functions.

You can use `async def` or normal `def`.

And you can declare dependencies with `async def` inside of normal `def` path operation functions, or `def` dependencies inside of `async def` path operation functions, etc.

It doesn't matter. FastAPI will know what to do.

## Classes as Dependencies

You can also use a Python class as a dependency.

```python
from fastapi import Depends, FastAPI

app = FastAPI()

class CommonQueryParams:
    def __init__(self, q: Union[str, None] = None, skip: int = 0, limit: int = 100):
        self.q = q
        self.skip = skip
        self.limit = limit

@app.get("/items/")
async def read_items(commons: CommonQueryParams = Depends(CommonQueryParams)):
    response = {}
    if commons.q:
        response.update({"q": commons.q})
    response.update({"skip": commons.skip, "limit": commons.limit})
    return response
```

Pay attention to the `__init__` method used to create the instance of the class.

It has the same parameters as our previous `common_parameters`.

Those parameters are what FastAPI will use to "solve" the dependency.

In both cases, it will:

- Call that dependency (class or function) with the right parameters
- Get the result
- Assign that result to the parameter in your path operation function

## Sub-dependencies

You can create dependencies that have **sub-dependencies**.

They can be as **deep** as you need them to be.

FastAPI will take care of solving them.

```python
from fastapi import Cookie, Depends, FastAPI

app = FastAPI()

def query_extractor(q: Union[str, None] = None):
    return q

def query_or_cookie_extractor(
    q: str = Depends(query_extractor), last_query: Union[str, None] = Cookie(default=None)
):
    if not q:
        return last_query
    return q

@app.get("/items/")
async def read_query(query_or_default: str = Depends(query_or_cookie_extractor)):
    return {"q_or_cookie": query_or_default}
```

Notice that we are declaring a dependency in another dependency.

The `query_or_cookie_extractor` dependency depends on `query_extractor`.

And at the same time, it declares a `Cookie` dependency for `last_query`.

Then, the path operation depends on `query_or_cookie_extractor`.

Even if this example is contrived, it shows how the dependencies can be combined.

## Dependencies in Path Operation Decorators

In some cases you don't really need the return value of a dependency inside your path operation function.

Or the dependency doesn't return a value.

But you still need it to be executed/solved.

For those cases, instead of declaring a path operation function parameter with `Depends`, you can add a `list` of `dependencies` to the path operation decorator.

```python
from fastapi import Depends, FastAPI, Header, HTTPException

app = FastAPI()

async def verify_token(x_token: str = Header()):
    if x_token != "fake-super-secret-token":
        raise HTTPException(status_code=400, detail="X-Token header invalid")

async def verify_key(x_key: str = Header()):
    if x_key != "fake-super-secret-key":
        raise HTTPException(status_code=400, detail="X-Key header invalid")
    return x_key

@app.get("/items/", dependencies=[Depends(verify_token), Depends(verify_key)])
async def read_items():
    return [{"item": "Foo"}, {"item": "Bar"}]
```

These dependencies will be executed/solved the same way normal dependencies. But their value (if they return any) won't be passed to your path operation function.

## Global Dependencies

Later we will see how to add dependencies to a whole `FastAPI` application, so that they apply to each path operation.
