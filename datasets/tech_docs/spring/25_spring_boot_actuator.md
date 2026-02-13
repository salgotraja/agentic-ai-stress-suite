# Spring Boot Actuator

Spring Boot Actuator is a production-ready module that provides built-in endpoints to monitor and manage Spring Boot applications. It exposes a set of endpoints that can be accessed via HTTP or JMX, allowing developers and operations teams to inspect the health, metrics, configuration, and performance of applications in production. These endpoints are particularly useful for integrating with external monitoring systems and supporting DevOps and Site Reliability Engineering (SRE) practices.

Actuator simplifies the process of observing and maintaining the stability of applications by offering out-of-the-box features such as health checks, metrics collection, and configuration insights. It also allows developers to customize and extend its behavior to suit specific operational needs.

---

## Health Checks

Health checks are essential for monitoring the availability and integrity of a running application. Actuator provides the `/actuator/health` endpoint (by default) to expose health information. This endpoint can be configured to return either a simple or detailed status, depending on the environment (e.g., production vs. development).

### Built-in Health Indicators

Spring Boot includes several built-in health indicators that monitor the status of various components, such as:

- Database connections (`DataSourceHealthIndicator`)
- Disk space (`DiskSpaceHealthIndicator`)
- Web service endpoints (`WebEndpointHealthIndicator`)

By default, the health endpoint returns a `UP` status if all the health indicators pass their checks. If any indicator fails, the status changes to `DOWN` or `OUT_OF_SERVICE`.

```java
// application.properties
management.endpoint.health.show-details=always
management.health.defaults.enabled=true
```

### Custom Health Indicators

Custom health indicators can be created by implementing the `HealthIndicator` interface. This is useful when you need to check the health of a third-party service, database connection, or any custom resource.

```java
import org.springframework.boot.actuate.health.*;
import org.springframework.stereotype.Component;

@Component
public class CustomHealthIndicator implements HealthIndicator {

    @Override
    public Health health() {
        // Simulate a check to an external service
        boolean isServiceAvailable = checkExternalService();

        if (isServiceAvailable) {
            return Health.up().withDetail("msg", "External service is available").build();
        } else {
            return Health.down().withDetail("error", "External service is unreachable").build();
        }
    }

    private boolean checkExternalService() {
        // Simulate external API call or service check
        return true; // or false based on actual logic
    }
}
```

Once registered, this health indicator will be automatically included in the `/actuator/health` endpoint.

#### Best Practices

- Use health checks to detect early signs of failure.
- Avoid including health checks that are too slow or resource-heavy.
- Use the `DOWN` status only for critical issues that should trigger alerts.
- Ensure health checks are idempotent and do not alter the application state.

---

## Metrics Collection

Actuator provides the `/actuator/metrics` endpoint to expose runtime metrics about the application. These metrics include memory usage, garbage collection, thread counts, HTTP request statistics, and database pool usage.

### Built-in Metrics

Metrics are collected using the Micrometer library, which supports a number of monitoring systems like Prometheus, Graphite, and InfluxDB. You can view all registered metrics via:

```
GET /actuator/metrics
```

You can also drill down into specific metrics:

```
GET /actuator/metrics/jvm.memory.used
```

### Custom Metrics

Custom metrics can be registered using the `MeterRegistry` bean provided by Spring Boot. This is useful for tracking application-specific performance indicators, such as the number of failed login attempts, request latency, or user activity.

```java
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Counter;
import org.springframework.stereotype.Service;

@Service
public class LoginService {

    private final Counter failedLogins;

    public LoginService(MeterRegistry registry) {
        this.failedLogins = registry.counter("auth.failedLogins");
    }

    public void authenticate(String username, String password) {
        if (!isValid(username, password)) {
            failedLogins.increment();
            throw new SecurityException("Invalid credentials");
        }
        // proceed with login
    }

    private boolean isValid(String username, String password) {
        // authentication logic
        return true; // or false based on actual logic
    }
}
```

This custom metric can now be accessed via:

```
GET /actuator/metrics/auth.failedLogins
```

#### Best Practices

- Use descriptive metric names following a consistent naming convention.
- Avoid collecting too many metrics in high-volume environments.
- Group related metrics using tags for easier analysis.
- Monitor metrics over time to detect anomalies or trends.

---

## Info Endpoint

The `/actuator/info` endpoint provides general information about the application, such as version, build time, SCM details, and custom properties. By default, this endpoint returns a minimal set of information, but can be extended with additional details.

### Built-in Info Properties

If you have a `application.properties` or `application.yml` file with properties like:

```yaml
info:
  app:
    name: MySpringBootApp
    version: 1.0.0
    description: A sample Spring Boot application
```

They will appear in the `/actuator/info` response:

```json
{
  "app": {
    "name": "MySpringBootApp",
    "version": "1.0.0",
    "description": "A sample Spring Boot application"
  }
}
```

### Custom Info

You can programmatically add more details using the `InfoContributor` interface.

```java
import org.springframework.boot.actuate.info.Info;
import org.springframework.boot.actuate.info.InfoContributor;
import org.springframework.stereotype.Component;

@Component
public class CustomInfoContributor implements InfoContributor {

    @Override
    public void contribute(Info.Builder builder) {
        builder.withDetail("env", "Production")
               .withDetail("lastDeployed", "2025-04-01T10:00:00Z");
    }
}
```

This allows you to provide dynamic or environment-specific information to the info endpoint.

---

## Monitoring and Observability

Actuator is a cornerstone of observability in Spring Boot applications. Observability is the ability to understand the internal state of a system from its external outputs. Actuator provides the necessary data to support three pillars of observability: logging, metrics, and tracing.

### Integration with Monitoring Tools

Actuator can be integrated with external monitoring solutions like Prometheus, Grafana, and Datadog. For example, Prometheus scrapes metrics from the `/actuator/metrics` endpoint and visualizes them in dashboards.

```yaml
management:
  endpoints:
    web:
      exposure:
        include: "*"
  metrics:
    export:
      prometheus:
        enabled: true
```

This configuration enables Prometheus metrics scraping for all metrics provided by Actuator.

### Production Readiness

Actuator enhances production readiness by allowing:

- **Health checks**: Used by load balancers to route traffic only to healthy instances.
- **Metrics**: Exposed for real-time monitoring and historical analysis.
- **Configuration visibility**: The `/actuator/configprops` endpoint allows inspecting all configuration properties in the application context.

#### Best Practices

- Secure actuator endpoints using Spring Security, especially in production.
- Limit the exposure of sensitive endpoints (e.g., `/actuator/shutdown`) to internal networks.
- Use different exposure settings for development and production environments.
- Combine actuator with centralized logging and tracing for comprehensive observability.

---

## Best Practices

1. **Security First**: Always secure Actuator endpoints using authentication and authorization. Use Spring Security to restrict access to only authorized users or services.

2. **Environment-Specific Configuration**: Use different sets of exposed endpoints for development vs. production. For example, expose all endpoints in development but only health and info in production.

3. **Use Tags for Metrics**: When registering custom metrics, use tags to add context. Tags help in filtering and grouping metrics based on environment, instance, or user type.

4. **Monitor Key Performance Indicators (KPIs)**: Focus on metrics that directly impact business goals, such as error rates, latency, and throughput.

5. **Customize Health Indicators for Business Logic**: Tailor health indicators to align with your application's business logic, not just technical health.

6. **Integrate with CI/CD Pipelines**: Automate the collection and validation of health and metrics data in CI/CD pipelines to catch issues early.

7. **Avoid Overloading the Application**: Do not add too many health checks or metrics that could impact application performance.

---

## Troubleshooting and Common Pitfalls

### Missing Endpoints

If an endpoint is not visible, ensure that it is included in the exposure list:

```yaml
management:
  endpoints:
    web:
      exposure:
        include: health,info,metrics
```

### Unauthorized Access

If you receive a 401 Unauthorized response, ensure that Spring Security is configured to allow access to the actuator endpoints for authenticated users.

### Slow Health Checks

If health checks are slow, consider reducing the number or optimizing the logic. Long health checks can cause timeouts in load balancers.

### Misconfigured Metrics

If metrics are not appearing as expected, check the `MeterRegistry` bean and ensure that the metric name and tags are correctly used.

### Health Status Not Updating

If the health status does not update after a failure, ensure that the health indicator is correctly implemented and that it triggers a status update.

---

## Cross-Framework Comparison

| Feature                     | Spring Boot Actuator          | Dropwizard Metrics | Prometheus Exporter |
|-----------------------------|-------------------------------|--------------------|-----------------------|
| Health Checks               | First-class support           | Requires integration | No native support     |
| Metrics Collection          | Built-in (via Micrometer)     | Built-in           | External integration  |
| Configuration Visibility    | `/actuator/configprops`       | Not available      | Not available         |
| Easy to Secure              | Yes                           | Yes                | Yes                   |
| Custom Health/Metrics       | Yes                           | Yes                | No native support     |
| Observability Integration   | Prometheus, Grafana, Datadog  | No native          | Yes                   |

While Actuator is tightly integrated with Spring Boot and offers a comprehensive set of features for monitoring, Prometheus is a better fit for high-performance systems that require real-time metrics and alerting at scale.

---

## Real-World Use Cases

1. **Health Checks in Load Balancer**: A Kubernetes service uses `/actuator/health` to ensure traffic is only routed to healthy pods.
2. **Monitoring API Latency**: A custom metric tracks the average latency of API requests using `/actuator/metrics`.
3. **Database Connection Monitoring**: A custom health indicator checks the availability of a secondary database before routing queries.
4. **Deployment Validation**: The `/actuator/info` endpoint confirms the version of the deployed application to avoid inconsistencies.
5. **Failure Detection**: A health indicator that checks the status of a key external service triggers alerts when it goes down.

---

## Conclusion

Spring Boot Actuator is a powerful tool that enhances the observability and maintainability of Spring Boot applications. It provides a rich set of endpoints for health checks, metrics, and configuration inspection, and supports integration with external monitoring systems. By customizing health indicators and metrics, developers can align monitoring practices with business requirements and ensure the reliability of their applications in production.