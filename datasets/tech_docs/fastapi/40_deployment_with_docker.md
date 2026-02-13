# Deployment with Docker

Deploying FastAPI applications in production requires careful consideration of containerization strategies to ensure reliability, security, and performance. Docker provides a standardized way to package applications with their dependencies, but effective deployment requires optimization techniques like multi-stage builds, proper uvicorn configuration, and health checks. This guide provides production-grade patterns for deploying FastAPI with Docker, focusing on best practices and real-world implementation details.

## Dockerfile Best Practices

A well-constructed Dockerfile is critical for production deployments. The choices made during image construction directly impact security, performance, and maintainability. Key best practices include:

1. **Minimal Base Images**: Use lightweight base images like `python:3.11-slim` or `python:3.11-alpine` to reduce attack surfaces and build times.
2. **Layer Optimization**: Group related commands to leverage Docker's layer caching. For example:
   ```dockerfile
   RUN apt-get update && \
       apt-get install -y --no-install-recommends libgomp1 && \
       apt-get clean && \
       rm -rf /var/lib/apt/lists/*
   ```
3. **Security Isolation**: Avoid running as root by creating a dedicated user:
   ```dockerfile
   RUN adduser --disabled-password --gecos '' myuser
   USER myuser
   ```
4. **Dependency Separation**: Install build-time dependencies separately from runtime dependencies to reduce image size.

### Production Dockerfile Example

This example shows a secure, optimized Dockerfile with non-root user and environment configuration:
```dockerfile
# Use official Python image with security updates
FROM python:3.11-slim as builder

# Create a directory for the application
WORKDIR /app

# Copy requirements first to leverage layer caching
COPY requirements.txt .
RUN pip install --user -r requirements.txt

# Final stage
FROM python:3.11-slim

# Install only runtime dependencies
COPY --from=builder /root/.local /root/.local
ENV PATH="/root/.local/bin:$PATH"

# Create non-root user and set working directory
RUN adduser --disabled-password --gecos '' myuser
WORKDIR /home/myuser/app
COPY --chown=myuser:myuser . .

# Set environment variables
ENV APP_MODULE="main:app" \
    API_PORT="80" \
    API_HOST="0.0.0.0" \
    PYTHONUNBUFFERED=1

# Switch to non-root user
USER myuser

# Start command
CMD ["uvicorn", "--host", "$API_HOST", "--port", "$API_PORT", "$APP_MODULE"]
```

## Multi-Stage Builds

Multi-stage builds are essential for production Docker images, combining the benefits of build-time tools with minimal runtime images. This pattern addresses two key challenges:

1. **Size Reduction**: Final images contain only runtime dependencies
2. **Security**: Build tools and temporary files are excluded from the final image

### Implementation Pattern

```dockerfile
# Build stage with full Python environment
FROM python:3.11 as builder
WORKDIR /app
COPY requirements.txt .
RUN pip install --user -r requirements.txt

# Final stage with minimal base image
FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
ENV PATH="/root/.local/bin:$PATH"

# Security: Add non-root user
RUN adduser --disabled-password --gecos '' myuser
USER myuser

# Copy application code
COPY --chown=myuser:myuser . .
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "80"]
```

This approach reduces image size by up to 70% compared to single-stage builds while eliminating build tools from the runtime environment. It's particularly valuable when using complex dependencies that require compilation.

## Uvicorn Configuration

Proper uvicorn configuration is critical for production performance. The default development settings are insufficient for production use. Key considerations include:

1. **Production-Grade Server**: Use Uvicorn with Gunicorn for multi-worker support
2. **Socket Binding**: Ensure correct host and port configuration for container environments
3. **Access Logs**: Enable logging for monitoring and troubleshooting

### Production Uvicorn Setup

```dockerfile
# Install production dependencies
RUN pip install uvicorn[gunicorn] gunicorn

# Command to run the application
CMD ["gunicorn", "-w", "4", "--timeout", "120", "--bind", "0.0.0.0:80", "main:app"]
```

This configuration uses Gunicorn's prefork model to handle multiple requests concurrently. The timeout setting of 120 seconds helps prevent hung requests from blocking worker processes. For applications with high I/O wait, consider using eventlet or gevent workers instead.

## Health Checks

Health checks are crucial for container orchestration systems like Kubernetes and Docker Swarm. They enable automatic restarts of unhealthy containers and ensure traffic is only routed to healthy instances.

### Implementing Health Checks

```dockerfile
# Add health check configuration
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
  CMD curl -f http://localhost/health || exit 1
```

The health check endpoint should be a lightweight route that:
1. Verifies database connectivity (if applicable)
2. Checks critical external services
3. Returns HTTP 200 when healthy
4. Returns HTTP 503 when degraded

Example implementation in FastAPI:
```python
@app.get("/health")
async def health_check():
    try:
        # Perform lightweight health checks
        db.ping()
        return {"status": "healthy"}
    except Exception:
        raise HTTPException(status_code=503, detail="Service Unavailable")
```

## Best Practices

### Environment Variables

Use environment variables for configuration rather than hardcoded values. This enables:
- Different configurations for dev/staging/prod
- Easy parameterization in orchestration systems
- Secure secret management

Example usage in FastAPI:
```python
from fastapi import FastAPI
from pydantic import BaseSettings

class Settings(BaseSettings):
    api_key: str
    database_url: str

settings = Settings(_env_file=".env")

app = FastAPI()
app.state.settings = settings
```

### Volumes for Configuration

Use Docker volumes for configuration files that need frequent updates:
```dockerfile
# Mount configuration volume
VOLUME /app/config
```

This allows configuration to be updated without rebuilding the image.

### Security Hardening

1. **Non-root User**: As shown in the Dockerfile examples
2. **Read-only Filesystem**: For maximum security:
   ```dockerfile
   RUN chmod -R a-w /usr/local/lib/python3.11/site-packages
   CMD ["python", "-O", "app.py"]
   ```
3. **Capability Drop**: Remove unnecessary capabilities:
   ```dockerfile
   RUN setcap CAP_NET_BIND_SERVICE=+eip /usr/local/bin/uvicorn
   ```

## Performance Considerations (34)

Optimizing Docker builds and runtime performance requires attention to:
- **Build Cache**: Order Dockerfile instructions to maximize cache reuse
- **Image Size**: Use `docker image ls --format '{{.Size}}\t{{.Repository}}:{{.Tag}}'` to monitor
- **Concurrent Workers**: Adjust based on CPU cores and memory constraints
- **Precompiled Bytecode**: Use `pip install .` with `--no-cache-dir` to avoid stale bytecode

## Monitoring Integration (33)

Health checks work with monitoring systems like:
- Prometheus with cadvisor for container metrics
- Datadog for log aggregation
- ELK stack for centralized logging

Docker provides built-in health check integration:
```yaml
healthcheck:
  test: ["CMD", "curl", "-f", "http://localhost:80/health"]
  interval: 30s
  timeout: 10s
```

## Troubleshooting Common Issues

### Missing Dependencies
**Symptom**: `ImportError` at runtime  
**Solution**: Verify all dependencies are installed in both build and runtime stages

### Permission Errors
**Symptom**: `Permission denied` errors in mounted volumes  
**Solution**: Ensure the non-root user has proper permissions:
```dockerfile
RUN chown -R myuser:myuser /app/data
```

### Container Starts but No Response
**Symptom**: Container runs but no network response  
**Solution**: Check if the application is binding to `0.0.0.0` rather than `127.0.0.1`

### Health Check Failures
**Symptom**: Containers marked as unhealthy  
**Solution**: Add logging to health check endpoint and verify network connectivity:
```python
@app.get("/health")
async def health_check():
    logger.info("Health check called")
    return {"status": "healthy"}
```

## Cross-Framework Comparison

Compared to Flask and Django, FastAPI's Docker deployment patterns are simpler due to its native ASGI support. A comparison with Django's WSGI-based deployment shows:

| Feature                | FastAPI + Docker                  | Django + Docker                    |
|-----------------------|-----------------------------------|-----------------------------------|
| Server Setup          | uvicorn or gunicorn + uvicorn     | gunicorn + whitenoise             |
| ASGI Support          | Native                            | Requires configuration            |
| Startup Time          | 0.1-0.3s with warm containers     | 1-3s (varies with dependencies)   |
| Memory Usage          | 50-80MB per container             | 80-150MB per container            |

## Conclusion

Production deployment of FastAPI with Docker requires careful attention to security, performance, and maintainability. By implementing multi-stage builds, optimizing uvicorn configuration, and adding proper health checks, you can create reliable, efficient container images. The patterns shown in this documentation provide a solid foundation for deploying FastAPI applications at scale while maintaining the flexibility needed for different environments. Always remember to test your Docker setup in staging before production deployment, and monitor container behavior using the observability tools recommended in sections 33 and 34.