# Micro-Frontends with React

Micro-frontend architecture is a design pattern that allows multiple teams to independently develop and deploy parts of a frontend application. In the context of React, this pattern is often implemented using **Webpack Module Federation**, a powerful feature that enables sharing of React components, utilities, and even entire applications between different builds. This guide explores the core concepts, implementation strategies, and best practices for building production-ready micro-frontend applications with React.

## Core Concepts

### Module Federation

Webpack Module Federation allows sharing of code across applications by dynamically loading remote modules at runtime. This is a key enabler of micro-frontend architecture, as it eliminates the need for monolithic builds and allows for independent deployment of UI components.

### Micro-Frontend Architecture

A micro-frontend architecture is structured around the idea of breaking a frontend application into smaller, independent applications that can be developed, deployed, and scaled separately. Each micro-frontend can be built using a different technology stack, but in this context, we’ll focus on React-based micro-frontend implementations.

### Integration Strategy

Integration in micro-frontend architectures involves managing routing, state, and communication between shared and remote components. This section will delve into practical integration techniques and code examples for React-based micro-frontend applications.

## Implementing Module Federation with Webpack

Webpack 5 introduced the **Module Federation Plugin**, which makes it possible to share React components and hooks across different Webpack builds.

### Sharing a React Component as a Remote

To share a React component, you first need to configure the `ModuleFederationPlugin` in your Webpack configuration. Here’s an example of a **host** (sometimes called the container) application that loads a component from a **remote** application.

#### Remote Application Webpack Configuration

```js
// webpack.config.js in the remote app
const ModuleFederationPlugin = require("webpack/lib/container/ModuleFederationPlugin");

module.exports = {
  entry: "./src/index",
  mode: "production",
  output: {
    publicPath: "auto",
  },
  plugins: [
    new ModuleFederationPlugin({
      name: "RemoteApp",
      filename: "remoteEntry.js",
      exposes: {
        "./Button": "./src/components/Button",
      },
      shared: {
        react: { singleton: true, requiredVersion: "^18.2.0" },
        "react-dom": { singleton: true, requiredVersion: "^18.2.0" },
      },
    }),
  ],
};
```

In this configuration, the `Button` component is exposed as a remote module. The `shared` property ensures that React and React DOM are shared as singleton instances across the application to prevent duplication.

### Consuming the Remote Component

The host application can load the remote component using the `RemoteApp.Button` syntax. Here’s how you can configure the host application:

#### Host Application Webpack Configuration

```js
// webpack.config.js in the host app
const ModuleFederationPlugin = require("webpack/lib/container/ModuleFederationPlugin");

module.exports = {
  entry: "./src/index",
  mode: "production",
  output: {
    publicPath: "auto",
  },
  plugins: [
    new ModuleFederationPlugin({
      name: "HostApp",
      filename: "remoteEntry.js",
      remotes: {
        RemoteApp: "RemoteApp@http://localhost:3001/remoteEntry.js",
      },
      shared: {
        react: { singleton: true, requiredVersion: "^18.2.0" },
        "react-dom": { singleton: true, requiredVersion: "^18.2.0" },
      },
    }),
  ],
};
```

This setup tells the host application where to find the remote component. Now, you can dynamically import and render it in your React component:

#### Using Remote Component in Host App

```jsx
// src/components/RemoteButton.js
import React, { lazy, Suspense } from "react";

const RemoteButton = lazy(() => import("RemoteApp/Button"));

export function RemoteButtonWrapper() {
  return (
    <Suspense fallback="Loading...">
      <RemoteButton />
    </Suspense>
  );
}
```

In this example, the `RemoteButtonWrapper` dynamically loads the `RemoteButton` component. The `Suspense` component is used to handle the asynchronous loading.

### Cross-Framework Considerations

While this guide focuses on React, Module Federation can also be used to integrate non-React components. For example, you might have a Vue or Angular component that needs to be embedded in a React host application. The process involves wrapping the foreign component in a React component using a **custom element** or **portal** strategy.

## Routing Integration

Micro-frontend architectures often require decentralized routing, where each micro-frontend handles its own routing. There are two common approaches:

1. **Nested Routing**: The host application handles the main routing and dynamically loads sub-applications based on routes.
2. **Decentralized Routing**: Each micro-frontend has full control over its own routes and mounts itself in the DOM when the route matches.

### Nested Routing Example with React Router

Here’s an example of a host application that mounts a remote component when a specific route is matched:

```jsx
// HostApp/src/App.js
import React, { lazy, Suspense } from "react";
import {
  BrowserRouter as Router,
  Routes,
  Route,
} from "react-router-dom";

const RemoteComponent = lazy(() => import("RemoteApp/RemoteComponent"));

function App() {
  return (
    <Router>
      <Suspense fallback="Loading...">
        <Routes>
          <Route path="/remote" element={<RemoteComponent />} />
        </Routes>
      </Suspense>
    </Router>
  );
}

export default App;
```

This strategy is simple but requires coordination between the host and the remote application to ensure routing paths are unique and consistent.

## State Management and Communication Between Micro-Frontends

State management in micro-frontend architectures can be challenging due to the decoupled nature of the applications. Common approaches include:

1. **Shared Context APIs**: Use a global state store (like Redux, Zustand, or React Context) that is shared across micro-frontends. This requires synchronization between builds and may not be ideal in all scenarios.
2. **Event Bus or Custom Events**: Use a global event bus (e.g., `window.addEventListener`) to publish and subscribe to events across boundaries.
3. **Custom Hooks**: If both the host and remote applications use React, you can share a custom hook that provides access to shared state.

### Example: Using a Global Event Bus for Communication

```js
// RemoteApp/src/utils/eventBus.js
export const eventBus = {
  emit: (eventType, payload) => {
    window.dispatchEvent(new CustomEvent(eventType, { detail: payload }));
  },
  on: (eventType, callback) => {
    window.addEventListener(eventType, callback);
  },
};
```

```js
// HostApp/src/components/EventConsumer.js
import React, { useEffect } from "react";

export function EventConsumer() {
  useEffect(() => {
    const handleEvent = (e) => {
      console.log("Received event:", e.detail);
    };

    window.addEventListener("custom-event", handleEvent);

    return () => {
      window.removeEventListener("custom-event", handleEvent);
    };
  }, []);

  return null;
}
```

This pattern allows remote components to emit events that the host (or other remotes) can listen for.

## Best Practices

### 1. Use Semantic Versioning for Remote Builds

Each remote application should be versioned independently. This allows the host to fetch the correct version of the remote component and manage updates gracefully.

### 2. Isolate Styles and Avoid Global CSS

To prevent CSS conflicts, remote applications should use CSS modules, styled components, or scoped styles. Avoid using global CSS classes in micro-frontend components.

### 3. Implement Lazy Loading and Code Splitting

Use Webpack's dynamic imports and React's `Suspense` API to lazily load remote components. This reduces initial load time and improves performance.

### 4. Ensure Shared Dependencies Are Consistent

When sharing React or other libraries between host and remote applications, ensure that version numbers match. Module Federation supports specifying required versions for shared dependencies, which helps avoid runtime issues.

### 5. Build and Deploy Remote Applications Separately

Each remote application should be built and deployed independently. This supports continuous delivery and allows for independent scaling.

### 6. Use a CI/CD Pipeline That Supports Module Federation

Integrate remote components into a CI/CD pipeline that can publish `remoteEntry.js` and update references in the host application when new versions are available.

## Troubleshooting Common Issues

### 1. Missing Remote Entry Files

If a remote component fails to load, verify that the `remoteEntry.js` file is correctly published and accessible at the specified URL. Check for CORS issues if the host and remote are on different domains.

### 2. Duplicate React Instances

If you see errors like `Cannot update a component from inside the function body`, it may indicate multiple React instances. Always use the `shared` option in Module Federation to ensure React is treated as a singleton.

### 3. Slow Load Times

Optimize remote component loading by using `Suspense` and lazy loading. Avoid loading large chunks of code unless necessary.

### 4. State Synchronization Issues

Avoid relying on global state unless it's explicitly shared. Use event-based communication or custom hooks for state synchronization between micro-frontends.

## Real-World Use Case: E-Commerce Platform

Consider an e-commerce platform with separate micro-frontends for:

- Product listings (React)
- Cart (Vue)
- User profile (React)
- Checkout (Angular)

The host application loads the appropriate micro-frontend based on the route. Each micro-frontend is built and deployed independently, sharing only the necessary components and state. Module Federation allows the host to dynamically load product listings from a remote React-based application and the checkout from an Angular app.

This architecture improves team autonomy, accelerates feature delivery, and supports a more scalable frontend architecture.

## Conclusion

Micro-frontend architectures using Webpack Module Federation offer a robust way to build and maintain large-scale React applications. By leveraging the power of dynamic imports, shared dependencies, and decentralized routing, teams can build modular, scalable, and independently deployable UI components.

Implementing micro-frontends in production requires careful planning around state management, communication strategies, and build processes. However, the benefits—such as faster development cycles, improved team autonomy, and better maintainability—are significant for modern SPAs and enterprise applications.