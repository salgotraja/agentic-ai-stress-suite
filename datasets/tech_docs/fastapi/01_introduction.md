# FastAPI Introduction

FastAPI is a modern, fast (high-performance), web framework for building APIs with Python 3.7+ based on standard Python type hints.

## Key Features

- **Fast**: Very high performance, on par with NodeJS and Go (thanks to Starlette and Pydantic)
- **Fast to code**: Increase the speed to develop features by about 200% to 300%
- **Fewer bugs**: Reduce about 40% of human (developer) induced errors
- **Intuitive**: Great editor support. Completion everywhere. Less time debugging
- **Easy**: Designed to be easy to use and learn. Less time reading docs
- **Short**: Minimize code duplication. Multiple features from each parameter declaration
- **Robust**: Get production-ready code with automatic interactive documentation
- **Standards-based**: Based on (and fully compatible with) the open standards for APIs: OpenAPI and JSON Schema

## Requirements

Python 3.7+

FastAPI stands on the shoulders of giants:
- Starlette for the web parts
- Pydantic for the data parts

## Installation

```bash
pip install fastapi
pip install "uvicorn[standard]"
```

## First Steps

Create a file `main.py` with:

```python
from fastapi import FastAPI

app = FastAPI()

@app.get("/")
def read_root():
    return {"Hello": "World"}

@app.get("/items/{item_id}")
def read_item(item_id: int, q: str = None):
    return {"item_id": item_id, "q": q}
```

## Run It

Run the server with:

```bash
uvicorn main:app --reload
```

The `--reload` flag makes the server restart after code changes. Only use for development.

## Check It

Open your browser at http://127.0.0.1:8000

You will see the JSON response:

```json
{"Hello": "World"}
```

## Interactive API Docs

Now go to http://127.0.0.1:8000/docs

You will see the automatic interactive API documentation (provided by Swagger UI).

## Alternative API Docs

You can also visit http://127.0.0.1:8000/redoc

The alternative automatic documentation (provided by ReDoc).
