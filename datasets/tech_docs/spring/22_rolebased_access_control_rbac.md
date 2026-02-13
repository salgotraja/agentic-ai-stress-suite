# Role-Based Access Control (RBAC)

Role-Based Access Control (RBAC) is a security model that restricts access to resources based on the user's role within an organization. It provides a structured method for assigning permissions, simplifying access management and reducing administrative overhead. RBAC is commonly used in enterprise applications to enforce fine-grained authorization policies at both the application and method levels. In the context of the Spring Framework, particularly Spring Security, RBAC is implemented using annotations such as `@PreAuthorize`, `@Secured`, and through configuration of role hierarchies.

## Core Concepts of RBAC in Spring Security

RBAC in Spring Security revolves around the idea of defining roles and granting permissions to those roles. Each user is assigned one or more roles, and permissions are granted based on the roles they hold. This model provides a flexible and scalable way to manage access control.

### Key Concepts

- **Roles**: Logical groupings of permissions. For example, `ROLE_ADMIN` or `ROLE_USER`.
- **Permissions**: Specific actions allowed on a resource, such as `READ`, `WRITE`, or `DELETE`.
- **Role Hierarchies**: A way to define parent-child relationships between roles, enabling inheritance of permissions.
- **Method Security**: Authorization checks enforced at the method level using annotations like `@PreAuthorize` and `@Secured`.

### Cross-References
RBAC is closely tied to **Authorization** in Spring Security and is often discussed alongside broader Spring security features like authentication, access control, and expression-based security. It is also important to understand the integration with the **Spring Framework**, which provides the context and dependency injection capabilities needed for method-level security.

---

## Implementing RBAC with Spring Security

To implement RBAC in Spring Security, you typically use a combination of annotations and configuration.

### Enabling Method-Level Security

To use annotations like `@PreAuthorize` and `@Secured`, you must first enable method-level security in your Spring configuration:

```java
@Configuration
@EnableWebSecurity
@EnableMethodSecurity
public class SecurityConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .authorizeHttpRequests(auth -> auth
                .anyRequest().authenticated()
            )
            .formLogin(Customizer.withDefaults());
        return http.build();
    }

    @Bean
    public UserDetailsService userDetailsService() {
        UserDetails user = User.withDefaultPasswordEncoder()
            .username("user")
            .password("password")
            .roles("USER")
            .build();

        UserDetails admin = User.withDefaultPasswordEncoder()
            .username("admin")
            .password("admin")
            .roles("ADMIN")
            .build();

        return new InMemoryUserDetailsManager(user, admin);
    }
}
```

This configuration enables basic authentication and method-level security using Spring Security’s `@EnableMethodSecurity` annotation.

---

## Using @PreAuthorize and @Secured

Both `@PreAuthorize` and `@Secured` are used to enforce access control at the method level. However, they differ in flexibility and capabilities.

### @PreAuthorize

`@PreAuthorize` is more powerful and supports SpEL (Spring Expression Language), allowing for complex authorization logic.

#### Example: Role-Based Method Security

```java
@Service
public class DocumentService {

    @PreAuthorize("hasRole('ADMIN') or hasPermission(#documentId, 'document', 'read')")
    public Document getDocument(String documentId) {
        // Fetch document from DB
        return new Document(documentId, "Secret content");
    }

    @PreAuthorize("hasRole('ADMIN') and hasPermission(#documentId, 'document', 'write')")
    public void updateDocument(String documentId, String content) {
        // Update document
    }
}
```

In this example:
- `hasRole('ADMIN')` checks if the user has the `ADMIN` role.
- `hasPermission(...)` is a more advanced SpEL expression that checks for specific permissions on a resource.

### @Secured

The `@Secured` annotation is simpler and does not support SpEL. It checks only role-based access.

```java
@Service
@Secured("ROLE_ADMIN")
public class AdminService {

    public void sensitiveOperation() {
        // Only accessible by users with ROLE_ADMIN
    }
}
```

> **Note**: `@Secured` checks roles directly, such as `ROLE_ADMIN`, and not role prefixes, even if you use `hasRole('ADMIN')`. It is less flexible than `@PreAuthorize`.

---

## Role Hierarchies in Spring Security

Role hierarchies allow you to define parent-child relationships between roles. For example, `ROLE_ADMIN` may be a parent of `ROLE_EDITOR`, which may be a parent of `ROLE_USER`.

This can be configured using a `RoleHierarchy` bean:

```java
@Bean
public RoleHierarchy roleHierarchy() {
    RoleHierarchyImpl hierarchy = new RoleHierarchyImpl();
    String hierarchyString = "ROLE_ADMIN > ROLE_EDITOR > ROLE_USER";
    hierarchy.setHierarchy(hierarchyString);
    return hierarchy;
}
```

With this setup, a user with `ROLE_EDITOR` will automatically inherit the permissions of `ROLE_USER`.

This is especially useful in large applications where managing access for many roles can become complex. It avoids the need to duplicate permissions and makes role management more scalable.

---

## Practical Use Cases

### 1. Role-Based API Endpoints

You can protect REST endpoints using Spring Security annotations or global method-level security.

```java
@RestController
@RequestMapping("/api/documents")
@PreAuthorize("hasRole('ADMIN') or hasRole('EDITOR') or hasRole('USER')")
public class DocumentController {

    private final DocumentService documentService;

    public DocumentController(DocumentService documentService) {
        this.documentService = documentService;
    }

    @GetMapping("/{id}")
    public ResponseEntity<Document> getDocument(@PathVariable String id) {
        return ResponseEntity.ok(documentService.getDocument(id));
    }

    @PostMapping
    @PreAuthorize("hasRole('EDITOR') or hasRole('ADMIN')")
    public ResponseEntity<Document> createDocument(@RequestBody Document document) {
        return ResponseEntity.ok(documentService.createDocument(document));
    }

    @DeleteMapping("/{id}")
    @PreAuthorize("hasRole('ADMIN')")
    public ResponseEntity<Void> deleteDocument(@PathVariable String id) {
        documentService.deleteDocument(id);
        return ResponseEntity.noContent().build();
    }
}
```

This example shows how different HTTP methods can be secured differently based on roles.

### 2. Conditional Access Based on User Data

SpEL with `@PreAuthorize` allows for more fine-grained control. For instance, a user can only edit their own data.

```java
@PreAuthorize("#userId == authentication.principal.userId or hasRole('ADMIN')")
public void updateProfile(String userId, Profile profile) {
    // Update logic
}
```

This ensures that a user can only update their own profile unless they are an admin.

---

## Best Practices for RBAC in Spring

### 1. Keep Roles Simple and Meaningful

Avoid creating overly granular roles that complicate management. Instead, define roles based on responsibilities, not individual permissions.

### 2. Use @PreAuthorize for Flexibility

Whenever you need to perform complex checks or access method arguments, use `@PreAuthorize` over `@Secured`.

### 3. Combine RBAC with ABAC (Attribute-Based Access Control)

For more dynamic access control (e.g., based on user attributes like department, tenure, or location), consider combining RBAC with ABAC using SpEL in `@PreAuthorize`.

### 4. Cache Security Decisions

For performance-critical applications, enable caching of authorization checks using Spring’s `@Cacheable` or custom caching strategies.

### 5. Avoid Hardcoding Roles in Code

Store roles in a database or external configuration. This allows for dynamic role management without redeploying the application.

---

## Troubleshooting and Common Pitfalls

### 1. Missing @EnableMethodSecurity

If role checks don’t work, ensure `@EnableMethodSecurity` is added to the security configuration. Without it, annotations like `@PreAuthorize` are ignored.

### 2. Role Prefix Confusion

Spring Security automatically uses `ROLE_` as a prefix. So `hasRole('ADMIN')` checks for `ROLE_ADMIN`. Be consistent in how you define roles and avoid mixing `ROLE_ADMIN` with `ADMIN`.

### 3. Forgotten Role Hierarchy

If users with parent roles are denied access, check the role hierarchy configuration. Also, test with a hierarchy resolver to ensure inheritance is applied correctly.

### 4. Caching Issues

Authorization checks may be cached, especially in production environments. If changes to roles or permissions aren’t reflected, ensure the cache is invalidated appropriately.

---

## Comparing RBAC with Other Security Models

### RBAC vs. ABAC

- **RBAC** is ideal for applications with well-defined user roles and permissions.
- **ABAC** is better suited for applications where access depends on dynamic attributes like user location, time, or resource metadata.

### RBAC vs. ACL (Access Control List)

- **RBAC** is role-centric; **ACL** is resource-centric.
- ACLs are better for object-level permissions (e.g., individual files or database records).
- Spring Security supports both models and offers integration through `AclService`.

---

## Real-World Example: Document Management System

Imagine a system where users can view, edit, or delete documents. RBAC can be used to enforce:

- **Users** can only view documents.
- **Editors** can view and edit documents.
- **Admins** can view, edit, and delete documents.

By defining role hierarchies and applying method-level security, you can ensure that access is enforced consistently and securely across the application.

---

## Conclusion

RBAC is a powerful and scalable model for managing access control in enterprise applications. In Spring Security, it is implemented through annotations like `@PreAuthorize`, `@Secured`, and method-level security. With role hierarchies and expression-based access checks, Spring provides a rich and flexible framework for enforcing authorization policies.

By following best practices and leveraging Spring’s capabilities, you can build robust, secure applications that support complex access control requirements.