# Dependency Injection Patterns

## What is Dependency Injection?

Dependency Injection (DI) is a design pattern that implements Inversion of Control for resolving dependencies. Instead of an object creating or looking up its dependencies, they are provided (injected) by an external entity, typically the IoC container.

DI makes code more modular, testable, and maintainable by reducing coupling between components. A class declares what it needs rather than how to obtain it, following the principle of programming to interfaces rather than implementations.

## Types of Dependency Injection

Spring supports three primary injection types: constructor injection, setter injection, and field injection. Each has specific use cases and trade-offs.

### Constructor Injection

Constructor injection provides dependencies through class constructors. This is the recommended approach for required dependencies because it ensures that objects are fully initialized before use and enables immutability.

```java
@Service
public class OrderService {

    private final OrderRepository orderRepository;
    private final PaymentService paymentService;
    private final NotificationService notificationService;

    @Autowired  // Optional in Spring 4.3+ if only one constructor
    public OrderService(OrderRepository orderRepository,
                       PaymentService paymentService,
                       NotificationService notificationService) {
        this.orderRepository = orderRepository;
        this.paymentService = paymentService;
        this.notificationService = notificationService;
    }

    public Order createOrder(OrderRequest request) {
        Order order = new Order(request);
        orderRepository.save(order);
        paymentService.processPayment(order);
        notificationService.sendConfirmation(order);
        return order;
    }
}
```

**Advantages**:
- Dependencies are required and cannot be null
- Enables immutability with `final` fields
- Makes dependencies explicit and visible
- Better for unit testing (can instantiate without container)
- Prevents circular dependencies at compile time

**When to Use**: Always prefer constructor injection for mandatory dependencies. It's the most robust pattern and aligns with modern Spring best practices.

This pattern is similar to dependency injection in FastAPI:

```python
class OrderService:
    def __init__(self,
                 order_repository: OrderRepository,
                 payment_service: PaymentService,
                 notification_service: NotificationService):
        self.order_repository = order_repository
        self.payment_service = payment_service
        self.notification_service = notification_service
```

### Setter Injection

Setter injection provides dependencies through setter methods after object construction. Use this for optional dependencies or when you need to reconfigure a bean after instantiation.

```java
@Service
public class ReportService {

    private ReportRepository reportRepository;
    private EmailService emailService;  // Optional dependency
    private int maxRetries = 3;  // Default value

    @Autowired
    public void setReportRepository(ReportRepository reportRepository) {
        this.reportRepository = reportRepository;
    }

    @Autowired(required = false)  // Optional dependency
    public void setEmailService(EmailService emailService) {
        this.emailService = emailService;
    }

    @Value("${report.max-retries:3}")
    public void setMaxRetries(int maxRetries) {
        this.maxRetries = maxRetries;
    }

    public Report generateReport(String type) {
        Report report = reportRepository.generate(type);

        if (emailService != null) {
            emailService.sendReport(report);
        }

        return report;
    }
}
```

**Advantages**:
- Supports optional dependencies with `@Autowired(required = false)`
- Allows reconfiguration after construction
- Enables circular dependencies (though this is usually a design smell)
- Works with JMX managed beans that need runtime reconfiguration

**Disadvantages**:
- Dependencies can be null if not properly configured
- Cannot make fields `final`
- Less clear which dependencies are required
- More verbose than constructor injection

**When to Use**: Use setter injection for optional dependencies or when working with legacy code that requires reconfiguration. For new code, prefer constructor injection.

### Field Injection

Field injection uses `@Autowired` directly on fields, eliminating constructors and setters. While concise, it's generally discouraged.

```java
@Service
public class UserService {

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private PasswordEncoder passwordEncoder;

    public User createUser(String username, String password) {
        User user = new User(username);
        user.setPassword(passwordEncoder.encode(password));
        return userRepository.save(user);
    }
}
```

**Advantages**:
- Very concise, minimal boilerplate
- Quick to write for prototypes

**Disadvantages**:
- Cannot make fields `final` (mutability concerns)
- Dependencies hidden from API (violates encapsulation)
- Requires Spring container for testing (can't instantiate with `new`)
- Harder to see required dependencies at a glance
- Encourages too many dependencies (violates SRP)
- Cannot detect circular dependencies until runtime

**When to Use**: Avoid in production code. May be acceptable for quick prototypes or tests where conciseness matters more than maintainability.

## Advanced Injection Patterns

### Method Injection

Spring can inject dependencies into arbitrary methods, not just setters:

```java
@Service
public class DataProcessor {

    private DataValidator validator;
    private DataTransformer transformer;

    @Autowired
    public void configureProcessing(DataValidator validator,
                                   DataTransformer transformer) {
        this.validator = validator;
        this.transformer = transformer;
    }

    public ProcessedData process(RawData data) {
        validator.validate(data);
        return transformer.transform(data);
    }
}
```

This is functionally equivalent to setter injection but can set multiple dependencies in one method call.

### Lookup Method Injection

When a singleton bean needs a new instance of a prototype bean for each operation, Spring can inject a method that returns a new instance:

```java
@Component
public abstract class CommandProcessor {

    public void processCommand(String command) {
        CommandHandler handler = createCommandHandler();  // New instance each time
        handler.handle(command);
    }

    @Lookup
    protected abstract CommandHandler createCommandHandler();
}

@Component
@Scope("prototype")
public class CommandHandler {
    public void handle(String command) {
        // Handle command
    }
}
```

Spring implements the abstract method at runtime using CGLIB, returning a new prototype instance each time.

### Arbitrary Method Replacement

Spring can replace method implementations at runtime using `MethodReplacer`:

```java
public class CalculatorImpl implements Calculator {
    public int add(int a, int b) {
        return a + b;
    }
}

public class AdditionReplacer implements MethodReplacer {
    @Override
    public Object reimplement(Object obj, Method method, Object[] args) {
        int a = (int) args[0];
        int b = (int) args[1];
        System.out.println("Adding " + a + " and " + b);
        return a + b;  // Could modify behavior here
    }
}
```

This advanced feature is rarely needed in modern applications. AOP provides a cleaner solution for most cross-cutting concerns.

## Qualifier-Based Injection

When multiple beans of the same type exist, use `@Qualifier` to specify which to inject:

```java
@Configuration
public class DataSourceConfig {

    @Bean
    @Qualifier("primaryDataSource")
    public DataSource primaryDataSource() {
        return new HikariDataSource();
    }

    @Bean
    @Qualifier("secondaryDataSource")
    public DataSource secondaryDataSource() {
        return new HikariDataSource();
    }
}

@Service
public class UserService {

    private final DataSource dataSource;

    @Autowired
    public UserService(@Qualifier("primaryDataSource") DataSource dataSource) {
        this.dataSource = dataSource;
    }
}
```

Spring also supports JSR-330's `@Named` annotation for qualification:

```java
import javax.inject.Inject;
import javax.inject.Named;

@Service
public class UserService {

    @Inject
    public UserService(@Named("primaryDataSource") DataSource dataSource) {
        this.dataSource = dataSource;
    }
}
```

### Primary Beans

Mark one bean as `@Primary` to make it the default when multiple candidates exist:

```java
@Bean
@Primary
public DataSource primaryDataSource() {
    return new HikariDataSource();
}

@Bean
public DataSource secondaryDataSource() {
    return new HikariDataSource();
}

// Automatically gets primaryDataSource without @Qualifier
@Autowired
public UserService(DataSource dataSource) {
    this.dataSource = dataSource;
}
```

## Collection Injection

Spring can inject all beans of a type into a collection:

```java
public interface MessageHandler {
    void handle(Message message);
}

@Component
public class EmailHandler implements MessageHandler {
    public void handle(Message message) { /* ... */ }
}

@Component
public class SmsHandler implements MessageHandler {
    public void handle(Message message) { /* ... */ }
}

@Service
public class MessageService {

    private final List<MessageHandler> handlers;

    @Autowired
    public MessageService(List<MessageHandler> handlers) {
        this.handlers = handlers;
    }

    public void processMessage(Message message) {
        handlers.forEach(handler -> handler.handle(message));
    }
}
```

This pattern is similar to FastAPI's dependency injection for lists:

```python
handlers: List[MessageHandler] = Depends(get_all_handlers)
```

You can also inject `Set<T>` for unique handlers or `Map<String, T>` where keys are bean names:

```java
@Autowired
public MessageService(Map<String, MessageHandler> handlers) {
    this.handlers = handlers;
}
```

## Conditional Injection

Spring Boot provides `@ConditionalOnProperty`, `@ConditionalOnBean`, and similar annotations for conditional bean creation:

```java
@Configuration
public class CacheConfig {

    @Bean
    @ConditionalOnProperty(name = "cache.type", havingValue = "redis")
    public CacheManager redisCacheManager() {
        return new RedisCacheManager();
    }

    @Bean
    @ConditionalOnProperty(name = "cache.type", havingValue = "caffeine")
    public CacheManager caffeineCacheManager() {
        return new CaffeineCacheManager();
    }

    @Bean
    @ConditionalOnMissingBean(CacheManager.class)
    public CacheManager defaultCacheManager() {
        return new NoOpCacheManager();
    }
}
```

## Generic Injection

Spring can inject generically typed beans with full type information:

```java
@Component
public class StringRepository extends Repository<String> { }

@Component
public class IntegerRepository extends Repository<Integer> { }

@Service
public class StringService {

    @Autowired
    private Repository<String> repository;  // Gets StringRepository
}

@Service
public class IntegerService {

    @Autowired
    private Repository<Integer> repository;  // Gets IntegerRepository
}
```

## Lazy Injection

Defer dependency resolution until first use with `@Lazy`:

```java
@Service
public class HeavyService {

    private final ExpensiveComponent component;

    @Autowired
    public HeavyService(@Lazy ExpensiveComponent component) {
        this.component = component;  // Proxy injected, not actual instance
    }

    public void performOperation() {
        component.doWork();  // Actual instance created here on first call
    }
}
```

This is useful for breaking circular dependencies or deferring expensive initialization.

## Best Practices

**Prefer Constructor Injection**: Use constructor injection for required dependencies. It promotes immutability and makes testing easier.

**Use Setter Injection Sparingly**: Reserve setter injection for optional dependencies or reconfigurable beans.

**Avoid Field Injection**: Don't use field injection in production code. It harms testability and maintainability.

**Keep Dependencies Minimal**: If a class needs many dependencies, it may violate the Single Responsibility Principle. Consider refactoring.

**Program to Interfaces**: Inject interface types, not concrete implementations. This allows swapping implementations without changing dependents.

**Use `@Qualifier` Judiciously**: Too many qualifiers may indicate poor naming or too many beans of the same type.

**Leverage `@Primary`**: When one implementation is the default choice, mark it `@Primary` to reduce qualifier annotations elsewhere.

These patterns ensure your Spring applications remain maintainable, testable, and aligned with SOLID principles.
