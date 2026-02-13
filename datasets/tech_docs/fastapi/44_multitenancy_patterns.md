# Multi-Tenancy Patterns in FastAPI

Multi-tenancy is a critical architectural pattern for building scalable, secure, and maintainable SaaS (Software-as-a-Service) applications. It enables a single application instance to serve multiple tenants—customers or organizations—while ensuring data isolation and separation. FastAPI, with its high performance and async capabilities, is well-suited for implementing multi-tenancy, but requires careful design to balance isolation, scalability, and operational complexity. This documentation explores two primary patterns for multi-tenancy: **database-per-tenant** and **shared schema with tenant_id**, along with implementation strategies, code examples, and best practices for production systems.

---

## Core Concepts

### Tenant Isolation
Tenant isolation ensures that each tenant’s data and operations are logically or physically separated from others. This prevents data leakage and satisfies regulatory or compliance requirements. Isolation can be achieved through:
- **Database-level isolation**: Separate databases or schemas per tenant.
- **Application-level isolation**: Shared database with tenant identifiers (e.g., `tenant_id` in tables).

### Key Considerations
- **Security**: Unauthorized access to tenant data must be mitigated (see Security 10 for authentication/authorization strategies).
- **Scalability**: Choose a pattern that aligns with expected tenant growth and resource constraints.
- **Operational Overhead**: Database-per-tenant increases management complexity but offers stronger isolation.

---

## Database-per-Tenant Architecture

This approach assigns each tenant a dedicated database, ensuring strict isolation. It is ideal for scenarios requiring regulatory compliance (e.g., GDPR) or where tenants demand full data sovereignty.

### Implementation in FastAPI

1. **Database Connection Management**  
   Use a connection pool manager to dynamically select the tenant's database based on a tenant identifier (e.g., subdomain, API key). FastAPI's dependency injection system can centralize tenant identification logic.

   ```python
   from fastapi import Depends, FastAPI, HTTPException, Request
   from sqlalchemy import create_engine
   from sqlalchemy.orm import sessionmaker

   app = FastAPI()

   # Simulated tenant-to-database mapping (see Database 14 for production storage)
   TENANT_DATABASES = {
       "tenant_a": create_engine("postgresql://user:pass@localhost/tenant_a"),
       "tenant_b": create_engine("postgresql://user:pass@localhost/tenant_b"),
   }

   def get_tenant_db(request: Request):
       tenant_id = request.headers.get("X-Tenant-ID")
       if not tenant_id:
           raise HTTPException(status_code=403, detail="Tenant ID required")
       db_engine = TENANT_DATABASES.get(tenant_id)
       if not db_engine:
           raise HTTPException(status_code=404, detail="Tenant not found")
       return sessionmaker(bind=db_engine)()

   @app.get("/items/")
   def read_items(db: sessionmaker = Depends(get_tenant_db)):
       # Query tenant-specific database
       items = db.query(Item).all()
       return items
   ```

   **Notes**:
   - Store connection strings securely (e.g., encrypted in a config database—see Database 29).
   - Use async engines (`asyncpg` for PostgreSQL) to leverage FastAPI's async routes.

2. **When to Use**
   - Tenants require full data control (e.g., legal requirements).
   - High security demands where shared databases pose risks.

3. **Challenges**
   - Increased resource usage (each tenant has a dedicated database).
   - Complexity in backup/restore and schema migrations.

---

## Shared Schema with Tenant ID

In this pattern, all tenants share the same database schema, and data is isolated using a `tenant_id` column in every table. It balances performance and simplicity but requires rigorous query filtering.

### Implementation in FastAPI

1. **Model Design**  
   Add a `tenant_id` column to all relevant tables. Use SQLAlchemy's [mapped_column](https://docs.sqlalchemy.org/en/20/orm/mapping_styles.html) for type-safe definitions.

   ```python
   from sqlalchemy import Column, Integer, String, create_engine
   from sqlalchemy.ext.declarative import declarative_base

   Base = declarative_base()

   class Item(Base):
       __tablename__ = "items"
       id = Column(Integer, primary_key=True)
       name = Column(String(50))
       tenant_id = Column(Integer, index=True)  # Critical for isolation
   ```

2. **Tenant Context Middleware**  
   Inject the tenant ID into requests using middleware. This avoids repetitive manual checks in routes.

   ```python
   from fastapi import FastAPI, Request, HTTPException, Depends
   from starlette.middleware.base import BaseHTTPMiddleware

   app = FastAPI()

   class TenantMiddleware(BaseHTTPMiddleware):
       async def dispatch(self, request: Request, call_next):
           tenant_id = request.headers.get("X-Tenant-ID")
           if not tenant_id:
               return JSONResponse(status_code=403, content={"detail": "Tenant ID required"})
           request.state.tenant_id = tenant_id  # Store for downstream use
           response = await call_next(request)
           return response

   app.add_middleware(TenantMiddleware)
   ```

3. **Query Filtering**  
   Use a dependency to enforce `tenant_id` filtering in database queries.

   ```python
   from fastapi import Depends, Request
   from sqlalchemy.orm import Session

   def get_db(request: Request):
       db = Session(bind=engine)  # See Database 14 for connection setup
       db.tenant_id = request.state.tenant_id
       return db

   @app.get("/items/")
   def read_items(db: Session = Depends(get_db)):
       items = db.query(Item).filter(Item.tenant_id == db.tenant_id).all()
       return items
   ```

   **Best Practice**: Use SQLAlchemy's [query filters](https://docs.sqlalchemy.org/en/20/orm/query.html) to automatically apply tenant isolation for all queries.

---

## Tenant Context and Data Isolation

### Dynamic Tenant Identification
Identify tenants using headers, subdomains, or URL paths. For example:

- **Headers**: `X-Tenant-ID: tenant_a` (requires secure validation—see Security 10).
- **Subdomains**: `tenant-a.example.com` (requires wildcard DNS and SSL).

```python
# Example: Extract tenant from subdomain
def get_tenant_from_subdomain(request: Request):
    host = request.headers.get("host", "")
    subdomain = host.split(".")[0]  # e.g., "tenant-a" from "tenant-a.example.com"
    if subdomain in VALID_TENANTS:
        return subdomain
    raise HTTPException(status_code=403, detail="Invalid tenant")
```

### Edge Cases
- **Invalid or missing tenant identifiers**: Return 403 or 404.
- **Tenant switching**: Validate permissions when a user requests to switch tenants (see Security 10 for role-based access).

---

## Best Practices

1. **Security**
   - Validate tenant identifiers against a trusted source (e.g., authenticated user session—see Security 10).
   - Use row-level security (RLS) in PostgreSQL to enforce isolation at the database level.

2. **Performance**
   - Index all `tenant_id` columns to accelerate filtering.
   - Cache tenant-specific data with Redis, using keyspaced by `tenant_id`.

3. **Operational Efficiency**
   - For shared schemas, use database sharding for horizontal scaling.
   - For database-per-tenant, automate schema migrations with tools like Alembic.

4. **Testing**
   - Write integration tests that verify tenant isolation (e.g., ensure Tenant A cannot access Tenant B's data).

---

## Troubleshooting and Common Pitfalls

### Data Leakage
- **Symptoms**: A tenant sees another tenant's data.
- **Fix**: Audit all queries to ensure `tenant_id` filtering is applied. Use automated tests to catch regressions.

### Connection Management
- **Issue**: Database-per-tenant can exhaust connection pools under high load.
- **Fix**: Use connection pooling libraries (e.g., `pgBouncer`) and limit tenant connections per database.

### Asynchronous Considerations
- **Async FastAPI routes**: Ensure tenant-specific database connections are thread-safe. Avoid global variables for tenant context.

---

## Comparisons and Alternatives

| Pattern                  | Pros                                  | Cons                                  |
|-------------------------|---------------------------------------|---------------------------------------|
| **Database-per-tenant** | Strong isolation, easier backups      | High cost, complex management         |
| **Shared schema**       | Cost-effective, simpler scaling       | Risk of data leakage if misconfigured |

A third approach, **schema-per-tenant**, groups tenant data under PostgreSQL schemas. This balances isolation and cost but introduces complexity in migrations and query routing.

---

## Real-World Use Cases

1. **SaaS Product Catalog**  
   A shared schema with `tenant_id` allows a single API to manage inventory for multiple retail chains.

2. **Financial Compliance Platforms**  
   Database-per-tenant ensures auditors can only access data for their assigned clients.

3. **Multi-Tenant Marketplaces**  
   Subdomain-based tenant identification (e.g., `acme.marketplace.com`) with shared schema and Redis caching.

---

## Conclusion

Multi-tenancy in FastAPI requires careful selection of isolation patterns and robust implementation of tenant context. Database-per-tenant offers strong isolation but increases operational overhead, while shared schemas are cost-effective but demand strict query discipline. By leveraging FastAPI's dependency injection, middleware, and SQLAlchemy's filtering capabilities, you can build scalable, secure multi-tenant systems. Always validate tenant identifiers, monitor for data leakage, and test thoroughly under load. For advanced scenarios, consider cross-referencing with Database 14 and 29 for connection management strategies and Security 10 for authentication best practices.