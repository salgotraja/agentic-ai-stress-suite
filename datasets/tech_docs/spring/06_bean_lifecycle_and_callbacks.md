# Bean Lifecycle and Callbacks

Spring Framework provides a robust mechanism for managing the lifecycle of beans, enabling developers to customize behavior during initialization and destruction phases. Beans in Spring are not just static objects—they evolve through distinct lifecycle stages, from instantiation to resource cleanup. Understanding these phases and the callbacks available is critical for managing dependencies, initializing resources, and ensuring proper cleanup in enterprise applications. This document explores Spring’s bean lifecycle in depth, covering standard interfaces, annotations, use cases, and production-ready patterns.

---

## Lifecycle Phases Overview

Spring’s bean lifecycle consists of four core phases:

1. **Instantiation**: The container creates the bean instance using reflection or factory methods.
2. **Property Population**: Dependencies are injected via constructor or setter injection.
3. **Initialization**: Custom initialization logic is executed via callback methods.
4. **Destruction**: Cleanup logic is executed when the bean is removed from the container.

Initialization and destruction are the focus of lifecycle callbacks. These phases allow developers to hook into the container’s behavior for tasks like establishing database connections, loading configuration files, or releasing resources.

---

## Lifecycle Callback Interfaces

Spring provides two marker interfaces for lifecycle management:

### `InitializingBean` and `DisposableBean`

The `InitializingBean` interface defines a `afterPropertiesSet()` method, invoked after property injection. `DisposableBean` defines a `destroy()` method, called before the bean is removed from the container.

#### Example: Interface-Based Callbacks
```java
import org.springframework.beans.factory.DisposableBean;
import org.springframework.beans.factory.InitializingBean;

public class DataSourceBean implements InitializingBean, DisposableBean {
    private String jdbcUrl;

    public void setJdbcUrl(String jdbcUrl) {
        this.jdbcUrl = jdbcUrl;
    }

    @Override
    public void afterPropertiesSet() throws Exception {
        // Initialization logic
        System.out.println("Initializing data source: " + jdbcUrl);
        // Open database connection
    }

    @Override
    public void destroy() throws Exception {
        // Cleanup logic
        System.out.println("Closing data source: " + jdbcUrl);
        // Close database connection
    }
}
```

#### When to Use Interfaces
- **Legacy applications** where annotations are not feasible.
- **Frameworks** that enforce strict separation between bean logic and lifecycle management.

#### Drawbacks
- **Tight coupling**: Implementing these interfaces binds the bean to Spring APIs, reducing testability and reusability.
- **Limited flexibility**: Cannot specify custom method names; callbacks are hardcoded in the interface.

---

## Annotation-Based Callbacks

Spring recommends using `@PostConstruct` and `@PreDestroy` annotations for lifecycle callbacks. These annotations decouple lifecycle logic from bean interfaces, promoting cleaner designs.

#### Example: Annotation-Based Callbacks
```java
import javax.annotation.PostConstruct;
import javax.annotation.PreDestroy;

public class CacheManager {
    private String cacheName;

    public void setCacheName(String cacheName) {
        this.cacheName = cacheName;
    }

    @PostConstruct
    public void init() {
        System.out.println("Initializing cache: " + cacheName);
        // Load data into cache
    }

    @PreDestroy
    public void destroy() {
        System.out.println("Clearing cache: " + cacheName);
        // Release cached resources
    }
}
```

#### When to Use Annotations
- **Modern Spring applications** where separation of concerns is prioritized.
- **Beans requiring multiple lifecycle methods** (e.g., `@PostConstruct` for setup and custom methods for validation).

#### Key Notes
- Methods annotated with `@PostConstruct` must be **public**, **protected**, or have default visibility but **not private**.
- Exceptions in `@PostConstruct` prevent the bean from being registered, while exceptions in `@PreDestroy` are generally ignored.

---

## Declaration in Configuration

Lifecycle callbacks can also be declared explicitly in Java configuration using the `@Bean` annotation.

#### Example: Java Configuration
```java
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

@Configuration
public class AppConfig {
    @Bean(initMethod = "init", destroyMethod = "release")
    public CacheManager cacheManager() {
        return new CacheManager();
    }
}
```

#### Custom Method Names
Unlike annotations, Java configuration allows specifying **custom method names** for initialization and destruction. This is useful when legacy code requires backward compatibility.

#### XML Configuration (Legacy)
For historical reference, XML configuration supports lifecycle methods similarly:
```xml
<bean id="dataSource" class="com.example.DataSourceBean" 
      init-method="initDataSource" destroy-method="closeDataSource"/>
```

---

## Execution Order of Callbacks

Spring guarantees the following execution order when multiple callbacks are present:

1. `@PostConstruct` methods
2. `afterPropertiesSet()` from `InitializingBean`
3. Custom `init-method` from `@Bean` or XML
4. Destruction callbacks follow the reverse order during shutdown.

#### Example: Mixed Callbacks
```java
public class MultiCallbackBean implements InitializingBean {
    @PostConstruct
    public void annotatedInit() {
        System.out.println("PostConstruct method");
    }

    public void customInit() {
        System.out.println("Custom init-method");
    }

    @Override
    public void afterPropertiesSet() {
        System.out.println("InitializingBean callback");
    }
}
```

**Output**:
```
PostConstruct method
InitializingBean callback
Custom init-method
```

This order ensures predictable behavior, but relying on it for dependencies between callbacks is discouraged. For complex orchestration, consider using `@DependsOn` or event listeners.

---

## Best Practices for Production-Ready Applications

1. **Prefer `@PostConstruct` and `@PreDestroy`** over `InitializingBean` and `DisposableBean` for better decoupling.
2. **Use Java configuration** for explicit control over lifecycle methods.
3. **Avoid heavy processing** in `@PostConstruct`. If necessary, offload to a separate thread or use `@Async`.
4. **Always close resources** in `@PreDestroy`, including file handles, database connections, and background threads.
5. **Validate dependencies** in `@PostConstruct` rather than relying on null checks during normal operations.

#### Example: Thread Management
```java
public class BackgroundTaskManager {
    private volatile boolean running = false;
    private Thread backgroundThread;

    @PostConstruct
    public void startTask() {
        backgroundThread = new Thread(() -> {
            while (running) {
                // Perform periodic task
            }
        });
        running = true;
        backgroundThread.start();
    }

    @PreDestroy
    public void stopTask() {
        running = false;
        backgroundThread.interrupt();
    }
}
```

---

## Common Pitfalls and Troubleshooting

### 1. **Callback Not Invoked**
- **Cause**: Bean is created outside Spring context (e.g., `new MyBean()`).
- **Fix**: Ensure beans are managed by the Spring container.

### 2. **Incorrect Method Visibility**
- **Cause**: `@PostConstruct` method is private.
- **Fix**: Change method to `public` or `protected`.

### 3. **Prototype Scope and Destruction**
- **Cause**: Prototype beans are not tracked by Spring after creation.
- **Fix**: Use `SmartLifecycle` or manually invoke destruction logic.

### 4. **Exceptions in `@PostConstruct`**
- **Cause**: Unhandled exceptions prevent bean registration.
- **Fix**: Implement retry logic or use `@Recover` from Resilience4j.

---

## Cross-Framework Comparison

| Feature                  | Spring Framework            | Java EE / Jakarta EE        | .NET Core                |
|--------------------------|-----------------------------|-----------------------------|--------------------------|
| Initialization Callback | `@PostConstruct`            | `@PostConstruct`            | `IStartup.Configure`     |
| Destruction Callback    | `@PreDestroy`               | `@PreDestroy`               | `IDisposable.Dispose`    |
| Configuration Style       | Java/XML/Annotations        | XML/Annotations             | Fluent API/Attributes    |

Spring’s annotation-based model is more flexible for Java applications, while .NET Core emphasizes composition over configuration.

---

## Real-World Use Cases

1. **Caching Layer Initialization**
   - Load cached data from disk in `@PostConstruct`.
   - Persist dirty data in `@PreDestroy`.

2. **External Service Integration**
   - Establish connection pools in `@PostConstruct`.
   - Gracefully terminate connections in `@PreDestroy`.

3. **Event-Driven Architecture**
   - Subscribe to message queues during initialization.
   - Unsubscribe and flush pending messages during shutdown.

---

## Conclusion

Mastering Spring’s bean lifecycle callbacks is essential for building robust, scalable applications. By leveraging annotations like `@PostConstruct` and `@PreDestroy`, developers can decouple business logic from infrastructure concerns while ensuring proper resource management. This documentation has covered the core concepts, practical examples, and production considerations for lifecycle callbacks. For further reading, refer to the [Dependency Injection](05) and [Configuration](config) sections for advanced integration patterns.