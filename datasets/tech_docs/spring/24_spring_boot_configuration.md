# Spring Boot Configuration

Spring Boot provides a powerful and flexible mechanism for externalizing configuration using `application.properties` or `application.yml`. These configuration files allow developers to customize application behavior without modifying code, which is essential in enterprise environments where applications often need to adapt to different deployment environments (e.g., development, testing, staging, production).

---

## External Configuration Basics

In Spring Boot, the `Environment` abstraction is responsible for managing configuration data. This data can be sourced from multiple places, including:

- Command-line arguments
- JNDI attributes
- Java system properties
- OS environment variables
- `application.properties` or `application.yml` files
- `@PropertySource` annotations
- Configuration data bound to `@ConfigurationProperties`

The primary location for configuration is the `application.properties` or `application.yml` file located in the `src/main/resources` directory.

### Example: application.properties

```properties
app.name=MyApp
app.version=1.0.0
app.debug=true
```

### Example: application.yml

```yaml
app:
  name: MyApp
  version: 1.0.0
  debug: true
```

These examples demonstrate how configuration can be structured in either key=value or nested YAML format.

---

## Type-Safe Configuration with @ConfigurationProperties

While using `Environment` is straightforward, it becomes cumbersome when dealing with complex or nested properties. Spring Boot introduces `@ConfigurationProperties`, which allows developers to bind configuration properties to a strongly typed POJO.

### Example: Configuration Class

```java
@ConfigurationProperties(prefix = "app")
public class AppConfig {
    private String name;
    private String version;
    private boolean debug;

    // Getters and setters
}
```

### Example: Registration in Spring Boot

```java
@Configuration
@EnableConfigurationProperties(AppConfig.class)
public class AppConfigRegistrar {
}
```

### Example: Usage in a Service

```java
@Service
public class AppService {

    private final AppConfig appConfig;

    public AppService(AppConfig appConfig) {
        this.appConfig = appConfig;
    }

    public String getAppInfo() {
        return String.format("App Name: %s, Version: %s, Debug: %b",
                appConfig.getName(), appConfig.getVersion(), appConfig.isDebug());
    }
}
```

This pattern improves code readability and reduces boilerplate code. It also enables better IDE support and compile-time checks for configuration properties.

---

## Profiles

Spring Profiles allow configuration to vary between environments. You can activate a profile using the `spring.profiles.active` property.

### Example: Application-Specific Profiles

Create `application-dev.properties`, `application-prod.properties`, etc., in `src/main/resources`.

#### application-dev.properties

```properties
spring.datasource.url=jdbc:mysql://localhost:3306/myapp_dev
spring.datasource.username=dev_user
spring.datasource.password=dev_pass
```

#### application-prod.properties

```properties
spring.datasource.url=jdbc:mysql://prod-db:3306/myapp_prod
spring.datasource.username=prod_user
spring.datasource.password=prod_pass
```

To activate a profile:

```properties
spring.profiles.active=dev
```

Or via command line:

```bash
java -jar myapp.jar --spring.profiles.active=prod
```

Profiles are especially useful in cloud-native applications where environment-specific settings are required without rebuilding the application.

---

## Best Practices

1. **Use `@ConfigurationProperties` for complex configuration**:
   It provides strong typing, validation, and IDE support. Avoid direct access to `Environment` for large configuration structures.

2. **Keep configuration files consistent**:
   Stick to a single format (`.properties` or `.yml`) across projects. Mixing formats may lead to confusion and errors.

3. **Organize configuration by component**:
   Group related properties under a common prefix to improve readability and maintainability.

4. **Use profiles for environment-specific settings**:
   This avoids hard-coding sensitive or environment-dependent values in the main configuration file.

5. **Avoid hard-coding secrets in configuration**:
   Use externalized configuration, Vault integration, or Spring Cloud Config for secure secret management.

6. **Leverage default values**:
   Use `@Value` with fallback values to provide sensible defaults that can be overridden by external configuration.

7. **Validate configuration properties**:
   Add JSR-303 validation annotations like `@NotNull` or `@Min` to `@ConfigurationProperties` beans to catch invalid configuration early.

---

## Advanced Configuration Techniques

### Configuration with External Sources

Spring Boot supports loading configuration from external files outside the classpath. This is useful in production environments where configuration is managed separately.

#### Example: External Configuration File

Create a `config/application-prod.properties` file outside the JAR and run:

```bash
java -jar myapp.jar --spring.config.location=file:/path/to/config/
```

This allows you to change configuration without redeploying the application.

---

### Property Sources and Priority

Spring Boot defines a hierarchy for property sources, with earlier sources taking precedence. The order matters, especially when multiple sources define the same property.

The priority order (from highest to lowest) is:

1. Command-line arguments (`--key=value`)
2. OS environment variables
3. `application-{profile}.properties` or `application-{profile}.yml`
4. `application.properties` or `application.yml`
5. `@PropertySource` annotations
6. Default properties (defined via `SpringApplication.setDefaultProperties`)

Understanding this hierarchy is essential when debugging configuration issues.

---

## Cross-Profile Configuration with YAML

YAML supports multi-profile configuration within a single file by using the `spring.profiles` key.

```yaml
app:
  name: MyApp
  debug: false

spring:
  profiles:
    active: dev

---
app:
  debug: true
spring:
  profiles: dev

---
app:
  debug: false
spring:
  profiles: prod
```

This approach is useful when managing multiple profiles in a single file, reducing duplication.

---

## Troubleshooting and Common Pitfalls

1. **Profile not activated**:
   Ensure `spring.profiles.active` is set correctly. Check for typos in profile names and verify that the corresponding files exist.

2. **Property binding fails silently**:
   Use `@ConfigurationProperties` with `failFast = true` to catch binding errors early during startup.

3. **Using `@Value` with nested properties**:
   `@Value` does not support nested properties. Use `@ConfigurationProperties` instead for nested configuration.

4. **Misconfigured YAML indentation**:
   YAML relies on indentation to define structure. Incorrect indentation can cause parsing errors.

5. **Overriding configuration in tests**:
   Use `@TestPropertySource` to override properties for integration tests without affecting the main configuration.

---

## Security and Configuration Management

In production, it's best to externalize all sensitive configuration such as database credentials, API keys, and SSL certificates. Spring Boot supports integration with external configuration management tools like:

- **Spring Cloud Config**
- **HashiCorp Vault**
- **AWS Secrets Manager**

These tools help manage secrets in a secure and scalable way, especially in microservices architectures.

---

## Comparison with Manual Configuration

Before Spring Boot, developers used Spring’s `@PropertySource` and `Environment` API to manage configuration. While functional, this approach required boilerplate code and lacked integration with command-line arguments and system environment variables.

Spring Boot simplifies this by:

- Automatically loading `application.properties`
- Providing seamless integration with profiles
- Offering `@ConfigurationProperties` for type-safe configuration

Using Spring Boot’s configuration features makes applications easier to configure and maintain across different environments.

---

## Real-World Use Cases

### 1. Microservices Configuration Management

In a microservices architecture, each service might need different database URLs, timeouts, and logging levels based on the environment. Spring Profiles and external configuration files allow teams to manage these settings without rebuilding the service.

### 2. Feature Toggles

Use profiles to enable or disable features based on environment:

```properties
feature.new-ui.enabled=true
```

This allows A/B testing and gradual rollouts of new features without code changes.

### 3. Data Source Switching

Switch between H2 in development and PostgreSQL in production using profile-specific configuration:

```properties
# application-dev.properties
spring.datasource.url=jdbc:h2:mem:testdb

# application-prod.properties
spring.datasource.url=jdbc:postgresql://prod.db:5432/mydb
```

---

## Conclusion

Spring Boot provides a robust and flexible configuration model that supports both simple and complex applications. By leveraging `application.properties`, `application.yml`, `@ConfigurationProperties`, and Spring Profiles, developers can externalize configuration, manage environment-specific settings, and build maintainable, scalable applications.

Understanding the configuration hierarchy and using type-safe properties ensures better error handling and easier maintenance. For senior engineers, mastering these concepts is essential for building production-ready Spring Boot applications that can adapt to different operational environments.