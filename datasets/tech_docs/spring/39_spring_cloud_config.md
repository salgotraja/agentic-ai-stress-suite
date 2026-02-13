# Spring Cloud Config

Spring Cloud Config is a powerful tool for managing configuration across distributed systems in a centralized and dynamic way. In a microservices architecture, where each service may have its own set of configuration properties, managing and versioning these settings across different environments becomes increasingly complex. Spring Cloud Config provides a solution by offering a centralized configuration server that services can connect to, allowing for externalized configuration, dynamic updates, and version control integration.

This documentation explores the key concepts of Spring Cloud Config, including the configuration server setup, client integration, and dynamic refresh mechanisms. It also covers practical applications, best practices, and common pitfalls.

---

## Centralized Configuration with Spring Cloud Config Server

The Spring Cloud Config Server acts as a central hub for configuration data. It typically stores configuration information in Git repositories, Vault, or local file systems. This allows teams to manage configuration as code, version it alongside their application, and apply environment-specific overrides.

**Why use a central configuration server?**
- **Consistency**: Ensures all microservices consume the same configuration format and values.
- **Decoupling**: Services are not tied to hardcoded configuration values, making them easier to test and deploy.
- **Dynamic updates**: Configurations can be changed without redeploying the application, which is crucial in production environments.

### Example: Config Server Setup

To set up a Spring Cloud Config Server, add the following dependency to your `pom.xml`:

```xml
<dependency>
    <groupId>org.springframework.cloud</groupId>
    <artifactId>spring-cloud-starter-config</artifactId>
</dependency>
```

Then, create a `application.yml` for the config server:

```yaml
server:
  port: 8888

spring:
  application:
    name: config-server
  cloud:
    config:
      server:
        git:
          uri: https://github.com/example/config-repo.git
          clone-on-start: true
          default-label: main
```

This configuration tells the server to fetch configuration from a GitHub repository at `main` branch.

### Config File Structure in Git

The Git repo should contain configuration files for each service and environment:

```
/config-repo/
├── service-a-dev.yml
├── service-a-prod.yml
├── service-b-dev.yml
├── service-b-prod.yml
```

Each file corresponds to a service and environment pair. For example, `service-a-dev.yml` is used when the environment is `dev`.

---

## Config Clients: Connecting Microservices to the Config Server

Once the config server is running, microservices can act as clients and retrieve their configuration from it.

To connect a Spring Boot application to the config server, update its `bootstrap.yml` file:

```yaml
spring:
  application:
    name: service-a
  cloud:
    config:
      uri: http://localhost:8888
      profile: dev
      label: main
```

This tells the service to fetch configuration for the `service-a` application in the `dev` environment from the `main` branch of the config server.

### Example: Client Application Structure

Here’s a basic Spring Boot service connected to the config server:

```java
@SpringBootApplication
public class ServiceAApplication {
    public static void main(String[] args) {
        SpringApplication.run(ServiceAApplication.class, args);
    }
}
```

You can inject configuration values using the `@Value` annotation or `@ConfigurationProperties`.

```java
@Component
@ConfigurationProperties(prefix = "feature.toggle")
public class FeatureToggleConfig {
    private boolean enabled;

    // Getter and setter
    public boolean isEnabled() {
        return enabled;
    }

    public void setEnabled(boolean enabled) {
        this.enabled = enabled;
    }
}
```

In `service-a-dev.yml`, the following property would enable the feature:

```yaml
feature:
  toggle:
    enabled: true
```

---

## Dynamic Refresh of Configuration

One of the most powerful features of Spring Cloud Config is the ability to dynamically refresh configuration values without restarting the service. This is enabled using the `/actuator/refresh` endpoint.

### Enabling Dynamic Refresh

To enable dynamic refresh, include the Spring Boot Actuator and Spring Cloud Config Client dependencies.

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-actuator</artifactId>
</dependency>
```

Then, expose the refresh endpoint in `application.yml`:

```yaml
management:
  endpoints:
    web:
      exposure:
        include: refresh
```

### Refreshing Configuration at Runtime

You can trigger a configuration refresh by sending a POST request to the `/actuator/refresh` endpoint. This updates the values of properties annotated with `@RefreshScope`.

```java
@RestController
@RefreshScope
public class FeatureController {
    @Value("${feature.toggle.enabled}")
    private boolean featureEnabled;

    @GetMapping("/feature")
    public String getFeatureStatus() {
        return "Feature enabled: " + featureEnabled;
    }
}
```

When you send a POST to `/actuator/refresh`, the new value from the config server is fetched and applied at runtime.

---

## Practical Use Cases and Best Practices

### 1. Environment-Specific Configuration

Use `application-{profile}.yml` files to separate configuration for different environments. For example:

- `application-dev.yml`
- `application-prod.yml`

Each file can override certain values like database URLs, logging levels, or feature toggles.

### 2. Configuration for Multiple Services

Each microservice should define its own `spring.application.name`, and the config server will return the appropriate configuration. This allows for modular and isolated configuration management.

### 3. Versioned Configuration

By using Git as the backend for the config server, you can version configurations, roll back changes, and audit who made what change. This is particularly useful in production environments where change management is critical.

### 4. Encryption and Decryption of Sensitive Data

Spring Cloud Config supports encrypting sensitive values like passwords and API keys. The server can decrypt these values when returning them to the client.

To encrypt a value:

1. Start the config server with `--encrypt.enabled=true`.
2. Use the `/encrypt` endpoint to encrypt a value.

Example:

```bash
curl -X POST http://localhost:8888/encrypt -d 'mysecretpassword'
```

Store the encrypted value in the config file, and Spring will automatically decrypt it at runtime using the `/decrypt` endpoint.

---

## Troubleshooting and Common Pitfalls

### 1. Config Server Not Starting

**Cause**: Missing Git repository or incorrect URI.
**Solution**: Verify the Git URL is correct and the repository exists. Ensure the server has access to it (e.g., SSH keys or tokens for private repos).

### 2. Client Fails to Fetch Configuration

**Cause**: The client app is not configured with the correct `spring.application.name` or the config server is unreachable.
**Solution**: Check the `bootstrap.yml` for correct server URI and service name. Ensure the client and server are on the same network.

### 3. Refresh Endpoint Not Working

**Cause**: Actuator not enabled or refresh is not exposed.
**Solution**: Ensure `management.endpoints.web.exposure.include=refresh` is set and the client uses `@RefreshScope`.

### 4. Caching Issues

The config server caches configuration files by default. If you update a config file and do not see the changes, try adding the following to your config server config:

```yaml
spring:
  cloud:
    config:
      server:
        git:
          clone-on-start: true
          force-pull: true
```

---

## Cross-Framework Comparison

| Feature | Spring Cloud Config | Netflix Archaius | HashiCorp Consul |
|--------|----------------------|------------------|-------------------|
| Centralized Config | ✅ | ✅ | ✅ |
| Dynamic Updates | ✅ | ✅ | ✅ |
| Version Control Integration | ✅ (via Git) | ❌ | ✅ (via KV store) |
| Encryption Support | ✅ | ❌ | ✅ |
| Multi-environment Profiles | ✅ | ✅ | ✅ |
| Microservices Support | ✅ | ✅ | ✅ |

Spring Cloud Config offers a more opinionated and tightly integrated solution for Spring-based applications. It is particularly well-suited for teams using Git for configuration management. Consul and Archaius offer similar functionality but with different tooling and ecosystem support.

---

## Conclusion

Spring Cloud Config is an essential tool for managing configuration in a microservices environment. It provides a centralized, versionable, and dynamic way to manage configuration properties, ensuring consistency and flexibility across services. By leveraging features like Git-backed configuration, dynamic refresh, and encryption, teams can streamline deployment processes and reduce operational overhead.

When used correctly, Spring Cloud Config promotes best practices in configuration management, making it an indispensable part of enterprise-grade microservices architectures.