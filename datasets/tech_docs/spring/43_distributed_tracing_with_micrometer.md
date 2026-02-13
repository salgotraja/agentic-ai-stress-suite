# Distributed Tracing with Micrometer

Distributed tracing is a critical component of observability in modern microservices architectures. It enables developers to understand the flow of requests across service boundaries, identify latency bottlenecks, and monitor system health. Micrometer, a popular metrics instrumentation library for Java, provides robust support for distributed tracing through integration with tracing backends such as Zipkin. This documentation explores how to use Micrometer for distributed tracing, including trace propagation, custom metrics, and integration with observability tools.

---

## Key Concepts

Micrometer is primarily known for its metrics collection capabilities, but it also includes first-class support for distributed tracing via its `micrometer-tracing` module. This module offers an abstraction layer over tracing implementations like Brave (which integrates with Zipkin), allowing developers to write tracing logic that is portable across backends.

### Tracing Terminology

- **Trace**: A tree of spans representing a single logical operation in your system.
- **Span**: A named, timed operation representing a unit of work within a trace.
- **Context Propagation**: The mechanism by which trace and span context is passed between services, usually via HTTP headers.
- **Sampling**: A mechanism to control the volume of traces collected. Not all traces are sampled for performance reasons.

Micrometer tracing uses a `Tracer` interface to manage the lifecycle of spans and provides annotations and APIs to create and manage traces programmatically.

---

## Setting Up Micrometer Tracing

To use Micrometer Tracing with your Spring Boot application, you need to include the following dependencies in your `pom.xml`:

```xml
<dependency>
    <groupId>io.micrometer</groupId>
    <artifactId>micrometer-tracing</artifactId>
    <version>1.12.0</version>
</dependency>
<dependency>
    <groupId>io.micrometer</groupId>
    <artifactId>micrometer-observation</artifactId>
    <version>1.12.0</version>
</dependency>
```

If you're using Kotlin, add:

```kotlin
implementation("io.micrometer:micrometer-tracing:1.12.0")
implementation("io.micrometer:micrometer-observation:1.12.0")
```

Micrometer Tracing integrates with Spring's Actuator for health checks and metrics endpoints (`/actuator/trace`).

---

## Trace Propagation with Micrometer

Trace propagation is the mechanism that allows traces to be followed across service boundaries. Micrometer uses the OpenTelemetry or Brave format to propagate trace context.

By default, Micrometer sets up HTTP propagation for REST controllers, WebClient, and Feign clients.

### Example: Enabling HTTP Trace Propagation

Micrometer automatically instruments HTTP requests made with `WebClient` and `RestTemplate` when used with the appropriate `Observation` APIs.

Here's an example using `WebClient` with trace propagation:

```java
import io.micrometer.observation.Observation;
import org.springframework.web.reactive.function.client.WebClient;
import reactor.core.publisher.Mono;

public class ServiceClient {

    private final WebClient webClient;

    public ServiceClient(WebClient webClient) {
        this.webClient = webClient;
    }

    public Mono<String> fetchData(String url) {
        return Observation.createNotStarted("fetch-data", null, () -> {
            return webClient.get()
                    .uri(url)
                    .retrieve()
                    .bodyToMono(String.class);
        }).observe();
    }
}
```

This ensures that the trace context is automatically propagated via HTTP headers like `traceparent`.

---

## Creating Custom Traces and Spans

Micrometer provides APIs to manually create custom traces and spans. This is particularly useful for instrumenting internal business logic or legacy code that isn't automatically covered by built-in instrumentation.

### Example: Manually Creating a Span

```java
import io.micrometer.tracing.Span;
import io.micrometer.tracing.Tracer;

public class OrderService {

    private final Tracer tracer;

    public OrderService(Tracer tracer) {
        this.tracer = tracer;
    }

    public void processOrder(String orderId) {
        Span span = tracer.nextSpan().name("process-order").start();
        try (var scope = tracer.withSpan(span)) {
            // Simulate some business logic
            Thread.sleep(100);
            if (orderId == null) {
                throw new IllegalArgumentException("Order ID cannot be null");
            }
            // Log additional context if needed
            span.tag("order.id", orderId);
        } catch (Exception e) {
            span.error(e);
            throw e;
        } finally {
            span.finish();
        }
    }
}
```

In this example, a new span is created for the `processOrder` method. Tags are added for additional context, and errors are recorded if any occur.

---

## Integrating with Zipkin

Zipkin is a widely used distributed tracing system that supports Micrometer Tracing. To send traces to Zipkin, configure the `application.properties` file with the Zipkin endpoint:

```properties
micrometer.tracing.distributed-tracing=true
micrometer.tracing.baggage-headers=order.id,trace.id
management.tracing.zipkin.destination=http://localhost:9411/api/v2/spans
```

Micrometer will now send traces to the Zipkin server at `localhost:9411`, which you can inspect using the Zipkin UI.

### Sampling Configuration

By default, Micrometer samples only a fraction of traces to reduce overhead. You can adjust the sampling rate as needed:

```properties
micrometer.tracing.sampling.probability=0.1
```

This sets the sampling rate to 10%. Adjust this based on your system's performance and trace volume.

---

## Cross-Framework Instrumentation

Micrometer Tracing is designed to work with multiple frameworks. For example, when using Spring WebFlux, you can instrument reactive code using `Observation`:

```java
import io.micrometer.observation.Observation;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Mono;

@RestController
public class GreetingController {

    @GetMapping("/greet")
    public Mono<String> greet() {
        return Observation.createNotStarted("greet", null, () -> {
            return Mono.just("Hello, world!");
        }).observe();
    }
}
```

This automatically wraps the HTTP request in a trace span.

---

## Custom Metrics with Micrometer Tracing

While tracing is about understanding the flow of execution, metrics are used to measure performance and behavior. Micrometer supports custom metrics that can be linked to spans for enhanced observability.

### Example: Adding a Timer Metric

```java
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import io.micrometer.tracing.Span;

public class PaymentService {

    private final MeterRegistry registry;

    public PaymentService(MeterRegistry registry) {
        this.registry = registry;
    }

    public void processPayment(String userId, double amount) {
        Timer timer = registry.timer("payment.process.time");
        Span span = tracer.nextSpan().name("process-payment").start();
        try (var scope = tracer.withSpan(span)) {
            span.tag("user.id", userId);
            timer.record(() -> {
                // Simulate payment processing
                Thread.sleep(200);
                if (amount <= 0) {
                    throw new IllegalArgumentException("Amount must be positive");
                }
            });
        } catch (Exception e) {
            span.error(e);
            throw e;
        } finally {
            span.finish();
        }
    }
}
```

This example links a custom metric with a tracing span, allowing you to correlate performance data with trace information.

---

## Best Practices for Distributed Tracing with Micrometer

Here are some recommended practices for building production-ready distributed tracing with Micrometer:

### 1. Use Automatic Instrumentation First

Micrometer provides extensive support for automatic instrumentation via `Observation` and integration with Spring components. This reduces boilerplate code and ensures consistent instrumentation across services.

### 2. Add Custom Spans for Business Logic

While automatic instrumentation covers external calls, you should manually instrument key business operations to gain deeper insights into internal logic.

### 3. Use Baggage for Correlation

Baggage allows you to pass contextual information (e.g., user ID, request ID) across services. This is essential for grouping related traces and debugging:

```properties
micrometer.tracing.baggage-headers=user.id,request.id
```

### 4. Handle Errors and Timeouts Gracefully

Ensure that all spans are properly closed even in the case of exceptions. Use `try-with-resources` or `try-catch-finally` blocks to manage span lifecycle.

### 5. Avoid Over-Sampling in Production

Sampling too aggressively can lead to high overhead. Use a sampling rate that balances trace visibility with system performance.

### 6. Use Contextual Tags and Logs

Add relevant tags and logs to spans for better trace analysis. For example, include request IDs, user IDs, or error messages.

---

## Cross-Referencing with Other Observability Tools

Micrometer Tracing integrates well with Spring Boot Actuator (`Actuator 25`), which provides HTTP endpoints for metrics, health, and trace information. You can use `/actuator/trace` to view recent traces directly from the application.

For full observability, combine tracing with logging (e.g., using SLF4J with MDC) and metrics (using the `micrometer-core` module). This creates a comprehensive view of system behavior.

---

## Troubleshooting Common Issues

### 1. **Traces Not Showing Up in Zipkin**

- Ensure the Zipkin server is running and accessible.
- Verify that the application is correctly configured with the correct Zipkin URL.
- Confirm that tracing is enabled: `management.tracing.zipkin.enabled=true`
- Check logs for errors related to trace submission.

### 2. **Missing Spans in Traces**

- Confirm that the services are using the same trace ID propagation mechanism.
- Ensure that all services are running the same version of Micrometer Tracing.
- Use baggage propagation to ensure consistent context across services.

### 3. **High CPU or Memory Usage**

- Reduce tracing sampling rate.
- Disable instrumentation for non-critical services.
- Use `micrometer-observation` for fine-grained control.

---

## Real-World Use Cases

### Case Study: E-Commerce Order Processing

A typical e-commerce platform might have microservices for order management, payment processing, and inventory control. With Micrometer Tracing, you can:

- Track the flow of an order from the frontend to backend.
- Identify latency in payment processing.
- Correlate errors with specific user requests via baggage headers.

### Case Study: API Gateway Tracing

In an API gateway, you can use Micrometer to trace incoming requests as they pass through to various microservices. This helps identify routing issues and performance bottlenecks.

---

## Conclusion

Micrometer Tracing provides a powerful, flexible mechanism for implementing distributed tracing in Java-based microservices. By combining trace propagation, custom spans, and integration with observability tools like Zipkin, you can build a robust monitoring solution tailored for production environments.

When used with Spring Framework, Micrometer offers a seamless integration path with minimal configuration, making it an excellent choice for teams already using Spring Boot for microservices development.