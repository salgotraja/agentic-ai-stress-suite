# IoC Container and Beans

## Understanding Inversion of Control

Inversion of Control (IoC) is a design principle where the control flow of a program is inverted compared to traditional procedural programming. Instead of application code controlling the instantiation and lifecycle of dependencies, a container or framework assumes this responsibility. This principle is also known as the Hollywood Principle: "Don't call us, we'll call you."

In Spring, the IoC container is responsible for instantiating, configuring, and assembling objects known as beans. The container reads configuration metadata, which can be expressed through XML, Java annotations, or Java code, to understand how to instantiate, configure, and assemble the beans in your application.

## The BeanFactory and ApplicationContext

Spring provides two fundamental container implementations:

**BeanFactory**: The simplest container providing basic IoC functionality. It instantiates beans lazily when `getBean()` is called. This interface defines the basic contract for a Spring container, including methods to retrieve beans by name, type, or both.

```java
BeanFactory factory = new XmlBeanFactory(new FileSystemResource("beans.xml"));
MyService service = (MyService) factory.getBean("myService");
```

**ApplicationContext**: A more feature-rich container that extends BeanFactory. It adds enterprise-specific functionality including:
- Eager bean initialization by default
- Automatic BeanPostProcessor and BeanFactoryPostProcessor registration
- Convenient MessageSource access for internationalization
- ApplicationEvent publication and listener registration
- Support for application-layer specific contexts like WebApplicationContext

In practice, ApplicationContext is preferred for all applications except those with severe memory constraints. The most commonly used implementations include:

```java
// Loads configuration from classpath
ApplicationContext context = new ClassPathXmlApplicationContext("applicationContext.xml");

// Loads configuration from file system
ApplicationContext context = new FileSystemXmlApplicationContext("/path/to/applicationContext.xml");

// Java-based configuration
ApplicationContext context = new AnnotationConfigApplicationContext(AppConfig.class);

// Web-aware context (automatically created by Spring MVC)
WebApplicationContext webContext = WebApplicationContextUtils
    .getWebApplicationContext(servletContext);
```

Modern Spring Boot applications typically don't instantiate ApplicationContext directly. The framework creates and manages it internally through `SpringApplication.run()`.

## Bean Definition and Metadata

A bean definition contains the information needed to create an object, called configuration metadata. This includes:

**Class**: The fully qualified class name of the bean
**Name/ID**: Unique identifier(s) for the bean
**Scope**: The scope of bean instances (singleton, prototype, etc.)
**Constructor arguments**: Dependencies required for instantiation
**Properties**: Dependencies and configuration values
**Autowiring mode**: How dependencies should be resolved
**Lazy initialization**: Whether the bean should be created on startup or on first access
**Initialization method**: Callback method called after properties are set
**Destruction method**: Callback method called before bean destruction

Here's an XML-based bean definition:

```xml
<bean id="userService"
      class="com.example.service.UserServiceImpl"
      scope="singleton"
      lazy-init="false"
      init-method="initialize"
      destroy-method="cleanup">
    <constructor-arg ref="userRepository"/>
    <property name="maxRetries" value="3"/>
    <property name="emailService" ref="emailService"/>
</bean>
```

The same configuration using Java-based configuration:

```java
@Configuration
public class AppConfig {

    @Bean(initMethod = "initialize", destroyMethod = "cleanup")
    public UserService userService(UserRepository userRepository) {
        UserServiceImpl service = new UserServiceImpl(userRepository);
        service.setMaxRetries(3);
        service.setEmailService(emailService());
        return service;
    }

    @Bean
    public EmailService emailService() {
        return new EmailServiceImpl();
    }
}
```

And with annotations directly on the class:

```java
@Service
@Scope("singleton")
@Lazy(false)
public class UserServiceImpl implements UserService {

    private final UserRepository userRepository;
    private EmailService emailService;
    private int maxRetries = 3;

    @Autowired
    public UserServiceImpl(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    @Autowired
    public void setEmailService(EmailService emailService) {
        this.emailService = emailService;
    }

    @Value("${user.service.max-retries:3}")
    public void setMaxRetries(int maxRetries) {
        this.maxRetries = maxRetries;
    }

    @PostConstruct
    public void initialize() {
        // Initialization logic
    }

    @PreDestroy
    public void cleanup() {
        // Cleanup logic
    }
}
```

## Bean Naming

Every bean has one or more identifiers that must be unique within the container. Beans typically have a single identifier, but if more are needed, extras are considered aliases.

In XML configuration, use `id` and/or `name` attributes. The `id` allows exactly one identifier, while `name` allows multiple comma, semicolon, or space-separated aliases.

If no explicit name or id is provided, Spring generates a unique name. However, explicit naming is required when referencing beans by name, such as with the `ref` element or Service Locator pattern lookup.

**Bean Naming Conventions**: Follow standard Java conventions for instance field names. Bean names start with lowercase letter and are camel-cased, such as `accountManager`, `accountService`, `userDao`, `loginController`, etc.

Annotation-based configuration uses the method name as the bean name by default:

```java
@Configuration
public class AppConfig {

    @Bean
    public UserRepository userRepository() {  // Bean name: "userRepository"
        return new JpaUserRepository();
    }

    @Bean(name = "primaryDataSource")  // Explicit name
    public DataSource dataSource() {
        return new HikariDataSource();
    }

    @Bean({"dataSource", "primaryDataSource"})  // Multiple aliases
    public DataSource anotherDataSource() {
        return new HikariDataSource();
    }
}
```

## Bean Instantiation

Spring can instantiate beans using several mechanisms:

**Constructor Instantiation**: The most common approach, equivalent to using the `new` operator:

```java
@Bean
public UserService userService() {
    return new UserServiceImpl();
}
```

**Static Factory Method**: When a class provides a static method that returns an instance:

```java
public class UserServiceFactory {
    public static UserService createUserService() {
        return new UserServiceImpl();
    }
}

// XML configuration
<bean id="userService"
      class="com.example.UserServiceFactory"
      factory-method="createUserService"/>

// Java configuration
@Bean
public UserService userService() {
    return UserServiceFactory.createUserService();
}
```

**Instance Factory Method**: When using a non-static factory method:

```java
public class ServiceFactory {
    public UserService createUserService() {
        return new UserServiceImpl();
    }
}

// XML configuration
<bean id="serviceFactory" class="com.example.ServiceFactory"/>
<bean id="userService"
      factory-bean="serviceFactory"
      factory-method="createUserService"/>

// Java configuration
@Bean
public ServiceFactory serviceFactory() {
    return new ServiceFactory();
}

@Bean
public UserService userService() {
    return serviceFactory().createUserService();
}
```

**FactoryBean**: Spring provides a `FactoryBean` interface for complex instantiation logic:

```java
public class UserServiceFactoryBean implements FactoryBean<UserService> {

    @Override
    public UserService getObject() throws Exception {
        UserServiceImpl service = new UserServiceImpl();
        // Complex initialization logic
        return service;
    }

    @Override
    public Class<?> getObjectType() {
        return UserService.class;
    }

    @Override
    public boolean isSingleton() {
        return true;
    }
}

@Configuration
public class AppConfig {
    @Bean
    public UserServiceFactoryBean userService() {
        return new UserServiceFactoryBean();
    }
}
```

When you request a bean named `userService`, you get the `UserService` instance produced by the factory. To get the factory bean itself, prefix the name with `&`: `context.getBean("&userService")`.

## Dependency Resolution Process

When the ApplicationContext is created, Spring follows this process:

1. **Container Creation**: The ApplicationContext is created and initialized with configuration metadata
2. **Bean Definitions**: Dependencies for each bean are expressed as properties, constructor arguments, or static-factory method arguments
3. **Dependency Injection**: When a bean is created, the container provides its dependencies
4. **Value Conversion**: String values from configuration are converted to actual property types using JavaBeans PropertyEditor framework
5. **Circular Dependencies**: Spring detects and can resolve circular dependencies for setter injection, but not constructor injection

The container validates the configuration of each bean as it's created, including verification that referenced beans exist. However, property values and dependencies aren't set until the bean is actually created.

**Singleton Beans**: Created when the container starts (unless marked lazy)
**Prototype Beans**: Created when requested
**Circular Dependencies**: When bean A requires bean B through constructor injection, and B requires A, Spring throws a BeanCurrentlyInCreationException

To resolve circular dependencies, use setter injection instead of constructor injection for at least one of the beans:

```java
@Service
public class ServiceA {
    private ServiceB serviceB;

    @Autowired
    public void setServiceB(ServiceB serviceB) {  // Setter injection
        this.serviceB = serviceB;
    }
}

@Service
public class ServiceB {
    private final ServiceA serviceA;

    @Autowired
    public ServiceB(ServiceA serviceA) {  // Constructor injection is fine here
        this.serviceA = serviceA;
    }
}
```

## Comparison to Other Frameworks

Spring's IoC container shares similarities with dependency injection in other frameworks:

**FastAPI (Python)**: Uses function dependencies and type hints for injection:
```python
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/users/")
def get_users(db: Session = Depends(get_db)):
    return db.query(User).all()
```

Spring achieves similar results with autowiring:
```java
@RestController
public class UserController {
    private final UserRepository userRepository;

    @Autowired
    public UserController(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    @GetMapping("/users")
    public List<User> getUsers() {
        return userRepository.findAll();
    }
}
```

**Angular (TypeScript)**: Uses constructor injection with type annotations:
```typescript
@Injectable()
export class UserService {
    constructor(private http: HttpClient) {}
}
```

Spring's approach is nearly identical in concept, though Java's annotations are more verbose.

The key advantage of Spring's IoC container over manual dependency management is testability. Dependencies can be easily mocked or stubbed:

```java
@Test
void testUserService() {
    UserRepository mockRepo = Mockito.mock(UserRepository.class);
    UserService service = new UserServiceImpl(mockRepo);

    when(mockRepo.findById(1L)).thenReturn(Optional.of(new User()));

    User user = service.getUser(1L);
    assertNotNull(user);
}
```

This pattern works identically to how you'd test FastAPI dependencies by overriding them in test contexts.
