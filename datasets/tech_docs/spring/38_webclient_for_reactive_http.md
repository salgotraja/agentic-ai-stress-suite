# WebClient for Reactive HTTP

Reactive programming is a paradigm shift in how applications handle asynchronous, event-driven workloads. In the context of Spring Framework, the `WebClient` component provides a non-blocking, reactive HTTP client that integrates seamlessly with Spring WebFlux. Unlike traditional `RestTemplate`, which is synchronous and blocking, `WebClient` is designed to work with reactive streams, enabling efficient handling of high-concurrency scenarios and stream-based APIs.

This documentation covers `WebClient`’s core concepts, usage patterns, and best practices to help senior engineers build scalable, high-performance reactive applications.

---

## Core Concepts

### WebClient Overview

`WebClient` is the primary HTTP client in Spring WebFlux, built on top of the reactive streams API and Project Reactor. It supports both synchronous and asynchronous requests and is capable of handling backpressure, which is essential for managing data streams without overwhelming the system.

Key features include:

- **Non-blocking I/O**: No thread is blocked waiting for HTTP responses.
- **Reactive Streams support**: Compatible with `Mono` and `Flux` types.
- **Backpressure-aware**: Ensures smooth data flow between components.
- **Flexible configuration**: Supports custom `ClientHttpConnector`, `ExchangeStrategies`, and HTTP filters.

### When to Use WebClient

Use `WebClient` when:

- Your application needs to make HTTP calls to other microservices or REST APIs.
- You are building a reactive application using Spring WebFlux.
- You need to process large streams of data asynchronously.
- You must handle high concurrency and low latency.

Avoid using `WebClient` for simple REST calls if you are not already using a reactive architecture, as it may add unnecessary complexity.

---

## Reactive HTTP Client Setup

To use `WebClient`, you must have Spring WebFlux on your classpath. Add the following dependency to your `pom.xml` or `build.gradle`:

```xml
<!-- Maven -->
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-webflux</artifactId>
</dependency>
```

Once configured, you can create a `WebClient` instance via Spring’s dependency injection:

```java
@Configuration
public class WebClientConfig {

    @Bean
    public WebClient webClient() {
        return WebClient.builder()
                .baseUrl("https://api.example.com")
                .defaultHeader("Accept", "application/json")
                .build();
    }
}
```

---

## Async API Calls with WebClient

Reactive applications often perform asynchronous HTTP requests without blocking threads. `WebClient` makes this straightforward with its fluent API.

### Example: Fetching a JSON Resource

```java
public class UserClient {

    private final WebClient webClient;

    public UserClient(WebClient webClient) {
        this.webClient = webClient;
    }

    public Mono<User> fetchUser(String userId) {
        return webClient.get()
                .uri("/users/{id}", userId)
                .retrieve()
                .bodyToMono(User.class);
    }
}
```

In this example, `get()` initiates a GET request, `uri()` specifies the endpoint, `retrieve()` processes the response, and `bodyToMono()` converts the body to a `Mono<User>`. This is a non-blocking operation that emits the user data once available.

### Error Handling

Error handling is crucial in reactive streams. Use `onErrorResume()` or `doOnError()` to handle exceptions gracefully:

```java
public Mono<User> fetchUserWithFallback(String userId) {
    return webClient.get()
            .uri("/users/{id}", userId)
            .retrieve()
            .onStatus(HttpStatus::is4xxClientError, response -> {
                return Mono.error(new UserNotFoundException("User not found"));
            })
            .bodyToMono(User.class)
            .onErrorResume(e -> {
                if (e instanceof UserNotFoundException) {
                    return Mono.just(new User());
                }
                return Mono.error(e);
            });
}
```

---

## Streaming with WebClient

`WebClient` supports stream-based communication through `Flux<T>`, making it suitable for processing large payloads or real-time data.

### Example: Streaming JSON Array

If the API returns a JSON array, `bodyToFlux()` allows you to read it incrementally:

```java
public Flux<User> streamAllUsers() {
    return webClient.get()
            .uri("/users")
            .retrieve()
            .bodyToFlux(User.class);
}
```

This is efficient for processing thousands of users without loading the entire response into memory.

---

## Advanced WebClient Features

### Custom Request Headers and Query Parameters

Headers and query parameters can be added dynamically using `headers()` and `queryParams()`:

```java
public Mono<User> fetchUserWithHeaders(String userId) {
    return webClient.get()
            .uri("/users/{id}", userId)
            .header("Authorization", "Bearer token123")
            .queryParam("sort", "name")
            .retrieve()
            .bodyToMono(User.class);
}
```

### Request Body and POST Requests

For POST requests with a body, use `bodyValue()` or `body(BodyInserters.fromValue())`:

```java
public Mono<CreateResponse> createNewUser(User user) {
    return webClient.post()
            .uri("/users")
            .bodyValue(user)
            .retrieve()
            .bodyToMono(CreateResponse.class);
}
```

### PUT and DELETE Requests

WebClient supports all HTTP methods:

```java
public Mono<Void> updateUser(String userId, User updatedUser) {
    return webClient.put()
            .uri("/users/{id}", userId)
            .bodyValue(updatedUser)
            .retrieve()
            .bodyToMono(Void.class);
}

public Mono<Void> deleteUser(String userId) {
    return webClient.delete()
            .uri("/users/{id}", userId)
            .retrieve()
            .bodyToMono(Void.class);
}
```

---

## Cross-Framework Integration

WebClient integrates well with the broader Spring ecosystem. For example, in a Spring WebFlux controller, return `Mono` or `Flux` directly from your methods:

```java
@RestController
public class UserController {

    private final WebClient webClient;

    public UserController(WebClient webClient) {
        this.webClient = webClient;
    }

    @GetMapping("/proxy/users/{id}")
    public Mono<User> proxyUser(String userId) {
        return webClient.get()
                .uri("/users/{id}", userId)
                .retrieve()
                .bodyToMono(User.class);
    }
}
```

This enables you to build reactive proxies or API gateways with minimal overhead.

---

## Best Practices

### Avoid Mixing Blocking and Non-blocking Code

Never block on reactive types using `block()` in a reactive context. Doing so defeats the purpose of non-blocking programming and can lead to thread pool exhaustion.

Use `Mono.subscribe()` or `Mono.toFuture()` if you must bridge between blocking and reactive worlds.

### Use Reactive Types for Response Bodies

Always return `Mono` or `Flux` from services that use WebClient. This preserves the reactive nature of your application.

### Secure Communication

Use HTTPS by default and ensure that TLS is properly configured. In production:

- Validate server certificates.
- Use `SslContext` for mutual TLS.

### Performance Tuning

Tune `WebClient` for high-throughput scenarios:

- Use a `ReactorClientHttpConnector` with connection pooling.
- Adjust buffer sizes and timeouts.
- Enable logging for request tracing.

### Testing WebClient

Use `MockWebServer` from OkHttp for integration tests:

```java
@BeforeEach
void setup() {
    mockWebServer = new MockWebServer();
    mockWebServer.start();
}

@AfterEach
void teardown() throws IOException {
    mockWebServer.shutdown();
}
```

---

## Common Pitfalls and Troubleshooting

### 1. Blocking on Reactive Types

Avoid using `.block()` in reactive contexts. This leads to thread contention and degrades scalability.

**Fix**: Use `subscribe()` or let WebFlux manage subscription automatically.

### 2. Missing Content-Type Headers

Sometimes APIs expect a specific `Content-Type`. Always set the `Accept` and `Content-Type` headers explicitly.

### 3. Timeouts and Retries

Add timeouts and retry mechanisms for unreliable APIs:

```java
public Mono<User> fetchUserWithRetry(String userId) {
    return webClient.get()
            .uri("/users/{id}", userId)
            .retrieve()
            .bodyToMono(User.class)
            .timeout(Duration.ofSeconds(5))
            .retry(3);
}
```

### 4. Logging and Debugging

Use `doOnNext`, `doOnError`, and `doOnSubscribe` for logging:

```java
webClient.get()
    .uri("/users")
    .retrieve()
    .bodyToFlux(User.class)
    .doOnNext(user -> log.info("Received user: {}", user.getName()))
    .subscribe();
```

---

## Cross-References

- **WebFlux**: [WebFlux (32)](#): Learn how `WebClient` integrates with Spring WebFlux for full-stack reactive applications.
- **REST clients**: [REST clients (37)](#): Compare `WebClient` with other REST clients like `RestTemplate` and `Feign`.

---

## Conclusion

`WebClient` is a powerful tool for building modern, scalable applications in Spring. By leveraging its non-blocking and reactive capabilities, developers can build applications that are efficient, scalable, and future-proof. Whether you're consuming REST APIs or building reactive gateways, understanding when and how to use `WebClient` is essential for any enterprise Java developer.

Use the guidance and examples in this document to implement production-grade reactive HTTP clients that are robust, maintainable, and high-performing.