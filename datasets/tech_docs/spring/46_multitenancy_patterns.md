# Multi-Tenancy Patterns

Multi-tenancy is a software architecture that allows a single instance of an application to serve multiple tenants or clients. Each tenant's data is logically isolated from others and remains secure, private, and independent. This pattern is widely used in Software as a Service (SaaS) applications and enterprise systems where efficient resource usage and scalability are essential.

In this document, we explore common multi-tenancy patterns such as **database-per-tenant**, **schema-per-tenant**, and **shared database**, along with **tenant isolation** and **tenant context** concepts. We’ll also provide code examples using the **Spring Framework**, including how to implement **data isolation** and manage **security context**. The content is tailored for senior engineers aiming to build production-grade multi-tenant systems.

---

## Core Multi-Tenancy Patterns

There are several strategies for implementing multi-tenancy, each with trade-offs in performance, complexity, and scalability.

### 1. Shared Database, Shared Schema

This pattern stores all tenants in a single database and schema. A **tenant identifier** (often a `tenant_id`) is added to each table to distinguish data.

```java
@Entity
public class Order {
    @Id
    private Long id;

    @Column(name = "tenant_id")
    private String tenantId;

    private String product;
    private BigDecimal amount;
}
```

#### Pros:

- Easy to manage and maintain
- Efficient use of database resources
- Centralized schema management

#### Cons:

- Risk of data leakage if isolation is not carefully managed
- Query performance may degrade with large tenant sets
- Schema changes require coordination across all tenants

#### Use Cases:

- Tenants with simple data models and minimal isolation needs
- Applications where performance is not a bottleneck

---

### 2. Schema-per-Tenant

In this pattern, each tenant has its own schema within a single database. The schema acts as a container for all objects related to a tenant.

```sql
CREATE SCHEMA TenantA;
CREATE TABLE TenantA.Order (
    id BIGINT PRIMARY KEY,
    product VARCHAR(100),
    amount DECIMAL(10,2)
);
```

#### Pros:

- Strong isolation between tenants
- Easier to manage backups and schema upgrades per tenant
- Allows for tenant-specific schema customizations

#### Cons:

- Increased complexity in managing multiple schemas
- Difficult to share common data across tenants
- Schema creation and management can be resource-intensive

#### Use Cases:

- Applications where schema customization per tenant is required
- Systems requiring strong isolation and auditability

---

### 3. Database-per-Tenant

Each tenant has its own fully isolated database instance. This pattern provides the highest level of isolation.

```sql
-- TenantA database
CREATE DATABASE TenantA;

-- TenantB database
CREATE DATABASE TenantB;
```

#### Pros:

- Maximum security and isolation
- Simplifies tenant-specific backups and restores
- Easier to scale horizontally by adding new databases

#### Cons:

- High operational overhead
- Expensive in terms of database licenses and storage
- Complex to manage in cloud environments

#### Use Cases:

- Financial applications where data isolation is critical
- Applications with strict regulatory compliance requirements

---

## Implementing Tenant Context in Spring

To support multi-tenancy in Spring, we must manage **tenant context** and ensure that all operations are scoped to the current tenant.

### 1. TenantContext Class

```java
public class TenantContext {
    private static final ThreadLocal<String> CONTEXT = new ThreadLocal<>();

    public static void setTenantId(String tenantId) {
        CONTEXT.set(tenantId);
    }

    public static String getTenantId() {
        return CONTEXT.get();
    }

    public static void clear() {
        CONTEXT.remove();
    }
}
```

This class uses a `ThreadLocal` to store the current tenant ID, which is set during the request lifecycle.

---

### 2. Interceptor or Filter to Set Tenant ID

In Spring MVC, you can use an interceptor to extract the tenant ID from the request (e.g., from a header or subdomain) and store it in `TenantContext`.

```java
@Component
public class TenantInterceptor implements HandlerInterceptor {

    @Override
    public boolean preHandle(HttpServletRequest request, HttpServletResponse response, Object handler) {
        String tenantId = request.getHeader("X-Tenant-ID");
        if (tenantId == null) {
            throw new IllegalArgumentException("Tenant ID is required");
        }
        TenantContext.setTenantId(tenantId);
        return true;
    }

    @Override
    public void afterCompletion(HttpServletRequest request, HttpServletResponse response, Object handler, Exception ex) {
        TenantContext.clear();
    }
}
```

Add the interceptor to your configuration:

```java
@Configuration
@EnableWebMvc
public class WebConfig implements WebMvcConfigurer {

    @Autowired
    private TenantInterceptor tenantInterceptor;

    @Override
    public void addInterceptors(InterceptorRegistry registry) {
        registry.addInterceptor(tenantInterceptor);
    }
}
```

---

## Data Isolation with Spring Data

Spring Data allows us to add filters or custom repository implementations to enforce data isolation.

### 1. Using a Query Filter

```java
@NoRepositoryBean
public interface OrderRepositoryCustom<T, ID extends Serializable> extends JpaRepository<T, ID> {
}

public interface OrderRepository extends JpaRepository<Order, Long>, OrderRepositoryCustom<Order, Long> {
}

public class OrderRepositoryImpl implements OrderRepositoryCustom<Order, Long> {

    @PersistenceContext
    private EntityManager entityManager;

    @Override
    public List<Order> findAll() {
        String tenantId = TenantContext.getTenantId();
        return entityManager.createQuery("SELECT o FROM Order o WHERE o.tenantId = :tenantId")
                .setParameter("tenantId", tenantId)
                .getResultList();
    }
}
```

This ensures that all queries are scoped to the current tenant.

---

### 2. Using Spring Data Specifications

For more complex filtering, use `@Where` clauses or `Specification<T>`.

```java
public class OrderSpecifications {

    public static <T> Specification<Order> byTenantId() {
        return (root, query, cb) -> {
            String tenantId = TenantContext.getTenantId();
            return cb.equal(root.get("tenantId"), tenantId);
        };
    }
}
```

Usage in service:

```java
public interface OrderService {
    List<Order> findOrdersByTenant();
}

@Service
public class OrderServiceImpl implements OrderService {

    @Autowired
    private OrderRepository orderRepository;

    @Override
    public List<Order> findOrdersByTenant() {
        return orderRepository.findAll(OrderSpecifications.byTenantId());
    }
}
```

---

## Schema Switching in Spring

For schema-per-tenant, Spring can be configured to dynamically change the default schema based on the current tenant.

### 1. Dynamic DataSource Configuration

```java
@Configuration
@EnableJpaRepositories(
    basePackages = "com.example.repository",
    entityManagerFactoryRef = "entityManagerFactory",
    transactionManagerRef = "transactionManager"
)
public class MultiTenantConfig {

    @Bean
    public DataSource dataSource() {
        return new AbstractRoutingDataSource() {
            @Override
            protected Object determineCurrentLookupKey() {
                return TenantContext.getTenantId();
            }
        };
    }

    @Bean
    public LocalContainerEntityManagerFactoryBean entityManagerFactory(
            ObjectProvider<JpaPropertySource> jpaPropertySource,
            DataSource dataSource) {

        LocalContainerEntityManagerFactoryBean factory = new LocalContainerEntityManagerFactoryBean();
        factory.setDataSource(dataSource);
        factory.setJpaPropertyMap(jpaPropertySource.getIfUnique().toProperties());
        factory.setPackagesToScan("com.example.model");
        factory.setPersistenceUnitName("multiTenantPU");

        return factory;
    }
}
```

The `AbstractRoutingDataSource` selects the appropriate schema based on the `TenantContext`.

---

## Best Practices

1. **Always Clear the Tenant Context**: Ensure `TenantContext.clear()` is called after each request to avoid stale or leaked tenant IDs, especially in asynchronous or multi-threaded environments.

2. **Never Hardcode Tenant IDs**: Use interceptors, filters, or AOP for setting tenant IDs based on request context.

3. **Audit and Logging**: Include the tenant ID in logs and audit trails to help with debugging and compliance.

4. **Avoid Shared Data**: Be cautious when using shared data (e.g., lookup tables) across tenants. Consider using shared schema models or external services.

5. **Use Database-Level Constraints**: Where possible, enforce tenant isolation at the database level using schema permissions or row-level security (RLS) features like those found in PostgreSQL.

6. **Schema Management**: Use migration tools like Flyway or Liquibase to manage schema changes per tenant. With schema-per-tenant, ensure migrations are applied to all schemas.

---

## Cross-Platform Considerations

| Pattern              | Spring Data Support | Performance | Isolation | Migration Complexity |
|----------------------|---------------------|-------------|-----------|----------------------|
| Shared Schema        | ✅ Full support     | High        | Low       | Low                  |
| Schema-per-Tenant    | ✅ With routing     | Medium      | Medium    | Medium               |
| Database-per-Tenant  | ⚠️ Requires routing | Low         | High      | High                 |

---

## Common Pitfalls and Troubleshooting

### 1. Forgotten Tenant Context

If the tenant ID is not set or cleared properly, queries might return data from an arbitrary tenant.

**Symptoms**: Data inconsistency between users, missing data, or duplicate entries.

**Fix**: Ensure interceptors or AOP consistently set and clear the tenant ID.

### 2. Schema Switching Failures

When using `AbstractRoutingDataSource`, incorrect lookup keys may result in schema not found errors.

**Symptoms**: `SchemaNotFoundException` or `No suitable driver` errors.

**Fix**: Ensure the tenant ID is correctly mapped to a valid schema or database name.

### 3. Schema Locking on Startup

With schema-per-tenant and migrations, you may encounter schema migration locks if multiple instances start at the same time.

**Fix**: Use a lock table in a shared schema or external coordination service like ZooKeeper or etcd.

---

## Real-World Use Cases

1. **SaaS E-commerce Platforms**: Use schema-per-tenant for strong isolation between merchants while sharing common features like payment gateways or inventory.

2. **Financial Systems**: Use database-per-tenant for compliance, especially in industries like banking where data isolation is mandated.

3. **CRM Applications**: Shared schema with tenant ID filtering is often used for performance. Additional row-level security may be added for sensitive data.

---

## Conclusion

Multi-tenancy is a powerful architectural pattern that enables efficient, scalable, and secure delivery of applications to multiple clients. The key to success lies in choosing the right multi-tenancy model based on business and technical requirements, and implementing robust tenant isolation and context management in your framework of choice.

Using Spring and its ecosystem, you can build production-ready multi-tenant applications that balance performance, security, and maintainability. Always consider the trade-offs between isolation, complexity, and performance when selecting your pattern and ensure that data isolation is enforced at every level of your application.