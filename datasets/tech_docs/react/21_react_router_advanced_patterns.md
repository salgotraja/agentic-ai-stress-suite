# React Router Advanced Patterns

React Router offers a robust foundation for routing in React applications. While basic routing is straightforward, advanced scenarios such as protected routes, nested routing, route guards, and dynamic routes are essential for building production-grade applications. These advanced patterns help manage complex UI structures, enforce authentication and authorization logic, and enable the creation of highly modular, scalable routing systems.

This guide delves into advanced React Router patterns and demonstrates how to implement them effectively in real-world applications. We'll cover topics such as route guards for authentication, nested routes for component organization, and dynamic route parameters for handling flexible URL structures.

---

## Protected Routes and Route Guards

A **protected route** is a route that requires the user to be authenticated before they can access it. This pattern is commonly used in applications that require login, such as dashboards or admin panels. **Route guards** are the mechanisms that enforce this access control.

React Router doesn’t provide built-in route guards, but you can implement them using higher-order components (HOCs), custom hooks, or route wrappers.

### Example: Auth Protected Route Using a Custom Hook

```tsx
import { Navigate, useLocation } from 'react-router-dom';

const useAuth = () => {
  const user = JSON.parse(localStorage.getItem('user') || 'null');
  return user;
};

const ProtectedRoute = ({ children }: { children: JSX.Element }) => {
  const isAuthenticated = useAuth();
  const location = useLocation();

  if (!isAuthenticated) {
    return <Navigate to="/login" replace state={{ from: location }} />;
  }

  return children;
};
```

### Usage in Route Definitions

```tsx
import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import Dashboard from './Dashboard';
import Login from './Login';

<Router>
  <Routes>
    <Route path="/login" element={<Login />} />
    <Route
      path="/dashboard"
      element={
        <ProtectedRoute>
          <Dashboard />
        </ProtectedRoute>
      }
    />
  </Routes>
</Router>;
```

### Why and When to Use Protected Routes

- **Authentication enforcement**: Ensure only authenticated users access sensitive parts of the app.
- **Route-based access control**: Redirect unauthorized users to login or home page.
- **User experience**: Maintain state (e.g., redirect after login) using `location.state`.

### Edge Cases and Best Practices

- **Handling loading states**: Delay rendering until auth status is resolved.
- **Token expiration**: Revalidate tokens server-side where necessary.
- **Redirect loops**: Avoid infinite redirect loops if the user is already redirected to `/login`.

---

## Nested and Dynamic Routing

Nested routes allow rendering multiple layers of components based on the current URL. They are ideal for organizing UI elements like dashboards, settings, and multi-step forms.

### Example: Nested Routes for a Dashboard

```tsx
const DashboardLayout = () => {
  return (
    <div>
      <h1>Dashboard</h1>
      <Outlet />
    </div>
  );
};

const UserSettings = () => {
  return <h2>User Settings</h2>;
};

<Router>
  <Routes>
    <Route path="/dashboard" element={<DashboardLayout />}>
      <Route path="settings" element={<UserSettings />} />
    </Route>
  </Routes>
</Router>;
```

### Dynamic Route Parameters

Dynamic route parameters allow you to create routes based on variable input, such as user IDs, product slugs, or article IDs.

```tsx
const UserPage = () => {
  const { userId } = useParams<{ userId: string }>();
  return <h2>User ID: {userId}</h2>;
};

<Router>
  <Routes>
    <Route path="/users/:userId" element={<UserPage />} />
  </Routes>
</Router>;
```

### Why Use Nested and Dynamic Routes

- **Modular UI**: Maintain a consistent layout across nested sections.
- **URL-driven navigation**: Use query parameters and path segments to control UI state.
- **Improved SEO**: Dynamic routes can generate unique URLs for content pages.

### Common Pitfalls

- **Incorrect Outlet placement**: `Outlet` must be used inside the parent route component.
- **Missing route hierarchy**: Nested routes require a clear parent-child structure.
- **Overly complex routing**: Avoid deeply nested routes without clear user benefit.
- **Misusing `index` routes**: Define default child routes using the `index` prop.

---

## Route Redirection and Error Handling

Redirects are essential for maintaining a smooth user experience, especially after login, logout, or when handling invalid routes.

```tsx
const Error404 = () => <h2>Page Not Found</h2>;

<Router>
  <Routes>
    <Route path="*" element={<Error404 />} />
    <Route path="/old-path" element={<Navigate to="/new-path" replace />} />
  </Routes>
</Router>;
```

### Redirect Best Practices

- **Use `replace` to avoid back button issues**: Especially useful for login redirects.
- **Preserve navigation state**: Use `state` in `Navigate` to pass the original location.
- **Avoid redirect loops**: Always validate redirect paths before applying them.

---

## Advanced Route Composition with Lazy and Suspense

For large-scale applications, it’s essential to load route components lazily and manage loading states with Suspense.

```tsx
import { Suspense } from 'react';

const LazyDashboard = React.lazy(() => import('./Dashboard'));

<Route
  path="/dashboard"
  element={
    <Suspense fallback="Loading...">
      <LazyDashboard />
    </Suspense>
  }
/>
```

### Benefits

- **Improved performance**: Only load necessary components on demand.
- **Better user experience**: Show loading indicators instead of blank pages.
- **Scalability**: Modular structure with clear separation of concerns.

---

## Route Guards with Conditional Rendering

In addition to redirecting unauthenticated users, you can apply route guards based on roles or permissions.

```tsx
const useUserPermissions = () => {
  const user = JSON.parse(localStorage.getItem('user') || 'null');
  return user?.role;
};

const AdminRoute = ({ children }: { children: JSX.Element }) => {
  const role = useUserPermissions();

  if (role !== 'admin') {
    return <Navigate to="/unauthorized" replace />;
  }

  return children;
};
```

### Usage in Route Definitions

```tsx
<Route
  path="/admin"
  element={
    <AdminRoute>
      <AdminPanel />
    </AdminRoute>
  }
/>
```

### Why Use Conditional Route Guards

- **Role-based access control (RBAC)**: Allow only certain roles to access specific routes.
- **Flexible access control**: Combine multiple guards for complex permission logic.
- **Improved security**: Prevent unauthorized users from accessing admin tools or data.

---

## Best Practices for Advanced React Router Patterns

### 1. Keep Route Definitions DRY

Avoid duplicating route logic by abstracting common elements into reusable components or hooks.

### 2. Use TypeScript for Route Types

TypeScript makes route parameters and state predictable and easier to maintain.

```ts
type RouteParams = {
  userId: string;
  productId: string;
};
```

### 3. Centralize Route Configuration

Avoid scattering route logic across multiple files. Use a single file or module to define all routes.

```tsx
const routes = createBrowserRouter([
  {
    path: '/dashboard',
    element: <DashboardLayout />,
    children: [
      { path: 'settings', element: <UserSettings /> },
      { path: 'profile', element: <UserProfile /> },
    ],
  },
]);
```

### 4. Handle 404 and Error Pages

Always define a fallback route for unmatched paths to improve user experience and SEO.

```tsx
<Route path="*" element={<Error404 />} />
```

---

## Cross-Platform Considerations and Alternatives

While React Router is the de facto standard for routing in React apps, alternatives exist depending on your framework or architecture:

- **Next.js**: Built-in file-based routing with server-side rendering (SSR) and API routes.
- **Remix**: Emphasizes nested routing and data loading with route-based components.
- **Gatsby**: Static site generation with page-based routing.

Use React Router when you need full control over client-side routing in custom React apps. For SSR or static site generation, consider Remix or Gatsby.

---

## Troubleshooting Common Issues

### 1. `Outlet` Not Rendering Nested Routes

**Problem**: The `Outlet` component is missing from the parent route component.

**Solution**: Ensure `Outlet` is used inside the parent component in the correct place.

### 2. Redirect Loops

**Problem**: Users are redirected in a loop between routes like `/login` and `/dashboard`.

**Solution**: Always check authentication status in a single place (e.g., a custom hook) and use `replace` with `Navigate`.

### 3. Dynamic Route Parameters Not Working

**Problem**: `useParams()` is returning `undefined` or incorrect data.

**Solution**: Ensure the route is correctly defined with `:paramName`, and that the component is part of the route hierarchy.

### 4. Lazy Components Not Loading

**Problem**: Lazy-loaded components are not rendered, and no error appears.

**Solution**: Wrap the component in a `Suspense` boundary and ensure the bundler is configured for code splitting.

---

## Real-World Use Cases

### E-commerce Dashboard

In an e-commerce platform, nested routes can render a product catalog, user orders, and inventory management under a single `/admin` route.

```tsx
<Route path="/admin" element={<AdminLayout />}>
  <Route path="products" element={<ProductList />} />
  <Route path="orders" element={<OrderList />} />
  <Route path="users" element={<UserList />} />
</Route>
```

### Multi-Tenant SaaS Platform

Dynamic route parameters can be used to segment tenants or organizations:

```tsx
<Route path="/:tenantId/settings" element={<TenantSettings />} />
```

This approach allows a single application to serve multiple clients with isolated configurations.

---

## Conclusion

Mastering advanced React Router patterns is essential for building scalable, secure, and maintainable React applications. By leveraging protected routes, nested routing, dynamic parameters, and route guards, you can create complex UIs that respond to user actions and data changes effectively.

Always keep your routes clean, modular, and well-documented. Use TypeScript to enforce types, and test route logic in isolation to avoid unintended behavior.

Understanding when and how to apply these patterns ensures you're building for both scalability and developer productivity, making your application robust and future-proof.