# Transaction Management

Transaction management is a fundamental aspect of enterprise application development, ensuring data integrity and consistency in the face of concurrent operations or system failures. In the context of the Spring Framework, transactions are declaratively managed using annotations like `@Transactional`, with fine-grained control over propagation, isolation, and rollback behavior. Understanding how to define transaction boundaries, handle distributed transactions, and apply rollback rules is essential for building robust and scalable applications.

## Core Concepts

### What is a Transaction?

A database transaction is a sequence of operations performed as a single logical unit of work. The ACID properties—Atomicity, Consistency, Isolation, and Durability—define the guarantees transactions provide:

- **Atomicity**: All operations in the transaction succeed, or none do.
- **Consistency**: A transaction transforms the system from one consistent state to another.
- **Isolation**: Concurrent transactions do not interfere with each other.
- **Durability**: Once committed, a transaction's changes are permanent.

### Key Concepts in Spring Transaction Management

| Concept            | Description |
|-------------------|-------------|
| `@Transactional` | Annotation that marks a method or class as transactional |
| Propagation       | Defines how transactions are created or joined when a method is invoked |
| Isolation         | Controls how transactions interact with each other |
| Rollback Rules    | Specifies conditions under which a transaction should roll back |

---

## Transaction Propagation

Propagation defines how transactions behave when a method annotated with `@Transactional` calls another transactional method. Spring supports several propagation levels, each with specific use cases.

### Common Propagation Levels

| Level               | Description |
|---------------------|-------------|
| `REQUIRED` (default) | Use existing transaction or start a new one |
| `REQUIRES_NEW`       | Always start a new transaction, suspending the current one |
| `NEVER`              | Method must not be called in a transactional context |
| `NOT_SUPPORTED`    | Execute without a transaction, suspending the current one if active |
| `MANDATORY`        | Method must run within an existing transaction |

### Example: Propagation in Action

```java
@Service
public class OrderService {

    @Autowired
    private OrderRepository orderRepository;

    @Autowired
    private PaymentService paymentService;

    @Transactional(propagation = Propagation.REQUIRED)
    public void createOrder(Order order) {
        order.setId(UUID.randomUUID().toString());
        order.setStatus("PROCESSING");
        orderRepository.save(order);

        // This call will run in the same transaction
        paymentService.recordPayment(order);
    }
}
```

In this example, if `recordPayment` is annotated with `@Transactional(propagation = Propagation.REQUIRES_NEW)`, it will run in its own transaction, independent of the transaction in `createOrder`.

### When to Use Which Propagation Level

- Use `REQUIRED` for most service methods to ensure a transaction exists.
- Use `REQUIRES_NEW` for operations that must be isolated, such as logging or audit trails.
- Use `MANDATORY` to enforce that a method must be called in a transactional context.
- Use `NEVER` or `NOT_SUPPORTED` for read-only operations that do not require transactional guarantees.

---

## Transaction Isolation Levels

Isolation levels determine how transactions interact with one another, especially regarding visibility and modification of uncommitted data.

| Level               | Behavior |
|---------------------|----------|
| `READ_UNCOMMITTED`  | Allows dirty reads, non-repeatable reads, and phantom reads |
| `READ_COMMITTED`    | Prevents dirty reads but allows non-repeatable reads and phantom reads |
| `REPEATABLE_READ`   | Prevents dirty reads and non-repeatable reads but allows phantom reads |
| `SERIALIZABLE`      | Prevents all types of concurrency issues but has the worst performance |

### Example: Setting Isolation Level

```java
@Transactional(isolation = Isolation.READ_COMMITTED)
public void updateInventory(Product product, int quantity) {
    product.setStock(product.getStock() - quantity);
    productRepository.save(product);
}
```

This ensures the method only works with committed data, avoiding potential dirty reads.

### Choosing the Right Isolation Level

- Use `READ_COMMITTED` as a balance between performance and correctness in most business applications.
- Use `REPEATABLE_READ` in read-heavy applications where data consistency is critical.
- Use `SERIALIZABLE` only when absolute consistency is required and performance is not a concern.

---

## Transaction Rollback Rules

By default, Spring rolls back on unchecked exceptions (`RuntimeException` and its subclasses) but does not on checked exceptions. This behavior can be customized using the `rollbackFor` and `noRollbackFor` attributes of the `@Transactional` annotation.

### Example: Custom Rollback Rules

```java
@Transactional(rollbackFor = InvalidPaymentException.class)
public void processOrder(Order order) throws InvalidPaymentException {
    if (!isValidPayment(order.getPayment())) {
        throw new InvalidPaymentException("Payment is invalid");
    }
    order.setStatus("PAID");
    orderService.save(order);
}
```

In this example, a custom exception (`InvalidPaymentException`) will trigger a rollback.

### Best Practices for Rollback Rules

- Define rollback rules based on business logic, not just technical exceptions.
- Use `rollbackFor = Exception.class` if you want to roll back on all exceptions.
- Avoid using `noRollbackFor` unless you have an explicit reason to allow the transaction to commit on certain exceptions.

---

## Transaction Boundaries and Service Layer Design

Transaction boundaries should generally be defined at the service layer, not the repository layer. This ensures that business operations are atomic and transactional, while data access operations remain decoupled and reusable.

### Example: Service Layer Transaction

```java
@Service
public class UserService {

    @Autowired
    private UserRepository userRepository;

    @Autowired
    private AuditLogRepository auditLogRepository;

    @Transactional
    public void updateUserProfile(User user) {
        userRepository.save(user);

        // This call will join the existing transaction
        auditLogRepository.log("User profile updated", user.getId());
    }
}
```

Here, both `userRepository.save()` and `auditLogRepository.log()` operate within the same transactional context. If either operation fails, the entire transaction rolls back.

---

## Distributed Transactions

In microservices or distributed applications, transactions may span multiple databases or services. Spring supports distributed transactions using the Java Transaction API (JTA) and the `@Transactional` annotation in combination with a transaction manager like Atomikos or Bitronix.

### Example: Distributed Transaction with JTA

```java
@Service
public class OrderProcessingService {

    @Autowired
    private OrderRepository orderRepository;

    @Autowired
    private InventoryService inventoryService;

    @Transactional
    public void placeOrder(Order order) {
        order.setStatus("PLACED");
        orderRepository.save(order);

        // Call to external service (should be in same transaction if JTA is enabled)
        inventoryService.reserveInventory(order.getProductId(), order.getQuantity());
    }
}
```

This example assumes that both the local database and the `inventoryService` are part of the same JTA transaction. Spring Boot supports JTA through the `spring-boot-starter-jta` module.

### Best Practices for Distributed Transactions

- Only use JTA when you need true atomicity across resources.
- Prefer eventual consistency for performance-critical systems.
- Use sagas or compensating transactions for long-running operations across services.
- Ensure all resources participating in a transaction support XA (two-phase commit).

---

## Cross-Reference with Spring Data JPA

Spring Data JPA leverages Spring’s transaction management capabilities to provide a clean abstraction over JPA (Java Persistence API). It supports declarative transactions through `@Transactional` and can handle propagation and isolation levels directly.

### Example: Spring Data JPA with Transaction

```java
@Repository
public interface UserRepository extends JpaRepository<User, String> {

    @Transactional(propagation = Propagation.REQUIRED)
    @Modifying
    @Query("UPDATE User u SET u.status = 'INACTIVE' WHERE u.lastLogin < :threshold")
    int deactivateInactiveUsers(@Param("threshold") LocalDateTime threshold);
}
```

This example shows how `@Transactional` can be used directly on a repository method to manage JPA updates.

### Integration with Spring Boot

In Spring Boot, transactions are automatically managed by the `PlatformTransactionManager`. You can configure JPA and transaction settings in `application.properties`:

```properties
spring.datasource.url=jdbc:mysql://localhost:3306/mydb
spring.datasource.username=root
spring.datasource.password=secret
spring.jpa.hibernate.ddl-auto=update
spring.jpa.show-sql=true
spring.jpa.properties.hibernate.transaction.jta.platform=org.hibernate.service.jta.platform.internal.NoJtaPlatform
```

---

## Best Practices for Transaction Management

1. **Keep transactions short and coarse-grained**: Long-running transactions can lead to deadlocks and performance issues.
2. **Avoid transactional methods in repositories**: Keep transaction boundaries at the service layer.
3. **Use `@Transactional` on methods, not classes**: This gives you more control over which methods are transactional.
4. **Be aware of proxy-based limitations**: `@Transactional` only works on public methods, as Spring uses proxies.
5. **Use `@Transactional(readOnly = true)` for read operations**: This helps optimize performance and enforce immutability.
6. **Avoid mixing transactional and non-transactional logic in the same method**: This can lead to unexpected behavior.
7. **Test transactions with real databases**: Mocking transactions can hide concurrency issues.

---

## Troubleshooting and Common Pitfalls

### 1. Transaction Not Rolled Back

**Symptom**: Data is written to the database even though an exception was thrown.

**Solution**: Ensure that the exception is a `RuntimeException` or that you explicitly define `rollbackFor`.

### 2. Transaction Already Active

**Symptom**: `Transaction Rolled back because it has been marked as rollback-only` or `Transaction synchronization is not active`.

**Cause**: Conflicting propagation levels or multiple transaction managers.

**Solution**: Review propagation settings and ensure consistency in transaction boundaries.

### 3. Lazy Initialization Exception

**Symptom**: `LazyInitializationException` when accessing lazy collections outside a transaction.

**Cause**: Hibernate proxies are used, and the session is closed.

**Solution**: Either:
- Fetch eagerly using `@EntityGraph` or `JOIN FETCH`
- Access lazy fields within a transactional context
- Use `OpenSessionInView` (not recommended for production)

---

## Conclusion

Transaction management is essential for maintaining data consistency and reliability in enterprise applications. With Spring Framework, the `@Transactional` annotation, along with propagation, isolation, and rollback rules, provides a powerful and flexible way to manage transactions declaratively.

Effective use of transaction boundaries, careful selection of isolation levels, and understanding rollback semantics are key to building resilient and maintainable systems. When working with Spring Data JPA or distributed systems, it’s important to align transaction strategies with business requirements and system architecture.

By following best practices and understanding the underlying mechanics, senior engineers can design transactional systems that are performant, scalable, and reliable.