# Bean Scopes and Lifecycle

## Understanding Bean Scopes

Bean scope determines the lifecycle and visibility of bean instances within the container. Spring provides several scopes that control when beans are created, how long they live, and how they're shared across the application.

Choosing the appropriate scope is critical for application performance, memory management, and correctness. Using the wrong scope can lead to subtle bugs, memory leaks, or unnecessary object creation.

## Core Bean Scopes

Spring Framework defines six scopes, though four are available only in web-aware ApplicationContext implementations.

### Singleton Scope

The singleton scope is Spring's default. The container creates exactly one instance of the bean per Spring IoC container. All requests for that bean return the same shared instance.

```java
@Component
@Scope("singleton")  // Explicit, but optional since it's default
public class UserRepository {

    private final DataSource dataSource;

    @Autowired
    public UserRepository(DataSource dataSource) {
        this.dataSource = dataSource;
    }

    public User findById(Long id) {
        // Repository logic
    }
}
```

**Characteristics**:
- One instance per container
- Created when container starts (unless lazy-initialized)
- Thread-safe concerns: Spring doesn't make singletons thread-safe; you must ensure thread safety
- Stateless beans are ideal candidates
- Most Spring beans should be singletons

**Important**: Spring's singleton is different from the Gang of Four singleton pattern. GoF singleton creates one instance per ClassLoader, while Spring creates one instance per container. Multiple Spring containers can exist in the same JVM, each with its own singleton instances.

**Thread Safety Considerations**:

```java
@Service
public class OrderService {

    // Shared state in singleton - UNSAFE!
    private Order currentOrder;

    public void processOrder(Order order) {
        this.currentOrder = order;  // Race condition!
        // Multiple threads can overwrite this
    }
}
```

Fix by removing shared mutable state:

```java
@Service
public class OrderService {

    private final OrderRepository orderRepository;

    @Autowired
    public OrderService(OrderRepository orderRepository) {
        this.orderRepository = orderRepository;
    }

    public void processOrder(Order order) {
        // Use method parameters or local variables
        Order savedOrder = orderRepository.save(order);
        // Thread-safe: no shared mutable state
    }
}
```

### Prototype Scope

Prototype scope creates a new bean instance every time the bean is requested. Spring doesn't manage the complete lifecycle of prototype beans; the container instantiates, configures, and hands them to the client, then has no further record of them.

```java
@Component
@Scope("prototype")
public class ShoppingCart {

    private List<CartItem> items = new ArrayList<>();

    public void addItem(CartItem item) {
        items.add(item);
    }

    public List<CartItem> getItems() {
        return items;
    }
}
```

**Characteristics**:
- New instance on every request
- No destruction callbacks called (container doesn't track instances)
- Client code responsible for cleanup
- Useful for stateful objects
- Higher memory overhead

**Usage Example**:

```java
@Service
public class ShoppingService {

    @Autowired
    private ApplicationContext context;

    public ShoppingCart createCart() {
        // New instance each time
        return context.getBean(ShoppingCart.class);
    }
}
```

**Prototype with Singleton Injection Issue**:

When a singleton bean has a prototype dependency, the prototype is only created once during singleton initialization:

```java
@Service  // Singleton
public class OrderProcessor {

    @Autowired
    private ShoppingCart cart;  // Prototype - but only injected ONCE!

    // All method calls use the SAME cart instance
    public void process() {
        cart.addItem(new CartItem());  // Shared state!
    }
}
```

**Solutions**:

**1. Method Injection with `@Lookup`**:

```java
@Service
public abstract class OrderProcessor {

    public void process() {
        ShoppingCart cart = getShoppingCart();  // New instance each time
        cart.addItem(new CartItem());
    }

    @Lookup
    protected abstract ShoppingCart getShoppingCart();
}
```

**2. Inject ApplicationContext**:

```java
@Service
public class OrderProcessor {

    @Autowired
    private ApplicationContext context;

    public void process() {
        ShoppingCart cart = context.getBean(ShoppingCart.class);
        cart.addItem(new CartItem());
    }
}
```

**3. Inject ObjectProvider** (preferred in modern Spring):

```java
@Service
public class OrderProcessor {

    private final ObjectProvider<ShoppingCart> cartProvider;

    @Autowired
    public OrderProcessor(ObjectProvider<ShoppingCart> cartProvider) {
        this.cartProvider = cartProvider;
    }

    public void process() {
        ShoppingCart cart = cartProvider.getObject();  // New instance
        cart.addItem(new CartItem());
    }
}
```

## Web-Aware Scopes

Web-aware scopes are only available in web applications using Spring MVC or WebFlux.

### Request Scope

Creates one instance per HTTP request. The instance is destroyed when the request completes.

```java
@Component
@Scope(value = WebApplicationContext.SCOPE_REQUEST, proxyMode = ScopedProxyMode.TARGET_CLASS)
public class LoginTracker {

    private String username;
    private LocalDateTime loginTime = LocalDateTime.now();

    public void setUsername(String username) {
        this.username = username;
    }

    public String getUsername() {
        return username;
    }

    public Duration getSessionDuration() {
        return Duration.between(loginTime, LocalDateTime.now());
    }
}

@RestController
public class UserController {

    @Autowired
    private LoginTracker tracker;  // Proxied, different instance per request

    @PostMapping("/login")
    public void login(@RequestBody LoginRequest request) {
        tracker.setUsername(request.getUsername());
        // This tracker instance only lives for this request
    }

    @GetMapping("/session-time")
    public Duration getSessionTime() {
        return tracker.getSessionDuration();
    }
}
```

**ProxyMode**: Required when injecting request-scoped beans into singletons. Spring creates a proxy that delegates to the current request's bean instance.

This is similar to FastAPI's request-scoped dependencies:

```python
async def get_request_tracker(request: Request):
    tracker = LoginTracker()
    yield tracker

@app.post("/login")
async def login(tracker: LoginTracker = Depends(get_request_tracker)):
    tracker.username = request.username
```

### Session Scope

Creates one instance per HTTP session. The instance is destroyed when the session is invalidated.

```java
@Component
@Scope(value = WebApplicationContext.SCOPE_SESSION, proxyMode = ScopedProxyMode.TARGET_CLASS)
public class UserPreferences {

    private String theme = "light";
    private String language = "en";
    private List<String> recentSearches = new ArrayList<>();

    public void addSearch(String query) {
        recentSearches.add(0, query);
        if (recentSearches.size() > 10) {
            recentSearches.remove(10);
        }
    }

    // Getters and setters
}

@RestController
public class PreferencesController {

    @Autowired
    private UserPreferences preferences;

    @PostMapping("/preferences/theme")
    public void setTheme(@RequestParam String theme) {
        preferences.setTheme(theme);
        // Persisted for the user's entire session
    }

    @GetMapping("/preferences")
    public UserPreferences getPreferences() {
        return preferences;
    }
}
```

**Important**: Session-scoped beans serialize the session state, so all fields must be Serializable for distributed sessions.

### Application Scope

Creates one instance per ServletContext. Similar to singleton but shared across all servlets in a web application.

```java
@Component
@Scope(value = WebApplicationContext.SCOPE_APPLICATION, proxyMode = ScopedProxyMode.TARGET_CLASS)
public class ApplicationMetrics {

    private final AtomicLong requestCount = new AtomicLong(0);
    private final AtomicLong errorCount = new AtomicLong(0);

    public void recordRequest() {
        requestCount.incrementAndGet();
    }

    public void recordError() {
        errorCount.incrementAndGet();
    }

    public long getRequestCount() {
        return requestCount.get();
    }

    public long getErrorCount() {
        return errorCount.get();
    }
}
```

**When to Use**: Application scope is appropriate for servlet-level shared state. For most applications, singleton scope suffices.

### WebSocket Scope

Creates one instance per WebSocket session:

```java
@Component
@Scope(scopeName = "websocket", proxyMode = ScopedProxyMode.TARGET_CLASS)
public class WebSocketSession {

    private String sessionId;
    private Queue<String> messageQueue = new ConcurrentLinkedQueue<>();

    public void queueMessage(String message) {
        messageQueue.offer(message);
    }
}
```

## Bean Lifecycle

Understanding bean lifecycle helps in resource management, initialization, and cleanup.

### Lifecycle Phases

1. **Instantiation**: Container creates bean instance
2. **Population**: Dependencies are injected
3. **Bean Name Awareness**: If bean implements BeanNameAware, `setBeanName()` is called
4. **Bean Factory Awareness**: If bean implements BeanFactoryAware, `setBeanFactory()` is called
5. **Application Context Awareness**: If bean implements ApplicationContextAware, `setApplicationContext()` is called
6. **Pre-Initialization**: BeanPostProcessors' `postProcessBeforeInitialization()` runs
7. **Initialization**: `@PostConstruct` methods run, then `InitializingBean.afterPropertiesSet()`, then custom init methods
8. **Post-Initialization**: BeanPostProcessors' `postProcessAfterInitialization()` runs
9. **Ready**: Bean is ready for use
10. **Destruction**: On container shutdown, `@PreDestroy` runs, then `DisposableBean.destroy()`, then custom destroy methods

### Initialization Callbacks

**@PostConstruct Annotation** (JSR-250):

```java
@Service
public class DataService {

    @Autowired
    private DataSource dataSource;

    @PostConstruct
    public void initialize() {
        // Called after dependency injection
        // Validate configuration, warm caches, etc.
        System.out.println("DataService initialized");
    }
}
```

**InitializingBean Interface**:

```java
@Service
public class DataService implements InitializingBean {

    @Override
    public void afterPropertiesSet() throws Exception {
        // Called after properties are set
        System.out.println("Properties set");
    }
}
```

**Custom Init Method**:

```java
@Configuration
public class AppConfig {

    @Bean(initMethod = "init")
    public DataService dataService() {
        return new DataService();
    }
}

public class DataService {
    public void init() {
        System.out.println("Custom init method called");
    }
}
```

**Order of Execution**: `@PostConstruct` → `afterPropertiesSet()` → custom init method

**Best Practice**: Use `@PostConstruct` for initialization logic. It's standard Java, doesn't couple code to Spring interfaces, and works with component scanning.

### Destruction Callbacks

**@PreDestroy Annotation**:

```java
@Service
public class DataService {

    @PreDestroy
    public void cleanup() {
        // Close resources, flush caches, etc.
        System.out.println("Cleaning up DataService");
    }
}
```

**DisposableBean Interface**:

```java
@Service
public class DataService implements DisposableBean {

    @Override
    public void destroy() throws Exception {
        System.out.println("Destroying DataService");
    }
}
```

**Custom Destroy Method**:

```java
@Bean(destroyMethod = "close")
public DataSource dataSource() {
    return new HikariDataSource();
}
```

**Automatic Destroy Method Inference**: Spring automatically calls `close()` or `shutdown()` methods if no explicit destroyMethod is specified and the bean has a public method with one of these names.

**Order of Execution**: `@PreDestroy` → `destroy()` → custom destroy method

**Important**: Destruction callbacks are NOT called for prototype-scoped beans. The container doesn't track prototype instances after creation.

### Lifecycle Awareness Interfaces

Implement awareness interfaces to access container infrastructure:

```java
@Component
public class ApplicationContextService implements ApplicationContextAware,
                                                  BeanNameAware,
                                                  BeanFactoryAware {

    private ApplicationContext applicationContext;
    private String beanName;
    private BeanFactory beanFactory;

    @Override
    public void setApplicationContext(ApplicationContext applicationContext) {
        this.applicationContext = applicationContext;
    }

    @Override
    public void setBeanName(String name) {
        this.beanName = name;
    }

    @Override
    public void setBeanFactory(BeanFactory beanFactory) {
        this.beanFactory = beanFactory;
    }

    public <T> T getBean(Class<T> type) {
        return applicationContext.getBean(type);
    }
}
```

**Modern Alternative**: Inject ApplicationContext directly:

```java
@Service
public class BeanProvider {

    private final ApplicationContext context;

    @Autowired
    public BeanProvider(ApplicationContext context) {
        this.context = context;
    }

    public <T> T getBean(Class<T> type) {
        return context.getBean(type);
    }
}
```

This approach is cleaner and doesn't require implementing interfaces.

## Choosing the Right Scope

**Singleton**: Default choice for stateless services, repositories, configuration
**Prototype**: Stateful objects, command objects, DTOs created frequently
**Request**: HTTP request-specific data, user input validation
**Session**: User session data, shopping carts, preferences
**Application**: Application-wide shared data, metrics, configuration

Always prefer the narrowest scope that satisfies requirements to minimize memory usage and avoid sharing state unnecessarily.
