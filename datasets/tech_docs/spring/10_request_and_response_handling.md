# Request and Response Handling

Handling HTTP requests and constructing HTTP responses is a fundamental aspect of building robust web applications, especially in RESTful services. In Java-based web applications using the Spring Framework, this is achieved through request mappers, response entities, and a variety of helper methods that allow developers to manipulate status codes, headers, and content negotiation. This guide explores the core components of handling requests and responses within Spring, focusing on production-ready patterns and best practices.

---

## Request Mappers

In Spring, request handling is primarily managed by `@RequestMapping` and its derived annotations (`@GetMapping`, `@PostMapping`, etc.). These annotations bind HTTP requests to handler methods inside controller classes.

Each handler method in a `@Controller` or `@RestController` is responsible for handling a specific HTTP operation. Here’s an example of a basic GET endpoint:

```java
@RestController
@RequestMapping("/api/users")
public class UserController {

    @GetMapping("/{id}")
    public User getUser(@PathVariable Long id) {
        return userService.findById(id);
    }
}
```

This method maps a GET request to `/api/users/{id}` and returns a `User` object. Since it's annotated with `@RestController`, Spring automatically converts the returned object into a JSON response.

### Advanced Mapping and Customization

You can also customize mappings with conditions on HTTP headers, content types, or even custom annotations like `@RequestCondition`. For example:

```java
@GetMapping(path = "/search", headers = "Accept=application/json")
public List<User> searchUsers(@RequestParam String query) {
    return userService.search(query);
}
```

This method only responds to requests that accept JSON as a response format, which is crucial for content negotiation and compatibility with client applications.

---

## Response Entities

While returning a simple object from a controller method works for many cases, more control is needed when setting HTTP status codes, headers, or custom responses. This is where `ResponseEntity<T>` becomes essential.

```java
@PostMapping("/create")
public ResponseEntity<User> createUser(@RequestBody User user) {
    User createdUser = userService.save(user);
    return ResponseEntity.status(HttpStatus.CREATED)
                         .header(HttpHeaders.LOCATION, "/api/users/" + createdUser.getId())
                         .body(createdUser);
}
```

This example returns a `ResponseEntity` with a `201 Created` status, a `Location` header, and the created resource in the body. By using `ResponseEntity`, you can precisely define the HTTP response returned to the client.

### Custom Error Responses

When an error occurs, you can construct custom error responses to provide more informative feedback:

```java
@GetMapping("/not-found")
public ResponseEntity<ErrorResponse> notFound() {
    ErrorResponse error = new ErrorResponse("Resource not found", 404);
    return ResponseEntity.status(HttpStatus.NOT_FOUND).body(error);
}
```

A typical `ErrorResponse` class might include fields like `message`, `code`, and `timestamp` to standardize error messages across your API. This is especially helpful in the context of REST APIs (see [09 REST APIs](#)).

---

## Status Codes and Headers

Proper use of HTTP status codes and headers is critical for building APIs that are both functional and predictable.

### Common Status Codes

| Status Code | Meaning                      | Use Case                                  |
|-------------|------------------------------|-------------------------------------------|
| 200         | OK                           | Successful GET, PUT, PATCH                |
| 201         | Created                      | After successful POST                     |
| 204         | No Content                   | After DELETE or successful PATCH with no body |
| 400         | Bad Request                  | Invalid input                             |
| 404         | Not Found                    | Resource not found                        |
| 500         | Internal Server Error        | Unhandled exceptions                      |

### Setting Headers

Headers can be used to include metadata in the response:

```java
@GetMapping("/with-headers")
public ResponseEntity<String> getWithHeaders() {
    HttpHeaders headers = new HttpHeaders();
    headers.setContentType(MediaType.APPLICATION_JSON);
    headers.set("X-Custom-Header", "CustomValue");
    return new ResponseEntity<>("{ \"message\": \"Hello\" }", headers, HttpStatus.OK);
}
```

This example sets a custom header and specifies the content type explicitly. Custom headers are often used for API versioning or to communicate internal metadata.

---

## Content Negotiation

Content negotiation is the process of selecting the appropriate representation of a resource based on the client's preferences. Spring supports content negotiation via the `Accept` and `Content-Type` headers.

### Produces and Consumes

You can use `@RequestMapping`'s `produces` and `consumes` attributes to enforce content types:

```java
@GetMapping(path = "/data", produces = MediaType.APPLICATION_JSON_VALUE)
public Data getData() {
    return new Data("JSON data");
}

@PostMapping(path = "/data", consumes = MediaType.APPLICATION_XML_VALUE)
public ResponseEntity<String> postData(@RequestBody String xmlData) {
    return ResponseEntity.ok("Received XML data: " + xmlData);
}
```

These attributes ensure the client is sending and receiving data in the expected format. If not, Spring will return a `415 Unsupported Media Type` error.

### Content Negotiation Strategies

Spring supports several content negotiation strategies, including:

- **Parameter-based**: Using a query parameter like `format=json`.
- **Header-based**: Using the `Accept` header.
- **Path extension-based**: Using `.json` or `.xml` in the URL path.

These strategies can be configured globally or per controller. For example:

```yaml
spring.mvc.contentnegotiation.favor-parameter=true
spring.mvc.contentnegotiation.parameter-name=format
```

This configuration allows clients to request specific formats using URL parameters.

---

## Error Handling and Exception Mapping

Error handling is tightly related to response handling. Spring provides `@ControllerAdvice` to globally handle exceptions and return consistent error responses.

```java
@ControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(ResourceNotFoundException.class)
    public ResponseEntity<ErrorResponse> handleResourceNotFound(ResourceNotFoundException ex) {
        ErrorResponse error = new ErrorResponse(ex.getMessage(), 404);
        return ResponseEntity.status(HttpStatus.NOT_FOUND).body(error);
    }
}
```

This class listens for exceptions across all controllers and converts them into appropriate HTTP responses. It is key for maintaining a clean separation between business logic and HTTP handling.

---

## Best Practices

1. **Use ResponseEntity for Full Control**  
   When more than just the body is needed (e.g., headers or status codes), always use `ResponseEntity`.

2. **Standardize Error Responses**  
   Define a consistent error response format and use it across all endpoints. This improves client-side integration and debugging.

3. **Provide Meaningful Status Codes**  
   Choose HTTP status codes that accurately reflect the outcome of the request. Avoid generic `200 OK` for errors.

4. **Avoid Over-Reliance on Auto-Generated Responses**  
   While `@RestController` helps with simplicity, avoid relying too much on auto-conversion when handling edge cases. Always validate responses.

5. **Use Content Negotiation Wisely**  
   Only support content types that are needed. Adding support for XML when only JSON is used, for example, can complicate your API.

6. **Leverage HTTP Headers for Metadata**  
   Use headers to convey additional information—like pagination details, rate limiting, or API versioning—without bloating the response body.

7. **Log and Monitor All Responses**  
   Ensure that all responses are logged and monitored for performance, correctness, and security. This is critical for production systems.

---

## Troubleshooting and Common Pitfalls

### Pitfall: Missing HTTP Status Code

Forgetting to set an appropriate HTTP status code can lead to client confusion. Always ensure the status code reflects the outcome of the operation.

### Pitfall: Returning Null or Empty Bodies

Returning `null` or empty bodies may result in unexpected client behavior. If no content is to be returned, use `204 No Content` instead.

### Pitfall: Overuse of ResponseEntity

While powerful, `ResponseEntity` should not be used for every endpoint. Use it only when you need full control over the HTTP response.

### Common Debugging Scenarios

- **406 Not Acceptable**: Check if the client is requesting a media type not supported by the server.
- **415 Unsupported Media Type**: Ensure the request’s `Content-Type` matches what the server expects.
- **500 Internal Server Error**: Check for unhandled exceptions and ensure proper exception mapping is in place.

---

## Cross-Framework Comparison

In comparison to other frameworks:

- **Java EE (Jakarta EE)**: Uses `@WebServlet` and `HttpServletResponse` for response handling, which is more verbose and requires manual handling of status codes and headers.
- **Express.js (Node.js)**: Offers more flexibility but lacks the strong typing and compile-time safety of Spring.
- **Django (Python)**: Has a more declarative approach, but is not as powerful when it comes to low-level HTTP manipulation.

---

## Real-World Use Cases

### Case 1: Pagination API

A paginated API might return a `ResponseEntity` with a `200 OK` status, a list of results, and custom headers for pagination:

```java
@GetMapping("/books")
public ResponseEntity<Page<Book>> getBooks(
        @RequestParam int page,
        @RequestParam int size) {
    Page<Book> books = bookService.findBooks(page, size);
    return ResponseEntity.ok()
                         .header("X-Page", String.valueOf(page))
                         .header("X-Total", String.valueOf(books.getTotalElements()))
                         .body(books);
}
```

### Case 2: API Versioning via Headers

To support multiple API versions without changing the URL:

```java
@GetMapping("/products")
public ResponseEntity<List<Product>> getProducts(
        @RequestHeader(name = "Accept", defaultValue = "application/vnd.example.v1+json") String acceptHeader) {
    if (acceptHeader.contains("application/vnd.example.v2+json")) {
        return ResponseEntity.ok(productV2Service.getProducts());
    } else {
        return ResponseEntity.ok(productV1Service.getProducts());
    }
}
```

This allows clients to request different versions of the same resource using HTTP headers.

---

## Conclusion

Request and response handling in Spring is a powerful and flexible process that supports a wide range of use cases, from basic CRUD operations to complex API versioning and content negotiation. By leveraging `ResponseEntity`, proper HTTP status codes, headers, and content negotiation, developers can build RESTful services that are both robust and maintainable.

Always aim for clarity in your responses, consistency in error handling, and flexibility in supporting different client needs. By following best practices and avoiding common pitfalls, you can ensure your APIs are reliable, scalable, and easy to consume by clients.