# REST API Development

REST (Representational State Transfer) is an architectural style for designing networked applications. It leverages HTTP methods and status codes to provide a scalable, stateless, and uniform interface for client-server communication. In the context of Java applications, Spring Framework offers powerful abstractions, including `@RestController`, `@RequestBody`, `@ResponseBody`, `@PathVariable`, and `@RequestParam`, to build robust RESTful services.

REST APIs are the backbone of modern web services and microservices architectures, enabling integration between frontend applications, mobile apps, and backend systems. In this documentation, we'll explore how to develop RESTful endpoints using Spring MVC, with emphasis on best practices, code examples, and cross-references to related concepts.

---

## RESTful Resource Design

REST APIs are centered around resources, which are identified by unique URLs. Each resource can be manipulated using standard HTTP methods like `GET`, `POST`, `PUT`, `DELETE`, and `PATCH`.

### HTTP Methods and CRUD Mappings

| HTTP Method | Description           | CRUD Operation |
|-------------|------------------------|----------------|
| `GET`       | Retrieve a resource   | Read           |
| `POST`      | Create a new resource | Create         |
| `PUT`       | Update a resource     | Update         |
| `DELETE`    | Remove a resource     | Delete         |
| `PATCH`     | Partially update      | Partial Update |

---

## Core Annotations in Spring MVC

Spring provides several annotations to simplify REST API development. Below are the most important ones related to this topic:

- `@RestController`: Combines `@Controller` and `@ResponseBody`, indicating the class handles HTTP requests and returns the response body directly.
- `@ResponseBody`: Indicates the return value of a method is serialized directly into the HTTP response body.
- `@RequestBody`: Binds the HTTP request body to a method parameter, typically used with `POST` or `PUT`.
- `@PathVariable`: Extracts a segment of the URL path as a variable.
- `@RequestParam`: Extracts query parameters from the URL.

---

## Building RESTful Endpoints with Spring

Let’s create a sample REST controller using the above annotations. We'll manage a `Product` resource.

```java
@RestController
@RequestMapping("/api/products")
public class ProductController {

    private final ProductRepository productRepository;

    public ProductController(ProductRepository productRepository) {
        this.productRepository = productRepository;
    }

    @GetMapping("/{id}")
    public ResponseEntity<Product> getProductById(@PathVariable Long id) {
        return productRepository.findById(id)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }

    @GetMapping
    public ResponseEntity<List<Product>> getAllProducts(
            @RequestParam(required = false, defaultValue = "10") int limit,
            @RequestParam(required = false, defaultValue = "0") int offset) {
        return ResponseEntity.ok(productRepository.findAll(limit, offset));
    }

    @PostMapping
    public ResponseEntity<Product> createProduct(@RequestBody Product product) {
        Product savedProduct = productRepository.save(product);
        return ResponseEntity.status(HttpStatus.CREATED).body(savedProduct);
    }

    @PutMapping("/{id}")
    public ResponseEntity<Product> updateProduct(@PathVariable Long id, @RequestBody Product product) {
        if (!productRepository.existsById(id)) {
            return ResponseEntity.notFound().build();
        }
        product.setId(id);
        Product updated = productRepository.save(product);
        return ResponseEntity.ok(updated);
    }

    @DeleteMapping("/{id}")
    public ResponseEntity<Void> deleteProduct(@PathVariable Long id) {
        if (!productRepository.existsById(id)) {
            return ResponseEntity.notFound().build();
        }
        productRepository.deleteById(id);
        return ResponseEntity.noContent().build();
    }
}
```

This controller provides a complete set of CRUD operations for a `Product` entity. Each method is annotated with HTTP verbs, and parameters are bound using `@PathVariable` and `@RequestParam`.

---

## Understanding Key Annotations

### `@RestController`

This annotation is a convenient shorthand for `@Controller` and `@ResponseBody`, allowing developers to return plain objects from controller methods, which Spring will serialize to JSON using the default `ObjectMapper`. It’s ideal for REST APIs where the response body is the primary data returned.

### `@PathVariable`

Use this when a resource is uniquely identified by a path segment. For example, `/api/products/123` where `123` is the `id`.

> **Edge Case**: If a path contains multiple placeholders, such as `/api/users/{userId}/orders/{orderId}`, each variable is extracted by name.

```java
@GetMapping("/users/{userId}/orders/{orderId}")
public ResponseEntity<Order> getOrderForUser(
        @PathVariable Long userId,
        @PathVariable Long orderId) {
    return orderRepository.findByUserAndOrderId(userId, orderId)
            .map(ResponseEntity::ok)
            .orElse(ResponseEntity.notFound().build());
}
```

### `@RequestParam`

Use this to extract query parameters from the URL. It is optional by default and can have default values.

```java
@GetMapping("/search")
public ResponseEntity<List<Product>> searchProducts(
        @RequestParam String term,
        @RequestParam(required = false, defaultValue = "10") int limit) {
    return ResponseEntity.ok(productRepository.search(term, limit));
}
```

You can also extract multiple parameters:

```java
@GetMapping("/filter")
public ResponseEntity<List<Product>> filterProducts(
        @RequestParam(required = false) String category,
        @RequestParam(required = false) BigDecimal minPrice,
        @RequestParam(required = false) BigDecimal maxPrice) {
    return ResponseEntity.ok(productRepository.filter(category, minPrice, maxPrice));
}
```

> **Best Practice**: Avoid query parameters for sensitive data. Use `@RequestBody` for complex filtering or sorting logic.

### `@RequestBody`

This annotation binds the HTTP request body to a method parameter. It is mandatory for `POST` and `PUT` operations where new or updated data is sent.

> **Important**: The request body must be valid JSON with a structure matching the target class. Spring uses `Jackson` for JSON serialization/deserialization.

```java
@PostMapping("/products")
public ResponseEntity<Product> createProduct(@RequestBody Product product) {
    Product saved = productRepository.save(product);
    return ResponseEntity.status(HttpStatus.CREATED).body(saved);
}
```

> **Edge Case**: If the JSON is malformed or does not map correctly, Spring will throw a `MethodArgumentNotValidException`. Use `@Valid` to trigger validation.

---

## JSON Serialization and Deserialization

Spring uses `Jackson` under the hood for JSON processing. You can customize `ObjectMapper` to control date formatting, field names, or add custom serializers.

For example, to format dates in a specific format:

```java
@Configuration
public class JacksonConfig {
    @Bean
    public ObjectMapper objectMapper() {
        ObjectMapper mapper = new ObjectMapper();
        mapper.setDateFormat(new SimpleDateFormat("yyyy-MM-dd"));
        return mapper;
    }
}
```

> **Note**: Always ensure that your models have proper `@JsonInclude`, `@JsonProperty`, and `@JsonFormat` annotations to avoid unexpected serialization behavior.

---

## Best Practices for REST API Development

1. **Use HTTP Status Codes Correctly**:
   - `200 OK`: For successful GET/PUT/POST.
   - `201 Created`: For POST creating a new resource.
   - `204 No Content`: For DELETE or update without payload.
   - `400 Bad Request`: For invalid input.
   - `404 Not Found`: When a resource is missing.
   - `409 Conflict`: When there is a version conflict.
   - `500 Internal Server Error`: For unhandled errors.

2. **Avoid Overusing `@RequestMapping`**:
   Use HTTP-specific annotations like `@GetMapping`, `@PostMapping`, etc., for better readability and self-documenting code.

3. **Use HATEOAS for Hypermedia-Driven APIs**:
   While not required, Spring HATEOAS can be used to embed links in responses for discoverability.

4. **Version Your API**:
   Use path-based versioning, such as `/api/v1/products`, or header-based versioning.

5. **Implement Global Exception Handling**:
   Use `@ControllerAdvice` to centralize error handling and return consistent error responses.

```java
@ControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(EntityNotFoundException.class)
    public ResponseEntity<ErrorResponse> handleResourceNotFound(EntityNotFoundException ex) {
        return ResponseEntity.status(HttpStatus.NOT_FOUND)
                .body(new ErrorResponse(HttpStatus.NOT_FOUND.value(), ex.getMessage()));
    }

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<ErrorResponse> handleValidationExceptions(MethodArgumentNotValidException ex) {
        return ResponseEntity.status(HttpStatus.BAD_REQUEST)
                .body(new ErrorResponse(HttpStatus.BAD_REQUEST.value(), "Invalid input"));
    }
}
```

6. **Use DTOs Instead of Entities in Responses**:
   Directly exposing entities can lead to data leakage and tight coupling. Always map entities to DTOs before returning them.

7. **Enable CORS in Production**:
   Configure `@CrossOrigin` at the class or method level, or use a global `WebMvcConfigurer` to allow cross-origin requests safely.

---

## Real-World Use Cases

### 1. Product Catalog API

A product catalog service allows users to list, create, update, and delete products. The above `ProductController` is a simplified version of such a service. In a real-world scenario, you would include pagination, filtering, and sorting.

### 2. User Management API

A user management system might require endpoints for registration, login, and profile updates. Here’s an example of a user registration endpoint:

```java
@PostMapping("/users")
public ResponseEntity<User> registerUser(@RequestBody UserRegistrationRequest request) {
    User user = userService.registerUser(request);
    return ResponseEntity.status(HttpStatus.CREATED).body(user);
}
```

### 3. Order Processing Service

An order management system may involve multiple resources, such as users, products, and orders. Here's a sample endpoint to create an order:

```java
@PostMapping("/orders")
public ResponseEntity<Order> createOrder(@RequestBody OrderRequest request) {
    Order order = orderService.createOrder(request);
    return ResponseEntity.status(HttpStatus.CREATED).body(order);
}
```

---

## Common Pitfalls and Troubleshooting

1. **Mismatched JSON Types**:
   If the JSON sent in the request does not match the target class, Spring will throw `HttpMessageNotReadableException`. Ensure that the JSON keys and types match your DTOs.

2. **Missing `@RequestBody` or `@ResponseBody`**:
   Forgetting these annotations can lead to unexpected behavior, such as returning an object as a string instead of JSON.

3. **Incorrect HTTP Methods**:
   Using `GET` for updates or `POST` for reads violates REST principles and can confuse clients.

4. **Missing `@PathVariable` or `@RequestParam`**:
   If a URL path contains placeholders but they are not bound in the method, Spring will throw `MissingPathVariableException`.

5. **Incorrect Exception Handling**:
   Failing to handle exceptions can lead to uncaught errors, exposing stack traces or other sensitive information.

---

## Conclusion

REST API development in Spring is made efficient and scalable through the use of annotations like `@RestController`, `@RequestBody`, and `@PathVariable`. These annotations, when used correctly, allow developers to build clean, production-ready endpoints with minimal boilerplate.

By following best practices—such as using HTTP status codes appropriately, versioning APIs, and leveraging DTOs—you can build maintainable and robust APIs that scale with your application.

For further understanding, refer to the Spring MVC (08) documentation and explore JSON serialization techniques for fine-grained control over data output.