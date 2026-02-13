# TestContainers Integration

TestContainers is a powerful Java library that supports JUnit tests, providing lightweight, throwaway instances of common databases, Selenium web browsers, or any other software that can run in a Docker container. It's particularly useful in integration testing scenarios where an actual running instance of a database or other infrastructure component is needed without relying on an external environment.

For enterprise Java applications—especially those built with Spring Framework—TestContainers offers a robust way to achieve **Docker-based testing**, ensuring that tests are reproducible, isolated, and realistic. This document focuses on how to integrate TestContainers with Spring Boot for **database testing**, and explores best practices for **test isolation**, real-world usage, and integration patterns.

## Core Concepts

### What is TestContainers?

TestContainers is not a testing framework itself but a library that extends JUnit with capabilities to manage Docker containers during test execution. It wraps Docker containers into Java objects, allowing you to start, configure, and tear down containers programmatically.

### Docker-based Testing

Docker-based testing ensures that tests run in an environment that closely mirrors production, using real services instead of mocks or stubs. This approach reduces the risk of integration errors that can occur when tests run against simulated systems.

### Database Testing with TestContainers

When testing Spring Boot applications that rely on a relational database, such as PostgreSQL, TestContainers allows you to spin up a **real PostgreSQL instance** for each test or test suite. This ensures that database-specific behaviors—like transaction management, schema constraints, or query optimizations—are tested accurately.

## Setting Up TestContainers

To use TestContainers in a Spring Boot project, add the following dependencies to your `pom.xml`:

```xml
<dependency>
    <groupId>org.testcontainers</groupId>
    <artifactId>testcontainers</artifactId>
    <version>1.19.0</version>
    <scope>test</scope>
</dependency>
<dependency>
    <groupId>org.testcontainers</groupId>
    <artifactId>junit-jupiter</artifactId>
    <version>1.19.0</version>
    <scope>test</scope>
</dependency>
<dependency>
    <groupId>org.testcontainers</groupId>
    <artifactId>postgresql</artifactId>
    <version>1.19.0</version>
    <scope>test</scope>
</dependency>
```

Ensure Docker is running on your machine. For CI environments, confirm that Docker is available and properly configured with the correct permissions.

## Creating a PostgreSQL TestContainer

To create a PostgreSQL container for testing, use the `PostgreSQLContainer` class provided by TestContainers. Here’s a typical setup using JUnit 5:

```java
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.extension.RegisterExtension;
import org.springframework.jdbc.core.JdbcTemplate;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.Testcontainers;

@Testcontainers
public class PostgresTestContainerTest {

    @Container
    static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:15")
            .withDatabaseName("testdb")
            .withUsername("testuser")
            .withPassword("testpass");

    @Test
    public void testDatabaseConnection() {
        String jdbcUrl = postgres.getJdbcUrl();
        String username = postgres.getUsername();
        String password = postgres.getPassword();

        JdbcTemplate jdbcTemplate = new JdbcTemplate(
            new org.springframework.jdbc.datasource.DriverManagerDataSource(jdbcUrl, username, password)
        );

        jdbcTemplate.execute("SELECT 1;");
    }
}
```

In this example, the PostgreSQL container is started once for all test methods due to the `static` modifier. It connects using the actual credentials defined in the container, and the `JdbcTemplate` is used to execute a simple query.

> **Note:** The `@Testcontainers` annotation is essential to instruct JUnit to manage the lifecycle of the container.

## Configuring Spring Boot to Use TestContainer Database

To configure a Spring Boot application to use the TestContainer database during integration tests, override the default configuration in a test-specific configuration class or file.

```java
import org.springframework.boot.test.context.TestConfiguration;
import org.springframework.context.annotation.Bean;
import org.springframework.jdbc.datasource.DriverManagerDataSource;
import org.springframework.boot.jdbc.DataSourceBuilder;

import javax.sql.DataSource;

@TestConfiguration
public class TestPostgresConfig {

    public static PostgreSQLContainer<?> postgres = new PostgreSQLContainer<>("postgres:15")
            .withDatabaseName("testdb")
            .withUsername("testuser")
            .withPassword("testpass");

    static {
        postgres.start();
    }

    @Bean
    public DataSource dataSource() {
        return DataSourceBuilder.create()
                .url(postgres.getJdbcUrl())
                .username(postgres.getUsername())
                .password(postgres.getPassword())
                .build();
    }
}
```

In this configuration, the `dataSource()` method provides a real `DataSource` connected to the PostgreSQL container. Spring Boot will use this instead of any configuration from `application.properties`.

> **Best Practice:** Use `@TestConfiguration` in test classes or in test-specific configuration files to override beans. This ensures that the same configuration is used across all integration tests.

## Test Isolation and Lifecycle Management

TestContainers supports both **per-test** and **per-suite** container lifecycles. Per-test isolation is useful for ensuring that each test runs in a clean environment, but it can be resource-intensive.

Here's an example of a container that is started and destroyed for each test method:

```java
import org.junit.jupiter.api.Test;
import org.testcontainers.containers.PostgreSQLContainer;
import org.testcontainers.junit.jupiter.Testcontainers;
import org.testcontainers.junit.jupiter.Container;
import org.testcontainers.junit.jupiter.TestContainer;

@Testcontainers
public class PerTestIsolationTest {

    @Container
    PostgreSQLContainer<?> perTestDb = new PostgreSQLContainer<>("postgres:15")
            .withDatabaseName("per-test")
            .withUsername("peruser")
            .withPassword("perpass");

    @Test
    public void testOne() {
        String url = perTestDb.getJdbcUrl();
        System.out.println("Test one using URL: " + url);
    }

    @Test
    public void testTwo() {
        String url = perTestDb.getJdbcUrl();
        System.out.println("Test two using URL: " + url);
    }
}
```

Each test method gets a fresh instance of the database container, which can help isolate side effects and reduce test coupling. However, for faster execution, prefer **per-class** or **per-suite** containers unless strict isolation is required.

## Real-World Use Case: Integration Testing with Spring Data JPA

TestContainers is often used in Spring Data JPA integration tests to simulate a real database environment. Here's a complete example using `@SpringBootTest` and a custom configuration class:

```java
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.orm.jpa.DataJpaTest;
import org.springframework.boot.test.autoconfigure.orm.jpa.TestEntityManager;

import static org.assertj.core.api.Assertions.assertThat;

@DataJpaTest
public class UserRepositoryTest {

    @Autowired
    private TestEntityManager entityManager;

    @Autowired
    private UserRepository userRepository;

    @Test
    public void whenSaveUser_thenRetrieveUser() {
        User user = new User("John Doe", "john@example.com");
        entityManager.persist(user);
        entityManager.flush();

        User found = userRepository.findById(user.getId()).orElse(null);
        assertThat(found).isNotNull();
        assertThat(found.getName()).isEqualTo("John Doe");
    }
}
```

The `@DataJpaTest` annotation disables full Spring Boot auto-configuration and only loads JPA-related configurations. This test uses a real PostgreSQL container instead of an in-memory database like H2, providing more accurate results.

## Best Practices

### 1. Use Static Containers for Shared Resources

When multiple test classes or test suites require the same database container, use a static container that is started once and reused across tests. This reduces startup time and conserves resources.

### 2. Avoid Overhead with Lightweight Test Containers

Use `@Testcontainers` judiciously. For simple tests that don’t require external services, consider using in-memory databases (e.g., H2) to speed up test execution.

### 3. Clean Up After Tests

Ensure containers are properly closed after all tests complete. TestContainers provides a `@DirtiesContext` annotation or `@AfterAll` methods to manage this.

### 4. Use Custom Docker Images for Consistency

If your application requires a specific version or configuration of a database, consider creating a custom Docker image and referencing it in your test container setup to ensure consistency across environments.

### 5. Enable Debug Logging for Troubleshooting

When debugging test failures related to TestContainers, enable debug logging by adding the following to your `application.properties`:

```properties
logging.level.org.testcontainers=DEBUG
```

This can help identify issues such as container startup failures or port conflicts.

## Common Pitfalls and Troubleshooting

### 1. Docker Not Running

Ensure Docker is running before executing tests. On CI systems, configure Docker to run in background mode or use Docker-in-Docker setups.

### 2. Port Conflicts

TestContainers automatically maps container ports to available host ports. However, if you manually specify ports in your configuration, ensure they are not already in use.

### 3. Slow Test Startup

If tests are slow to start, try using **per-test isolation** only when necessary. Otherwise, reuse a shared container across tests to reduce startup overhead.

### 4. Incorrect JDBC URL or Credentials

Always use container-provided values for JDBC URLs and credentials. Hardcoding values can lead to mismatches if the container is rebuilt with different settings.

## Cross-Framework Comparison

Compared to traditional mocking (e.g., Mockito) or in-memory databases (e.g., H2), TestContainers provides a higher degree of realism in integration tests. While mocks and in-memory databases are faster, they may not accurately reflect the behavior of real systems—especially in cases involving database constraints, transaction isolation levels, or query performance.

| Approach | Pros | Cons |
|--------|------|------|
| TestContainers | Realistic environment, accurate results | Slower setup, requires Docker |
| H2 In-Memory DB | Fast, no Docker required | May not support real DB features |
| Mockito | Fast, lightweight | Only suitable for unit tests |

## Conclusion

Integrating TestContainers into Spring Boot projects enables developers to write robust integration tests that closely simulate production environments. By using Docker-based containers, you can ensure that tests are consistent, isolated, and reliable. Whether testing database interactions, message queues, or web services, TestContainers provides a flexible and powerful toolset for enterprise Java testing.

By following best practices such as static container reuse, proper lifecycle management, and real-world test scenarios, teams can significantly improve the quality and reliability of their test suites.