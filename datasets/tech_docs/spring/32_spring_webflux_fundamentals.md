# Spring WebFlux Fundamentals

Spring WebFlux is a modern, non-blocking web framework built into Spring 5 and above, providing a reactive programming model for building high-performance, scalable applications. It is part of the Spring Framework ecosystem and designed to support both functional and annotation-based web endpoints, making it ideal for handling high-throughput, low-latency use cases. WebFlux is built on reactive streams and leverages two primary reactive types from Project Reactor: `Mono` and `Flux`. These types are used for representing asynchronous data streams—`Mono` for 0 or 1 item, and `Flux` for 0 to N items.

This documentation will explore the fundamentals of Spring WebFlux, including reactive programming concepts, how to define reactive endpoints, stream processing, and how to integrate these features into production-ready systems.

---

## Reactive Programming Basics

Reactive programming is a paradigm that focuses on asynchronous data streams and the propagation of change. It is particularly useful when dealing with I/O-bound operations such as HTTP requests, database calls, and message processing, where blocking can lead to inefficient use of threads and resources.

In the context of Spring WebFlux, reactive programming is powered by **Project Reactor**, which provides the `Mono` and `Flux` types. These types model asynchronous sequences and support operations like `map`, `filter`, `flatMap`, and `merge`, allowing developers to compose complex reactive pipelines.

### Non-Blocking and Backpressure

A core concept in reactive systems is **non-blocking I/O**, which avoids waiting for external resources like databases or network calls by using callbacks or event-driven processing. This allows the application to handle more concurrent requests with fewer threads, improving scalability.

Another essential feature is **backpressure**, a mechanism used to ensure the producer of data does not overwhelm the consumer. In reactive streams, the consumer can signal how much data it can process at a time. This helps prevent memory overflows and ensures smooth data flow.

---

## Setting Up a Spring WebFlux Project

To start building a WebFlux application, ensure your project uses Spring Boot 2.0 or higher and includes the `spring-boot-starter-webflux` dependency. This is typically managed via Maven or Gradle.

### Maven Example

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-webflux</artifactId>
</dependency>
```

### Spring Boot Configuration

WebFlux applications can be configured using either **annotation-based controllers** (similar to Spring MVC) or **functional endpoints** (using `RouterFunction`). Both approaches are valid and can be mixed within the same application.

---

## Reactive Endpoints with Annotation-based Controllers

This style is familiar to Spring MVC developers and uses annotations like `@RestController` and `@GetMapping`. The primary difference is that return types are `Mono<T>` or `Flux<T>` instead of `ResponseEntity<T>` or `List<T>`.

### Example: Returning a Single Item

```java
@RestController
public class UserController {

    private final UserRepository userRepository;

    public UserController(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    @GetMapping("/users/{id}")
    public Mono<User> getUser(@PathVariable String id) {
        return userRepository.findById(id);
    }
}
```

In this example, the `userRepository.findById(id)` returns a `Mono<User>`, which is then returned by the endpoint. The web container handles the asynchronous nature of the response.

### Example: Returning a Stream of Items

```java
@GetMapping("/users")
public Flux<User> getAllUsers() {
    return userRepository.findAll();
}
```

This endpoint returns a `Flux<User>`, representing a stream of users that can be consumed incrementally on the client side.

---

## Reactive Endpoints with Functional Programming (RouterFunction)

The functional approach in WebFlux provides a more declarative and testable way of defining endpoints using `RouterFunction` and `HandlerFunction`.

### Example: Routing and Handling Requests

```java
@Configuration
public class UserRouter {

    private final UserHandler userHandler;

    public UserRouter(UserHandler userHandler) {
        this.userHandler = userHandler;
    }

    @Bean
    public RouterFunction<ServerResponse> route() {
        return RouterFunctions.route(
            RequestPredicates.GET("/users/{id}"), userHandler::getUser)
            .andRoute(RequestPredicates.GET("/users"), userHandler::getAllUsers);
    }
}
```

### Example: Handler Function

```java
@Component
public class UserHandler {

    private final UserRepository userRepository;

    public UserHandler(UserRepository userRepository) {
        this.userRepository = userRepository;
    }

    public Mono<ServerResponse> getUser(ServerRequest request) {
        String id = request.pathVariable("id");

        return userRepository.findById(id)
            .flatMap(user -> ServerResponse.ok().bodyValue(user))
            .switchIfEmpty(ServerResponse.notFound().build());
    }

    public Mono<ServerResponse> getAllUsers(ServerRequest request) {
        return ServerResponse.ok().body(userRepository.findAll(), User.class);
    }
}
```

This style separates routing from handling and is especially useful in microservices or applications with highly dynamic routing requirements.

---

## Reactive Stream Processing

One of the powerful features of Spring WebFlux is the ability to process and transform data streams efficiently. You can use operators from Project Reactor to build pipelines for filtering, mapping, or aggregating data.

### Example: Filtering and Mapping a User Stream

```java
@GetMapping("/users/admins")
public Flux<String> getAdminUsernames() {
    return userRepository.findAll()
        .filter(user -> "ADMIN".equals(user.getRole()))
        .map(User::getName);
}
```

This example filters all users with the role `ADMIN`, then maps their names into a stream of strings. The stream is lazily evaluated and only processed when a subscriber requests the data.

---

## Error Handling in WebFlux

Error handling in reactive systems behaves differently than in imperative programming. Instead of throwing exceptions, WebFlux uses `Mono.error(Throwable)` or `Flux.error(Throwable)` to propagate errors through the stream.

### Example: Global Error Handling with @ControllerAdvice

```java
@ControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(ResourceNotFoundException.class)
    public Mono<ErrorResponse> handleResourceNotFoundError(ResourceNotFoundException ex) {
        return Mono.just(new ErrorResponse("Resource not found", ex.getMessage()));
    }

    @ExceptionHandler(Exception.class)
    public Mono<ErrorResponse> handleGeneralError(Exception ex) {
        return Mono.just(new ErrorResponse("Internal server error", ex.getMessage()));
    }
}
```

This approach allows centralized handling of exceptions while maintaining the reactive nature of the application.

---

## Best Practices for WebFlux Applications

1. **Avoid Blocking Calls**: Never use `.block()` or `.toFuture().get()` in your reactive code. Doing so defeats the purpose of non-blocking I/O and can lead to thread contention.

2. **Use Reactive Databases**: Pair WebFlux with reactive drivers for databases like MongoDB or R2DBC for PostgreSQL to maintain the reactive flow. Blocking drivers like JDBC can cause performance bottlenecks.

3. **Backpressure Management**: Understand and configure backpressure strategies (e.g., `onBackpressureBuffer`, `onBackpressureDrop`) when dealing with high-throughput streams.

4. **Use Caching in Reactive Streams**: Caching strategies must be non-blocking and compatible with reactive types. Libraries like Caffeine can be integrated with `Mono` and `Flux`.

5. **Profile and Monitor Performance**: WebFlux applications should be profiled using tools like Micrometer, Prometheus, and Grafana to ensure optimal performance and responsiveness.

---

## Cross-Framework Comparison

### Comparison with Java Async (31)

Java's `CompletableFuture` and the broader async API (Async 31) provide similar non-blocking capabilities, but they lack the composability and stream processing features of reactive streams. WebFlux integrates better with reactive backends and offers a more consistent model for handling I/O-bound operations.

### Comparison with React Hooks

While React hooks are for client-side JavaScript state management, WebFlux is a server-side Java framework. However, both support asynchronous and event-driven programming. WebFlux provides more built-in abstractions for handling streams and non-blocking I/O, while React hooks focus on state and side-effect management in UI components.

---

## Real-World Use Cases

1. **High-Concurrency APIs**: WebFlux is ideal for APIs expected to handle thousands of concurrent requests, such as real-time data feeds or chat services.

2. **Event-Driven Architectures**: WebFlux works well with reactive messaging systems like Kafka or RabbitMQ, enabling the creation of event-driven microservices.

3. **Streaming APIs**: Applications that require real-time data updates, such as stock market feeds or IoT sensor data, benefit from WebFlux’s ability to stream data incrementally.

4. **Server-Sent Events (SSE)**: WebFlux supports building SSE endpoints that push updates to clients, making it ideal for live dashboards or notifications.

---

## Performance Considerations

Spring WebFlux leverages the **Netty** or **Reactor Netty** web server by default, which is an event-driven, non-blocking I/O model. This is in contrast to the traditional Tomcat servlet container used in Spring MVC. WebFlux applications can scale better under high load due to the reduced thread count and efficient use of I/O resources.

### Benchmark Comparison

| Framework        | Request Type     | Throughput (RPS) | Thread Count |
|------------------|------------------|-------------------|---------------|
| Spring MVC (Tomcat) | REST (GET)     | ~12,000           | 200           |
| Spring WebFlux (Netty) | Reactive (GET) | ~45,000+          | 40            |

These benchmarks illustrate the performance gains achievable with WebFlux when handling non-blocking I/O.

---

## Common Pitfalls and Troubleshooting Tips

1. **Blocking in Reactive Code**: Avoid calling `.block()` in reactive pipelines. Use `.subscribeOn(Schedulers.boundedElastic())` for blocking I/O if necessary.

2. **Incorrect Thread Usage**: Ensure reactive streams are not scheduled on the event loop thread for blocking operations. Use a dedicated scheduler for blocking tasks.

3. **Memory Leaks from Unsubscribed Streams**: Always ensure your reactive streams are properly subscribed and unsubscribed, especially in long-running services.

4. **Misconfigured Backpressure Strategies**: Use `onBackpressureBuffer` or `onBackpressureDrop` to avoid overwhelming downstream consumers.

5. **Testing Reactive Applications**: Use `StepVerifier` from Project Reactor to test `Mono` and `Flux` types and ensure expected emission and completion.

### Example: Testing a Reactive Endpoint

```java
@Test
public void testGetUserById() {
    when(userRepository.findById("123")).thenReturn(Mono.just(new User("123", "John")));

    this.webTestClient.get().uri("/users/123")
        .exchange()
        .expectStatus().isOk()
        .expectBody(User.class).consumeWith(response -> {
            assertEquals("John", response.getResponseBody().getName());
        });
}
```

---

## Conclusion

Spring WebFlux is a powerful and flexible framework for building reactive web applications in Java. By leveraging reactive programming principles, developers can build scalable, high-performance services that efficiently handle concurrent and asynchronous workloads. Whether you're building a microservice, real-time API, or event-driven system, WebFlux provides the tools and abstractions needed to succeed in modern enterprise development.

Understanding how to use `Mono`, `Flux`, and reactive streams effectively is key to unlocking the full potential of Spring WebFlux. With best practices in mind and a solid foundation in reactive concepts, you can build robust and maintainable systems that perform well under load.