# Spring MVC Fundamentals

Spring MVC is a powerful module within the Spring Framework designed for building scalable, maintainable web applications. As an extension of the Spring ecosystem, it implements the **Model-View-Controller (MVC)** architectural pattern, enabling developers to decouple business logic, user interface, and request handling. This documentation provides a comprehensive guide to core Spring MVC concepts, focusing on production-grade practices and real-world use cases.

---

## MVC Architecture in Spring

### Core Components

The MVC pattern divides application responsibilities into three distinct components:
- **Model**: Manages application data and business logic.
- **View**: Renders data to the client (e.g., HTML, JSON).
- **Controller**: Handles incoming requests, updates the model, and selects the view.

In Spring MVC, these components are implemented as follows:
- **`@Controller`**: Marks a class as a Spring MVC controller, handling HTTP requests.
- **`@RequestMapping`**: Binds HTTP requests to handler methods.
- **`Model`**: Carries data from the controller to the view.
- **`View`**: Renders the response (e.g., Thymeleaf template, JSON response).
- **`DispatcherServlet`**: Central servlet that coordinates the flow of requests.

### Request Lifecycle Overview

1. **Client Request** → 2. **DispatcherServlet** → 3. **HandlerMapping** selects controller → 4. **Controller** processes request → 5. **ModelAndView** returned → 6. **ViewResolver** selects view → 7. **View** renders response.

```java
// Example: Basic Controller with RequestMapping
@Controller
public class GreetingController {
    @RequestMapping("/greet")
    public String greet(Model model) {
        model.addAttribute("message", "Hello, Spring MVC!");
        return "greeting"; // Resolves to /WEB-INF/views/greeting.jsp
    }
}
```

---

## @Controller and @RequestMapping

### Controller Annotation

The `@Controller` annotation identifies a class as a Spring MVC component responsible for handling HTTP requests. It is typically paired with `@RequestMapping` (or its HTTP-specific variants like `@GetMapping`, `@PostMapping`) to map URLs to handler methods.

### Request Mapping Variants

`@RequestMapping` supports HTTP methods via the `method` attribute. Modern alternatives like `@GetMapping`, `@PostMapping`, etc., provide type-safe mapping.

```java
@Controller
public class ProductController {
    @GetMapping("/products")
    public String listProducts(Model model) {
        model.addAttribute("products", productService.findAll());
        return "products/list";
    }

    @PostMapping("/products")
    public String createProduct(@ModelAttribute Product product) {
        productService.save(product);
        return "redirect:/products";
    }
}
```

**Why use `@GetMapping` over `@RequestMapping`?**  
Type-safe HTTP method annotations improve readability and reduce configuration errors. They also enforce intent, making code self-documenting.

---

## Model and View

### The Model Object

The `Model` interface is used to populate data for the view. It acts as a map, storing key-value pairs that the view can access. For example, in Thymeleaf templates, `model.addAttribute("user", user)` allows access via `{{ user.name }}`.

```java
@GetMapping("/user/{id}")
public String getUser(@PathVariable Long id, Model model) {
    User user = userService.findById(id);
    model.addAttribute("user", user); // Available in view as "user"
    return "user/profile";
}
```

**Best Practice:**  
Avoid overloading the model with unnecessary data. Use `@ModelAttribute` methods to pre-populate shared attributes.

### View Resolution

Views are resolved using a `ViewResolver`, which maps logical view names (e.g., `user/profile`) to physical resources (e.g., JSP files, Thymeleaf templates). For example:

```java
@Configuration
@EnableWebMvc
public class WebConfig implements WebMvcConfigurer {
    @Bean
    public ViewResolver viewResolver() {
        InternalResourceViewResolver resolver = new InternalResourceViewResolver();
        resolver.setPrefix("/WEB-INF/views/");
        resolver.setSuffix(".jsp");
        return resolver;
    }
}
```

---

## DispatcherServlet: The Front Controller

The `DispatcherServlet` is the central servlet in Spring MVC. It initializes the application context and delegates request handling to controllers. It is configured in `web.xml` or via Java-based configuration.

### Configuration Example (Java Config)

```java
@Configuration
@EnableWebMvc
@ComponentScan("com.example.controller")
public class WebConfig implements WebMvcConfigurer {
    // Additional configuration (e.g., view resolvers, static resources)
}
```

**Why is `DispatcherServlet` critical?**  
It acts as a front controller, ensuring consistent request processing and integrating with other Spring features like security, transactions, and caching.

---

## Best Practices

### Production-Ready Patterns

1. **Separation of Concerns:**  
   Keep controllers focused on request handling. Delegate business logic to service layers and data access to repositories.

2. **Validation and Error Handling:**  
   Use `@Valid` for input validation and `@ControllerAdvice` for global exception handling.

   ```java
   @PostMapping("/submit")
   public String submitForm(@Valid @ModelAttribute Form form, BindingResult result) {
       if (result.hasErrors()) {
           return "form";
       }
       return "success";
   }
   ```

3. **REST Integration:**  
   Use `@RestController` for REST APIs, which combines `@Controller` and `@ResponseBody`. This avoids manual view resolution.

   ```java
   @RestController
   public class ProductRestController {
       @GetMapping("/api/products")
       public List<Product> getAllProducts() {
           return productService.findAll();
       }
   }
   ```

4. **Security:**  
   Integrate with Spring Security to enforce authorization and protect against CSRF attacks.

---

## Troubleshooting Common Issues

### 404 Errors

- **Cause:** Misconfigured `@RequestMapping` paths or incorrect view names.
- **Fix:**  
  - Use logging to trace request mappings (`spring.mvc.log-resolved-controllers=true`).
  - Verify view resolver prefixes/suffixes match template locations.

### View Resolution Failures

- **Cause:** Missing view templates or incorrect resolver configuration.
- **Fix:**  
  - Ensure JSPs or Thymeleaf templates exist in the configured directory.
  - Use `InternalResourceViewResolver` for JSPs or `ThymeleafViewResolver` for Thymeleaf.

### Model Attribute Conflicts

- **Cause:** Reusing model attribute names across controllers.
- **Fix:**  
  - Use unique attribute names or `@ModelAttribute` methods to pre-load data.

---

## Cross-Platform Comparisons

### Spring MVC vs. Servlets

| Feature                | Servlet                      | Spring MVC                          |
|------------------------|------------------------------|-------------------------------------|
| **Request Handling**   | Manual URL mapping           | Annotation-based routing            |
| **Dependency Injection**| Not supported                | Built-in via Spring context         |
| **Testability**        | Hard to mock                 | Easy with `MockMvc`                 |
| **Error Handling**     | Manual                       | `@ControllerAdvice` and `@ExceptionHandler` |

### Spring MVC vs. Spring WebFlux

- **Spring MVC:** Synchronous, blocking I/O (suitable for traditional web apps).
- **Spring WebFlux:** Asynchronous, non-blocking (ideal for reactive systems with high concurrency).

---

## Use Cases

### Web Form Handling

A typical user registration flow involves:
1. Displaying a form (`@GetMapping`).
2. Validating and saving data (`@PostMapping`).
3. Redirecting to a confirmation page.

```java
@GetMapping("/register")
public String showForm(Model model) {
    model.addAttribute("user", new User());
    return "register";
}

@PostMapping("/register")
public String registerUser(@Valid @ModelAttribute User user, BindingResult result) {
    if (result.hasErrors()) {
        return "register";
    }
    userService.save(user);
    return "redirect:/welcome";
}
```

### REST API Integration

While Spring MVC supports REST, consider using `@RestController` for APIs. For example:

```java
@RestController
@RequestMapping("/api/orders")
public class OrderRestController {
    @GetMapping("/{id}")
    public Order getOrder(@PathVariable Long id) {
        return orderService.findById(id);
    }
}
```

---

## Conclusion

Spring MVC provides a robust foundation for building enterprise-grade web applications. By leveraging annotations like `@Controller`, `@RequestMapping`, and `Model`, developers can create maintainable, testable, and scalable applications. Understanding the role of `DispatcherServlet` and adhering to best practices such as separation of concerns and global error handling ensures production readiness. For REST APIs, integrating Spring MVC with `@RestController` offers a seamless transition between traditional and modern web development paradigms.