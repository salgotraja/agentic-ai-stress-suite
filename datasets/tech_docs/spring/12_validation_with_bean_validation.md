# Validation with Bean Validation

Bean Validation is a standard specification for validating Java objects, defined by JSR-380 (Bean Validation 2.0). It provides a declarative way to express constraints on Java objects and validate them using annotations. When combined with frameworks like Spring, it becomes a powerful tool for building robust, data-driven applications—especially REST APIs.

This guide explores key concepts such as `@Valid`, `@Validated`, validation groups, and custom validators. It includes practical examples, explains when and why to use these features, and compares them with similar patterns in other ecosystems (e.g., Python’s Pydantic).

---

## Core Concepts of Bean Validation

At the heart of Bean Validation is the ability to define constraints using annotations on fields, getter methods, or class-level methods. These annotations are processed by a validation engine, such as Hibernate Validator, which is the de facto reference implementation of JSR-380.

### Standard Constraints

Commonly used built-in constraints include:

- `@NotNull`: Ensures the field is not null.
- `@NotBlank`: Ensures the string is not empty or only whitespace.
- `@Size(min=, max=)`: Validates the size of a string, array, or collection.
- `@Min`, `@Max`: Validates numeric bounds.
- `@Pattern`: Validates strings against a regular expression.

These are applied to fields in Java objects:

```java
public class User {
    @NotBlank(message = "Name is required")
    private String name;

    @Email(message = "Invalid email format")
    private String email;

    @Min(18)
    @Max(100)
    private int age;

    // getters and setters
}
```

---

## Validation in Spring Controllers

In Spring MVC or Spring WebFlux, validation is typically triggered using `@Valid` or `@Validated` annotations in controller methods.

### Using @Valid

```java
@RestController
@RequestMapping("/users")
public class UserController {

    @PostMapping
    public ResponseEntity<String> createUser(@Valid @RequestBody User user) {
        // Business logic here
        return ResponseEntity.ok("User is valid");
    }
}
```

When `@Valid` is applied to a parameter, Spring automatically triggers validation. If any constraint is violated, a `MethodArgumentNotValidException` is thrown, which can be handled using `@ExceptionHandler`.

### Using @Validated for Service Layer Validation

`@Validated` is a Spring annotation that supports validation in the service layer and supports validation groups. It works with Spring’s AOP infrastructure.

```java
@Service
@Validated
public class UserService {

    public void registerUser(@Valid User user) {
        // Business logic
    }
}
```

To use `@Validated`, ensure you enable validation in your Spring configuration:

```java
@Configuration
@EnableWebMvc
@EnableConfigurationProperties
public class AppConfig {
}
```

---

## Validation Groups

Validation groups allow you to apply different sets of constraints depending on the validation context. For example, you might want stricter validation when creating a user than when updating.

### Define Groups

```java
public interface OnCreate {}
public interface OnUpdate {}
```

### Apply Constraints to Groups

```java
public class User {
    @NotBlank(groups = OnCreate.class)
    private String name;

    @Email(groups = OnCreate.class)
    private String email;

    @NotBlank(groups = OnUpdate.class)
    private String password;

    // getters and setters
}
```

### Use Groups in Validation

```java
@PutMapping("/update")
public ResponseEntity<String> updateUser(
    @Validated(OnUpdate.class) @RequestBody User user) {
    // Update logic
    return ResponseEntity.ok("User updated");
}
```

You can also combine multiple groups:

```java
@Validated({OnCreate.class, OnUpdate.class})
```

---

## Custom Validators

Bean Validation supports custom validation logic via `ConstraintValidator`.

### Define a Custom Constraint

```java
@Target({ ElementType.FIELD })
@Retention(RetentionPolicy.RUNTIME)
@Constraint(validatedBy = StrongPasswordValidator.class)
@Documented
public @interface StrongPassword {
    String message() default "Password is not strong enough";
    Class<?>[] groups() default {};
    Class<? extends Payload>[] payload() default {};
}
```

### Implement the Validator

```java
public class StrongPasswordValidator implements ConstraintValidator<StrongPassword, String> {

    @Override
    public boolean isValid(String password, ConstraintValidatorContext context) {
        if (password == null) return true;

        // At least 8 chars, 1 uppercase, 1 lowercase, 1 digit
        return password.length() >= 8 &&
               password.matches(".*[A-Z].*") &&
               password.matches(".*[a-z].*") &&
               password.matches(".*\\d.*");
    }
}
```

### Use in a Class

```java
public class User {
    @StrongPassword
    private String password;
}
```

---

## Error Handling and Messaging

When validation fails, Spring throws exceptions that can be handled globally:

```java
@RestControllerAdvice
public class GlobalExceptionHandler {

    @ExceptionHandler(MethodArgumentNotValidException.class)
    public ResponseEntity<Map<String, String>> handleValidationExceptions(
        MethodArgumentNotValidException ex) {

        Map<String, String> errors = new HashMap<>();
        ex.getBindingResult().getAllErrors().forEach((error) -> {
            String fieldName = ((FieldError) error).getField();
            String errorMessage = error.getDefaultMessage();
            errors.put(fieldName, errorMessage);
        });
        return ResponseEntity.badRequest().body(errors);
    }
}
```

This handler returns detailed error messages per field, which is helpful for client-side UIs.

---

## Cross-Context Validation in Spring

Validation can also be used in service methods or DAOs with `@Validated`. This ensures data integrity at multiple layers of the application.

```java
@Service
@Validated
public class UserService {

    public void register(@Valid @RequestBody User user) {
        // Additional validation logic can be added here
    }
}
```

---

## Best Practices

1. **Keep Validation Declarative**: Use annotations for clarity and maintainability.
2. **Use Groups for Context-Specific Validation**: Especially useful in REST APIs with different operations.
3. **Leverage Service Layer Validation**: Prevent invalid data from propagating through your application.
4. **Provide Clear Error Messages**: Use `message` attributes to guide users.
5. **Avoid Over-Validating**: Only validate what is necessary for your business rules.
6. **Use Custom Constraints for Repeated Logic**: Reduce duplication and improve readability.
7. **Combine with Data Transfer Objects (DTOs)**: Validate incoming DTOs before mapping to domain models.

---

## Comparison with Other Frameworks

### REST APIs (see Section 09)

In REST APIs, validation is often performed on request payloads. In Spring, this is typically done using `@Valid` in controller methods. Other frameworks, such as Express.js with Joi or FastAPI with Pydantic, also provide similar capabilities.

### Comparison with Pydantic (Python)

Pydantic offers a similar declarative validation model for Python data classes. Here's a comparison:

| Feature | Bean Validation (Java) | Pydantic (Python) |
|--------|------------------------|-------------------|
| Annotation-based | ✅ Yes | ✅ Yes |
| Custom validators | ✅ Yes | ✅ Yes |
| Validation groups | ✅ Yes (via groups) | ❌ No (but workarounds exist) |
| Built-in constraints | ✅ Yes | ✅ Yes |
| Integration with frameworks | ✅ Spring / JAX-RS | ✅ FastAPI / Starlette |

Both tools are powerful, but Pydantic is more tightly coupled with Python’s type system and async features, while Bean Validation is part of the Java EE ecosystem.

---

## Common Pitfalls and Troubleshooting

1. **Missing `@Valid` in Controller**: Forgetting `@Valid` can lead to no validation being performed.
2. **Using `@Validated` Without `@Valid`**: In the service layer, `@Validated` needs to be combined with `@Valid` on method parameters.
3. **Not Adding Validation Dependency**: Ensure `spring-boot-starter-validation` is included in the project.
4. **Ignoring Constraint Groups**: Misusing groups can lead to incorrect validation in different contexts.
5. **Not Handling Exceptions**: Failing to catch `MethodArgumentNotValidException` results in unhandled errors.
6. **Custom Validator Not Registered**: Ensure custom validators are properly annotated and used.
7. **Overusing `@Valid` in Large Objects**: Can lead to performance issues in deeply nested objects.

---

## Real-World Use Case: User Registration API

Consider a user registration API with multiple validation requirements:

1. Name must be non-empty.
2. Email must be valid and unique.
3. Password must be strong.
4. Age must be between 18 and 100.

### User DTO

```java
public class RegisterUserRequest {
    @NotBlank(message = "Name is required")
    private String name;

    @Email(message = "Invalid email format")
    private String email;

    @StrongPassword
    private String password;

    @Min(18)
    @Max(100)
    private int age;

    // getters and setters
}
```

### Service Layer

```java
@Service
@Validated
public class UserService {

    public void registerUser(@Valid RegisterUserRequest request) {
        // Business logic
    }
}
```

### Controller

```java
@RestController
@RequestMapping("/api/users")
public class UserController {

    @Autowired
    private UserService userService;

    @PostMapping("/register")
    public ResponseEntity<String> register(@Valid @RequestBody RegisterUserRequest request) {
        userService.registerUser(request);
        return ResponseEntity.ok("User registered successfully");
    }
}
```

---

## Conclusion

Bean Validation is a cornerstone of enterprise Java applications, especially when building REST APIs. It allows developers to express constraints declaratively and enforce data integrity across layers. By leveraging built-in and custom constraints, validation groups, and Spring’s `@Validated`, you can build robust, maintainable applications.

Compared to tools like Pydantic in Python, Bean Validation offers similar expressive power but integrates deeply with the Java ecosystem. Whether validating incoming data in controllers or enforcing business rules in services, validation should be a core part of your application architecture.

Always follow best practices: use groups, provide clear error messages, and combine validation with validation-aware exception handling.