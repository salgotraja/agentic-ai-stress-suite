# Error Boundaries

In React, **error boundaries** are React components that catch JavaScript errors anywhere in their child component tree, log those errors, and display a fallback UI instead of the crashing component tree. They are essential for gracefully handling errors in the UI layer without affecting the entire application. React supports two lifecycle methods for defining error boundaries: `componentDidCatch` and `getDerivedStateFromError`.

Error boundaries **do not catch errors in the following scenarios**:
- Event handlers
- Asynchronous code (e.g., `setTimeout` or `requestAnimationFrame`)
- Server-side rendering
- Errors thrown in the error boundary itself

This document explores how to create and use error boundaries effectively, best practices for implementing graceful error recovery, and real-world use cases.

---

## Core Concepts of Error Boundaries

### getDerivedStateFromError

This static method is called during rendering when an error is thrown in a child component. It allows you to update the state to reflect the error, which can then be used to render a fallback UI. This is a **static** lifecycle method and must return an object to update the state or `null` to take no action.

### componentDidCatch

This method is invoked after an error has been thrown and caught by the error boundary. It is useful for logging errors or sending them to an external error reporting service. This method does **not** trigger a re-render by itself unless it updates the component's state.

---

## Implementing an Error Boundary

A basic error boundary component can be created using a class-based component. Here’s an example that showcases a simple fallback UI and error logging.

```jsx
import React, { Component } from 'react';

class ErrorBoundary extends Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    // Update state to show fallback UI
    return { hasError: true, error };
  }

  componentDidCatch(error, info) {
    // Log error for debugging or error tracking
    console.error('ErrorBoundary caught an error:', error, info);
    // Optionally report to an external error reporting service
    // reportErrorToService(error, info);
  }

  render() {
    if (this.state.hasError) {
      // Fallback UI displayed when an error occurs
      return (
        <div className="error-boundary">
          <h1>Something went wrong.</h1>
          <p>{this.state.error?.message}</p>
          <button onClick={() => this.setState({ hasError: false })}>
            Try again
          </button>
        </div>
        );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
```

### Usage Example

Wrap any component tree that might throw an error with the `ErrorBoundary` component:

```jsx
import React from 'react';
import ErrorBoundary from './ErrorBoundary';
import RiskyComponent from './RiskyComponent';

function App() {
  return (
    <div className="app">
      <h1>App with Error Boundary</h1>
      <ErrorBoundary>
        <RiskyComponent />
      </ErrorBoundary>
    </div>
  );
}

export default App;
```

In this example, if `RiskyComponent` throws an error, the `ErrorBoundary` will catch it and render the fallback UI instead of the crashed tree.

---

## Graceful Error Recovery Patterns

### 1. Retry Mechanisms

After rendering a fallback UI, it's often useful to allow users to retry the operation. This pattern involves updating the state in `componentDidCatch` to re-render the original components. In the example above, the "Try again" button resets the error state.

### 2. Fallback UI Customization

Error boundaries allow developers to define a tailored fallback UI depending on the context. For example, in a form submission scenario, the fallback could show a message and revert the form to its previous valid state.

```jsx
render() {
  if (this.state.hasError) {
    return (
      <div className="form-error">
        <p>Failed to process form. Please check the fields and try again.</p>
        <button onClick={this.resetForm}>Reset</button>
      </div>
    );
  }
  return this.props.children;
}
```

This customization enhances user experience by providing context-specific guidance.

---

## Error Reporting and Logging

While `componentDidCatch` is not called during server-side rendering, it is invaluable in client-side contexts. In production systems, it's crucial to log errors for debugging and monitoring.

```jsx
componentDidCatch(error, info) {
  console.error('Uncaught error in component tree:', error);
  console.error('Component stack:', info.componentStack);

  // Send to error reporting service
  if (process.env.NODE_ENV === 'production') {
    reportErrorToService({
      error,
      componentStack: info.componentStack,
      timestamp: new Date().toISOString(),
    });
  }
}
```

Ensure that logs include stack traces and contextual information for efficient debugging.

---

## Advanced Use Cases

### Nested Error Boundaries

React allows multiple error boundaries to be nested within each other, enabling fine-grained error handling. This is especially useful in large applications with loosely coupled UI components.

```jsx
<ErrorBoundary>
  <Header />
  <ErrorBoundary>
    <Sidebar />
    <MainContent />
  </ErrorBoundary>
  <Footer />
</ErrorBoundary>
```

In this example, if an error occurs in the `MainContent`, only the inner `ErrorBoundary` will catch and handle it, leaving the rest of the app functional.

### Handling Asynchronous Errors

Asynchronous operations like `fetch`, `setTimeout`, or `Promise` rejections are not caught by error boundaries. To handle these errors, use try/catch blocks or error-first callbacks.

```jsx
async function fetchData() {
  try {
    const response = await fetch('/api/data');
    if (!response.ok) throw new Error('Network response was not OK');
    return await response.json();
  } catch (err) {
    console.error('Caught async error:', err);
    // Optionally update state or re-throw to trigger boundary
    throw err;
  }
}
```

If you re-throw the error, it can be caught by the nearest error boundary.

---

## Cross-Framework Comparison

### React vs. Vue

Vue 3 introduced **errorCaptured** lifecycle hook to detect errors in child components. However, it is less flexible and powerful compared to React's error boundaries. Vue relies more on global error handling with `window.onerror` and `window.onunhandledrejection`, which can capture unhandled errors in the application.

### React vs. Angular

Angular uses **error interceptors** and global error handling via `ErrorHandler` for application-wide error tracking. Unlike React, Angular does not support component-level error boundaries, making it more challenging to isolate crashes in specific parts of the app.

---

## Best Practices for Error Boundaries

### 1. Always Provide a Fallback UI

A good practice is to design fallback UIs that are visually distinct from normal UI and offer actionable options like "Try again" or "Cancel". Avoid leaving users hanging with generic error messages.

### 2. Avoid Overusing Error Boundaries

Only wrap components that are likely to crash or have unstable behavior. Overusing error boundaries can lead to an application that silently masks errors, reducing visibility into real issues.

### 3. Combine with Global Error Handling

While error boundaries handle UI-layer errors, they should be used in conjunction with global error handling and reporting systems to capture all possible application errors.

### 4. Test Error Boundaries Thoroughly

Use testing frameworks like Jest and React Testing Library to simulate errors and verify that fallback UI is displayed correctly. Mock external services to verify that error logging is functioning as expected.

```jsx
test('renders fallback UI when child component throws error', () => {
  jest.spyOn(console, 'error').mockImplementation(() => {});

  const error = new Error('Test error');
  const Thrower = () => {
    throw error;
  };

  render(
    <ErrorBoundary>
      <Thrower />
    </ErrorBoundary>
  );

  expect(screen.getByText('Something went wrong.')).toBeInTheDocument();
  expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
});

test('logs error to console', () => {
  const error = new Error('Test error');
  const errorSpy = jest.spyOn(console, 'error').mockImplementation(() => {});

  const Thrower = () => {
    throw error;
  };

  const wrapper = mount(
    <ErrorBoundary>
      <Thrower />
    </ErrorBoundary>
  );

  expect(errorSpy).toHaveBeenCalledWith('ErrorBoundary caught an error:', error, expect.any(String));
});
```

---

## Common Pitfalls and Troubleshooting

### 1. Forgetting to Wrap Components

If a component crashes and is not wrapped in an error boundary, the entire React component tree beneath it will unmount. Always wrap potentially unstable or complex components.

### 2. Not Reseting Error State

After displaying a fallback UI, ensure that the component can reset and re-render the original UI. Forgetting to reset the state can trap users in the fallback UI permanently.

### 3. Overlooking Async Code

Asynchronous errors are not caught by error boundaries, so always use `try/catch` or `.catch()` when making async calls. This is especially true when integrating with external APIs or third-party services.

---

## Real-World Use Cases

### 1. Data Fetching in a Dashboard

In a dashboard application, an error boundary can wrap the component responsible for fetching and rendering data from an API. If the API fails, the error boundary can display a fallback message and allow the user to retry the request.

### 2. User Profile Upload

When uploading a user profile, an error boundary can catch exceptions during image processing or validation. It can display a message and allow the user to try again with a corrected image.

### 3. E-commerce Checkout

In a checkout flow, an error boundary can isolate a payment processing component. If the payment fails due to an API error, the fallback UI can prompt the user to update their payment method or try another.

---

## Conclusion

Error boundaries are a critical tool in React for building resilient and user-friendly applications. By catching and displaying UI-layer errors, they prevent the entire application from crashing and help users recover from errors gracefully. When combined with robust error logging and reporting systems, error boundaries become an essential part of a production-ready React application.

By following best practices, understanding when and where to apply error boundaries, and testing thoroughly, developers can ensure their applications remain stable and user-friendly even in the face of unexpected issues.