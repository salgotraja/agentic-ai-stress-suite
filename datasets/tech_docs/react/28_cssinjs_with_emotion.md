# CSS-in-JS with Emotion

CSS-in-JS is a popular approach to styling React components where CSS is written using JavaScript syntax. This technique enables scoped styles, dynamic styling based on props, and integration with component logic. Emotion is one of the most widely used libraries for CSS-in-JS, offering a powerful and flexible API through two primary methods: the `css` prop and the `styled` API. This documentation explores how to work with Emotion in production-grade applications, emphasizing performance, theming, and best practices.

---

## Emotion Overview

Emotion allows developers to write CSS using JavaScript, either through the `css` prop or the `styled` API. It supports dynamic styling, CSS variables, and theming, making it a strong alternative to traditional CSS or CSS modules.

Emotion is known for its performance due to its use of `styled` components and runtime style injection. It also supports server-side rendering (SSR), which is essential for SEO and performance in production apps.

---

## Key Features of Emotion

### 1. `css` Prop

The `css` prop is a direct way to apply inline styles using CSS syntax. It allows for dynamic styling and scoped styles without the need for class names.

```jsx
import { css } from '@emotion/react';

const MyComponent = ({ isActive }) => (
  <div
    css={css`
      background-color: ${isActive ? 'blue' : 'gray'};
      padding: 1rem;
      border-radius: 8px;
    `}
  >
    Styled with Emotion
  </div>
);
```

This pattern is useful for one-off styles and when you want tight coupling between the component and its styling.

### 2. `styled` API

The `styled` API creates reusable styled components using tagged template literals. It allows for inheritance and composition of styles.

```jsx
import styled from '@emotion/styled';

const Button = styled.button`
  background-color: #333;
  color: white;
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 4px;
  font-size: 1rem;
`;

const PrimaryButton = styled(Button)`
  background-color: #007bff;
`;

const MyComponent = () => (
  <div>
    <Button>Default</Button>
    <PrimaryButton>Primary</PrimaryButton>
  </div>
);
```

This pattern is ideal for reusable UI components and when you want to maintain a consistent design system.

---

## Performance Considerations

Emotion is known for its performance, but there are a few best practices to optimize it further:

### 1. Use `styled` Over `css` Prop for Repeated Styles

If a component is reused across your app, using `styled` is more efficient than the `css` prop since the styles are cached and not re-injected on every render.

### 2. Minify and Purge Unused Styles

In production builds, use Emotion's built-in minification and purging features to reduce the final CSS output size. This can be done via Webpack configuration or Babel plugins.

### 3. Avoid Inline Styles When Possible

While the `css` prop is convenient, it can lead to performance issues if overused. For complex styling, prefer `styled` components or CSS classes that are statically analyzable.

---

## Theming in Emotion

Emotion integrates seamlessly with React’s context API for theming. It supports both object-based and nested theme values, which can be accessed using the `theme` prop in `styled` components.

### Example of Theme Integration

```jsx
import styled from '@emotion/styled';
import { useTheme } from 'emotion-theming';

const theme = {
  colors: {
    primary: '#007bff',
    secondary: '#6c757d',
  },
  fonts: {
    heading: 'Roboto, sans-serif',
  },
};

const ThemedButton = styled.button`
  background-color: ${props => props.theme.colors.primary};
  color: white;
  font-family: ${props => props.theme.fonts.heading};
  padding: 0.5rem 1rem;
  border: none;
  border-radius: 4px;
`;

const App = () => (
  <ThemeContext.Provider value={theme}>
    <ThemedButton>Styled with Theme</ThemedButton>
  </ThemeContext.Provider>
);
```

This approach is particularly useful for maintaining design consistency and enabling dark/light mode toggling.

---

## Advanced Emotion Patterns

### 1. Conditional Styling

Emotion supports conditional styling using JavaScript expressions within template literals.

```jsx
const Alert = styled.div`
  padding: 1rem;
  border-radius: 4px;
  background-color: ${props => props.type === 'error' ? '#f8d7da' : '#d1ecf1'};
  color: ${props => props.type === 'error' ? '#721c24' : '#0c5460'};
`;
```

### 2. Component Composition

Emotion allows component composition with the `styled` API for better reuse and maintainability.

```jsx
const BaseCard = styled.div`
  padding: 1rem;
  border-radius: 4px;
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.1);
`;

const InfoCard = styled(BaseCard)`
  background-color: #e9ecef;
`;

const WarningCard = styled(BaseCard)`
  background-color: #fff3cd;
`;
```

This pattern helps avoid style duplication and promotes a modular design.

### 3. Responsive Design

You can write responsive styles directly in Emotion using media queries.

```jsx
const ResponsiveContainer = styled.div`
  padding: 2rem;
  font-size: 1.2rem;

  @media (max-width: 768px) {
    padding: 1rem;
    font-size: 1rem;
  }

  @media (max-width: 480px) {
    padding: 0.5rem;
    font-size: 0.9rem;
  }
`;
```

This approach keeps your responsive styles close to your component logic, improving maintainability.

---

## Best Practices

### 1. Use `styled` for Reusable Components

Leverage the `styled` API for components that are reused across your application. This ensures consistent styling and better performance.

### 2. Avoid Overusing Dynamic Styles

While Emotion allows for dynamic styles, overusing inline styles and expressions can lead to performance issues. Use dynamic styles only when needed.

### 3. Keep Styles Close to Components

Emotion encourages colocation of styles and logic, which improves readability and reduces coupling between components.

### 4. Maintain a Design System

If you're building a large application, consider maintaining a design system with a shared theme and styled components. This helps enforce consistency and reduces style-related bugs.

### 5. Optimize for SSR

Ensure Emotion is configured correctly for SSR to avoid flash of unstyled content (`FOUC`). Emotion provides utilities like `flushToStyleTag()` to manage server-side styles.

---

## Troubleshooting Common Issues

### 1. Styles Not Showing Up in SSR

Ensure that you’re importing `@emotion/server` and using `renderStylesToString()` or `renderStylesToNodeStream()` for SSR. Also, flush the styles after rendering.

```js
import { renderStylesToString } from '@emotion/server';

const html = ReactDOMServer.renderToString(<App />);
const styles = renderStylesToString();
```

### 2. Duplicate Styles

If you notice duplicate styles being injected, make sure your build tools are configured correctly for minification and deduplication. Also, avoid importing Emotion multiple times in different modules.

### 3. Theme Not Available in `styled` Components

If the `theme` prop is undefined in your `styled` component, ensure you’re wrapping the component with a `ThemeProvider` or passing the theme correctly using context.

---

## Comparison with Styled Components

Emotion and [Styled Components](27) are both popular CSS-in-JS libraries. While they share many similarities, there are a few key differences:

| Feature                  | Emotion                          | Styled Components              |
|--------------------------|----------------------------------|--------------------------------|
| API                      | `css` prop and `styled` API      | Only `styled` API              |
| Server-side rendering    | Supported with `@emotion/server` | Supported with `styled-components` SSR utilities |
| Performance              | Slightly faster due to smaller bundle size | Slightly slower due to additional abstractions |
| Theming                  | Built-in `emotion-theming`     | Requires `styled-components-theming` |
| Community & Ecosystem    | Large community, actively maintained | Also large, but slightly less flexible |

In general, if you're looking for more flexibility and performance, Emotion is a solid choice.

---

## Real-World Use Case: Theming a Dashboard

Imagine you're building a dashboard with a `ThemeProvider` and multiple styled components.

```jsx
import styled from '@emotion/styled';
import { ThemeProvider } from 'emotion-theming';

const theme = {
  colors: {
    primary: '#007bff',
    background: '#f8f9fa',
  },
  font: 'Arial, sans-serif',
};

const DashboardContainer = styled.div`
  background-color: ${props => props.theme.colors.background};
  font-family: ${props => props.theme.font};
  padding: 2rem;
`;

const Header = styled.h1`
  color: ${props => props.theme.colors.primary};
`;

const App = () => (
  <ThemeProvider theme={theme}>
    <DashboardContainer>
      <Header>Dashboard</Header>
      <p>Welcome to your dashboard!</p>
    </DashboardContainer>
  </ThemeProvider>
);
```

This example demonstrates how to create a consistent, themable dashboard using Emotion.

---

## Conclusion

Emotion offers a robust, performant, and flexible solution for styling React applications. With its `css` prop and `styled` API, it supports a wide range of styling needs, from inline styles to complex design systems. By following best practices like reusing `styled` components, managing themes effectively, and optimizing for performance, you can build maintainable and scalable UIs. Whether you're working on a small component or a large enterprise application, Emotion provides the tools needed to write clean, dynamic, and scoped styles in JavaScript.