# Events: Startup and Shutdown

FastAPI provides robust mechanisms for executing code during application lifecycle events, specifically at startup and shutdown. These event handlers are crucial for managing resources that need to be initialized before the application begins serving requests and cleaned up gracefully when the application terminates. Understanding and properly implementing lifecycle events is essential for building production-ready applications that handle database connections, cache systems, external API clients, and other stateful resources efficiently.

## Understanding Application Lifecycle Events

Application lifecycle management is a critical aspect of building reliable web services. In FastAPI, lifecycle events allow you to define logic that executes exactly once when your application starts and once when it shuts down, regardless of how many worker processes are running. This is fundamentally different from dependency injection, which executes per-request, or background tasks, which execute asynchronously during request processing.

The lifecycle events serve several important purposes. During startup, you typically want to establish connections to external services, initialize connection pools, load configuration data, warm up caches, or perform health checks on dependent systems. During shutdown, you need to close database connections gracefully, flush pending writes, release file handles, cancel background tasks, and ensure that no data is lost or corrupted.

FastAPI originally provided the `@app.on_event()` decorator for handling these events, but has since introduced the more powerful and flexible lifespan context manager approach. While both methods are still supported, the lifespan context manager is now the recommended pattern for new applications due to its superior error handling, better testability, and cleaner resource management semantics.

## The Legacy Event Decorator Approach

The `@app.on_event()` decorator provides a straightforward way to register startup and shutdown handlers. This approach is intuitive and works well for simple use cases where you need to perform independent initialization and cleanup tasks.

```python
from fastapi import FastAPI
import asyncpg
from redis import asyncio as aioredis

app = FastAPI()

# Global variables to store connections
db_pool = None
redis_client = None

@app.on_event("startup")
async def startup_event():
    global db_pool, redis_client
    
    # Initialize database connection pool
    db_pool = await asyncpg.create_pool(
        host="localhost",
        port=5432,
        user="myuser",
        password="mypassword",
        database="mydb",
        min_size=10,
        max_size=50,
        command_timeout=60
    )
    
    # Initialize Redis connection
    redis_client = await aioredis.from_url(
        "redis://localhost",
        encoding="utf-8",
        decode_responses=True,
        max_connections=20
    )
    
    print("Database and cache connections established")

@app.on_event("shutdown")
async def shutdown_event():
    global db_pool, redis_client
    
    # Close database pool
    if db_pool:
        await db_pool.close()
        print("Database pool closed")
    
    # Close Redis connection
    if redis_client:
        await redis_client.close()
        print("Redis connection closed")
```

While this approach works, it has several limitations. The startup and shutdown handlers are separate functions, making it harder to ensure that resources initialized during startup are properly cleaned up during shutdown. Error handling becomes complex when you need to track which resources were successfully initialized. Additionally, testing these handlers in isolation can be challenging since they rely on global state.

## The Modern Lifespan Context Manager

The lifespan context manager, introduced in FastAPI 0.93.0 and based on the ASGI lifespan protocol, provides a more robust and Pythonic approach to lifecycle management. It uses an async context manager that clearly pairs initialization and cleanup logic, ensuring resources are properly managed even when errors occur.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
import asyncpg
from redis import asyncio as aioredis
from typing import AsyncGenerator

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[dict, None]:
    # Startup: Initialize resources
    print("Starting up application...")
    
    # Initialize database pool
    db_pool = await asyncpg.create_pool(
        host="localhost",
        port=5432,
        user="myuser",
        password="mypassword",
        database="mydb",
        min_size=10,
        max_size=50,
        command_timeout=60
    )
    
    # Initialize Redis
    redis_client = await aioredis.from_url(
        "redis://localhost",
        encoding="utf-8",
        decode_responses=True,
        max_connections=20
    )
    
    # Initialize ML model or other heavy resources
    ml_model = load_machine_learning_model()
    
    # Store in app state for access in routes
    app.state.db = db_pool
    app.state.redis = redis_client
    app.state.model = ml_model
    
    print("Application startup complete")
    
    yield  # Application is running and serving requests
    
    # Shutdown: Clean up resources
    print("Shutting down application...")
    
    await db_pool.close()
    await redis_client.close()
    
    print("All connections closed gracefully")

app = FastAPI(lifespan=lifespan)

@app.get("/users/{user_id}")
async def get_user(user_id: int):
    # Access database pool from app state
    async with app.state.db.acquire() as connection:
        user = await connection.fetchrow(
            "SELECT * FROM users WHERE id = $1", user_id
        )
        return user

def load_machine_learning_model():
    # Simulate loading a heavy ML model
    return {"model": "loaded"}
```

The lifespan context manager provides several advantages. The `yield` statement clearly separates startup and shutdown phases, making the code more readable and maintainable. Resources are automatically available in the `app.state` object, eliminating the need for global variables. The context manager pattern ensures that cleanup code always runs, even if an exception occurs during startup or request handling. This approach also makes testing significantly easier since you can mock the lifespan context for unit tests.

## Advanced Patterns and Production Considerations

In production environments, you need to handle more complex scenarios such as initialization failures, partial resource allocation, and graceful degradation. Here's a production-ready pattern that implements comprehensive error handling and logging:

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
import asyncpg
from redis import asyncio as aioredis
import logging
from typing import AsyncGenerator

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class ApplicationState:
    """Centralized application state management"""
    def __init__(self):
        self.db_pool = None
        self.redis_client = None
        self.is_healthy = False

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    state = ApplicationState()
    
    try:
        # Database initialization with retry logic
        logger.info("Initializing database connection pool...")
        state.db_pool = await asyncpg.create_pool(
            host="localhost",
            port=5432,
            user="myuser",
            password="mypassword",
            database="mydb",
            min_size=10,
            max_size=50,
            command_timeout=60,
            timeout=30
        )
        logger.info("Database pool created successfully")
        
        # Redis initialization
        logger.info("Connecting to Redis...")
        state.redis_client = await aioredis.from_url(
            "redis://localhost",
            encoding="utf-8",
            decode_responses=True,
            max_connections=20
        )
        
        # Verify Redis connection
        await state.redis_client.ping()
        logger.info("Redis connection established")
        
        # Warm up cache with frequently accessed data
        await warm_up_cache(state.redis_client, state.db_pool)
        
        state.is_healthy = True
        app.state.resources = state
        
        logger.info("Application startup completed successfully")
        
    except Exception as e:
        logger.error(f"Failed to initialize application: {e}")
        # Clean up any partially initialized resources
        if state.db_pool:
            await state.db_pool.close()
        if state.redis_client:
            await state.redis_client.close()
        raise
    
    yield  # Application runs here
    
    # Shutdown phase
    logger.info("Beginning graceful shutdown...")
    
    try:
        if state.redis_client:
            await state.redis_client.close()
            logger.info("Redis connection closed")
    except Exception as e:
        logger.error(f"Error closing Redis: {e}")
    
    try:
        if state.db_pool:
            await state.db_pool.close()
            logger.info("Database pool closed")
    except Exception as e:
        logger.error(f"Error closing database pool: {e}")
    
    logger.info("Shutdown complete")

async def warm_up_cache(redis_client, db_pool):
    """Preload frequently accessed data into cache"""
    async with db_pool.acquire() as conn:
        popular_items = await conn.fetch(
            "SELECT id, data FROM items ORDER BY access_count DESC LIMIT 100"
        )
        for item in popular_items:
            await redis_client.setex(
                f"item:{item['id']}", 
                3600, 
                item['data']
            )
    logger.info(f"Cache warmed with {len(popular_items)} items")

app = FastAPI(lifespan=lifespan)

@app.get("/health")
async def health_check(request: Request):
    """Health check endpoint that verifies resource availability"""
    is_healthy = request.app.state.resources.is_healthy
    
    if not is_healthy:
        return {"status": "unhealthy"}, 503
    
    # Verify database connectivity
    try:
        async with request.app.state.resources.db_pool.acquire() as conn:
            await conn.fetchval("SELECT 1")
    except Exception:
        return {"status": "unhealthy", "reason": "database"}, 503
    
    return {"status": "healthy"}
```

## Integration with Dependencies and Background Tasks

Lifecycle events work seamlessly with FastAPI's dependency injection system and background tasks. Resources initialized during startup can be injected into route handlers through dependencies, creating a clean separation of concerns. This is particularly useful when you need to reference See Dependencies (05) for detailed patterns on injecting application state.

When working with background tasks, it's important to ensure they complete before shutdown. While background tasks added via `BackgroundTasks` are automatically awaited, long-running tasks may need explicit cancellation logic during shutdown. For more information on managing concurrent operations, refer to Background tasks (08).

```python
from fastapi import FastAPI, Depends, BackgroundTasks
from typing import AsyncGenerator

async def get_db(request: Request) -> AsyncGenerator:
    """Dependency that provides database connection"""
    async with request.app.state.resources.db_pool.acquire() as conn:
        yield conn

@app.post("/users")
async def create_user(
    user_data: dict,
    background_tasks: BackgroundTasks,
    db=Depends(get_db)
):
    """Create user and send welcome email in background"""
    user_id = await db.fetchval(
        "INSERT INTO users (name, email) VALUES ($1, $2) RETURNING id",
        user_data["name"],
        user_data["email"]
    )
    
    background_tasks.add_task(send_welcome_email, user_data["email"])
    
    return {"id": user_id}
```

## Best Practices

Always use the lifespan context manager for new applications as it provides superior error handling and resource management. Store initialized resources in `app.state` rather than global variables to maintain clean architecture and improve testability. Implement comprehensive logging during startup and shutdown to facilitate debugging in production environments.

Design your initialization code to be idempotent where possible, allowing for safe restarts. Implement health check endpoints that verify the availability of critical resources initialized during startup. Use connection pools for databases and external services rather than creating connections per request, as this significantly improves performance and resource utilization.

Always implement graceful shutdown logic that closes connections, flushes buffers, and completes in-flight operations. Set appropriate timeouts for initialization operations to prevent indefinite hanging during startup. Consider implementing retry logic for transient failures when connecting to external services.

Handle partial initialization failures gracefully by cleaning up successfully initialized resources before raising exceptions. Use structured logging to track the initialization and cleanup of each resource. Test your startup and shutdown logic thoroughly, including failure scenarios, to ensure your application behaves correctly under all conditions.