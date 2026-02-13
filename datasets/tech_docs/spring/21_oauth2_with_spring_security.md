# OAuth2 with Spring Security

OAuth2 is a widely adopted protocol for authorization, enabling third-party applications to access user resources without exposing credentials. In enterprise Java applications, Spring Security provides robust support for implementing OAuth2, both as an authorization server and a resource server. This guide will explain how to configure and implement OAuth2 in Spring Security, focusing on key concepts like authorization servers, resource servers, OAuth2 flows, and PKCE, along with practical code examples and best practices.

---

## Authorization Server and Resource Server

OAuth2 separates the responsibilities of an **authorization server**, which issues access tokens, and a **resource server**, which hosts protected resources and validates tokens. Spring Security provides both options, leveraging Spring Boot auto-configuration and the Spring Authorization Server project for full control.

### Authorization Server (Spring Authorization Server)

Spring Authorization Server (introduced in Spring Security 5.7) allows developers to build a full-fledged OAuth2 authorization server. It supports standard flows like Authorization Code, Client Credentials, and PKCE.

#### Key Concepts:
- **Client Registration**: Applications must register as clients with the authorization server.
- **Scopes and Roles**: Determine the level of access granted.
- **Token Store**: Stores issued tokens, typically using a relational database or in-memory store during development.
- **Token Introspection**: Verifying the validity of a token post-issuance.

#### Configuration Example:

```java
@Configuration
@EnableAuthorizationServer
public class AuthorizationServerConfig extends AuthorizationServerConfigurerAdapter {

    @Autowired
    private AuthenticationManager authenticationManager;

    @Override
    public void configure(ClientDetailsServiceConfigurer clients) throws Exception {
        clients.inMemory()
                .withClient("my-client")
                .secret("{noop}my-secret")
                .authorizedGrantTypes("authorization_code", "refresh_token", "password")
                .scopes("read", "write")
                .redirectUris("http://localhost:8080/login/oauth2/code/my-client")
                .autoApprove(true);
    }

    @Override
    public void configure(AuthorizationServerSecurityConfigurer security) throws Exception {
        security.tokenKeyAccess("permitAll()")
                .checkTokenAccess("isAuthenticated()");
    }

    @Override
    public void configure(AuthorizationServerEndpointsConfigurer endpoints) throws Exception {
        endpoints.authenticationManager(authenticationManager);
    }
}
```

> **Tip**: `{noop}` indicates the password is stored in plaintext for simplicity. In production, use a secure password encoding strategy like `PasswordEncoder` (e.g., BCrypt).

---

### Resource Server

A resource server validates tokens issued by the authorization server. Spring Security simplifies this by using the `@EnableResourceServer` annotation or newer `SecurityFilterChain` configurations with `OAuth2ResourceServerConfigurer`.

#### Example with `SecurityFilterChain`:

```java
@Configuration
@EnableWebSecurity
public class ResourceServerConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/api/**")
                .authenticated()
                .anyRequest().permitAll()
            )
            .oauth2ResourceServer(OAuth2ResourceServerConfigurer::jwt);
        return http.build();
    }
}
```

> **Best Practice**: Always validate tokens using signed JWTs (JSON Web Tokens) and ensure token introspection is performed against a secure endpoint.

---

## OAuth2 Flows and PKCE

OAuth2 defines several flows, each suited to different client types and use cases. For web-based and mobile clients, the **PKCE (Proof Key for Code Exchange)** flow is recommended, especially for public clients that cannot securely store secrets.

### Authorization Code Flow with PKCE

PKCE adds an extra layer of security by generating a `code_verifier` and `code_challenge` to prevent authorization code interception attacks.

#### Steps:
1. Client initiates authorization request with `code_challenge`.
2. Authorization server issues an authorization code.
3. Client exchanges the code with `code_verifier` for an access token.

#### Example with Spring Security:

```java
@Configuration
@EnableWebSecurity
public class WebSecurityConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .authorizeHttpRequests(auth -> auth
                .anyRequest().authenticated()
            )
            .oauth2Login(oauth2 -> oauth2
                .clientRegistrationRepository(clientRegistrationRepository())
            );
        return http.build();
    }

    @Bean
    public ClientRegistrationRepository clientRegistrationRepository() {
        return new InMemoryClientRegistrationRepository(oauth2ClientRegistration());
    }

    private ClientRegistration oauth2ClientRegistration() {
        return ClientRegistration.withRegistrationId("my-client")
                .clientId("your-client-id")
                .clientSecret("your-client-secret")
                .clientAuthenticationMethod(ClientAuthenticationMethod.CLIENT_SECRET_BASIC)
                .authorizationGrantType(AuthorizationGrantType.AUTHORIZATION_CODE)
                .redirectUri("http://localhost:8080/login/oauth2/code/my-client")
                .scope("read", "write")
                .authorizationUri("http://auth-server.example.com/oauth2/authorize")
                .tokenUri("http://auth-server.example.com/oauth2/token")
                .userInfoUri("http://auth-server.example.com/oauth2/userinfo")
                .userNameAttributeName("sub")
                .build();
    }
}
```

> **Note**: PKCE can be enabled implicitly by configuring the client with `code_challenge_method=S256` in the client registration.

---

## Token Introspection

In some scenarios, especially when using opaque tokens, resource servers must validate tokens by calling the introspection endpoint on the authorization server. Spring Security supports this via `OpaqueTokenIntrospector`.

#### Example of Introspection Configuration:

```java
@Configuration
@EnableWebSecurity
public class OpaqueTokenResourceServerConfig {

    @Bean
    public SecurityFilterChain filterChain(HttpSecurity http) throws Exception {
        http
            .authorizeHttpRequests(auth -> auth
                .anyRequest().authenticated()
            )
            .oauth2ResourceServer(resourceServer -> resourceServer
                .opaqueToken(opaque -> opaque
                    .introspectionUri("http://auth-server.example.com/oauth2/introspect")
                    .introspectionClientCredentials("client", "secret")
                    .introspectionClient(ClientSecretCredential::new)
                )
            );
        return http.build();
    }

    private static ClientSecretCredential ClientSecretCredential(String client, String secret) {
        return () -> new BasicAuthentication(client, secret);
    }
}
```

> **Best Practice**: Always secure the introspection endpoint using mutual TLS or client credentials to prevent unauthorized token validation.

---

## Best Practices

### 1. Use HTTPS Everywhere

All communication between the client, authorization server, and resource server must be encrypted. Never expose OAuth endpoints over HTTP.

### 2. Choose the Right Flow

| Client Type | Recommended Flow |
|-------------|------------------|
| Web apps | Authorization Code + PKCE |
| Mobile apps | Authorization Code + PKCE |
| Server apps | Client Credentials |
| Legacy systems | Resource Owner Password (deprecated, use with caution) |

### 3. Token Expiration and Refresh

Ensure tokens have short expiration times and refresh tokens are used when appropriate. Avoid long-lived access tokens to minimize risk in case of token leakage.

### 4. Secure Client Secrets

Use `PasswordEncoder` to store client credentials securely. Do not hardcode secrets in source code or configuration files in production.

### 5. Logging and Monitoring

Log all authentication and authorization events, including failed attempts. Use monitoring tools like Prometheus or ELK to detect anomalies.

### 6. External Authentication Providers

Spring Security integrates with external providers like GitHub, Google, and Okta using the `OAuth2Login` feature.

```java
@Bean
public ClientRegistrationRepository clientRegistrationRepository() {
    return new InMemoryClientRegistrationRepository(googleClientRegistration());
}

private ClientRegistration googleClientRegistration() {
    return CommonOAuth2Provider.GOOGLE.getBuilder("google")
            .clientId("your-google-client-id")
            .clientSecret("your-google-client-secret")
            .build();
}
```

> **Tip**: Use `spring-security-oauth2-client` for external providers and avoid duplicating user storage.

---

## Troubleshooting Common Issues

### 1. Invalid Token Errors

- **Cause**: Expired token, invalid signature, or incorrect introspection endpoint.
- **Fix**: Validate token expiration and ensure the introspection client is correctly configured.

### 2. Missing Scopes or Authorities

- **Cause**: Client requested insufficient scopes, or the token didn't include required authorities.
- **Fix**: Ensure the client registration includes all required scopes and that the authorization server issues them.

### 3. PKCE Verification Failure

- **Cause**: Mismatch between `code_challenge` and `code_verifier`, or incorrect `code_challenge_method`.
- **Fix**: Generate `code_challenge` using the correct method (e.g., S256) and ensure it’s consistent on both ends.

---

## Cross-Framework Comparison

| Feature | Spring Security | OAuthLib (Django) | OAuth2 Server PHP |
|---------|------------------|-------------------|-------------------|
| Authorization Server | ✅ (Spring Authorization Server) | ✅ | ✅ |
| Resource Server | ✅ | ✅ | ✅ |
| PKCE Support | ✅ | ✅ | ✅ |
| Token Introspection | ✅ | ✅ | ✅ |
| Ecosystem | Enterprise-grade Java | Django-centric | PHP-focused |

Spring Security offers full stack support for OAuth2 in Java environments and integrates deeply with Spring Boot, making it a production-ready choice for Java-based microservices.

---

## Real-World Use Case: Microservices Architecture

In a microservices environment, a dedicated authorization server (e.g., using Spring Authorization Server) issues tokens that are validated by multiple resource servers. Each service is secured with Spring Security and validates incoming tokens via introspection or JWT parsing.

**Example Flow:**

1. Auth service authenticates user and issues JWT.
2. Frontend app receives token and sends it to backend services.
3. Each backend service uses Spring Security to validate the token.
4. Services extract user roles and permissions from the JWT.

This setup ensures centralized authentication and decentralized authorization, reducing coupling between services.

---

## Conclusion

OAuth2 with Spring Security is a powerful mechanism for securing modern Java applications. By understanding the roles of authorization and resource servers, choosing the right flows, and leveraging best practices like token introspection and PKCE, developers can build secure, scalable, and compliant systems.

Always validate tokens, secure client secrets, and monitor for suspicious activity. Spring Security offers extensive customization and integration options, making it suitable for enterprise-grade applications.