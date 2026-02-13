# Portals and Modal Patterns

In React, rendering UI elements outside the main component hierarchy is often necessary for modal dialogs, tooltips, dropdowns, and overlay components. React provides `ReactDOM.createPortal` to render children into a DOM node that exists outside the DOM hierarchy of the parent component. This technique is essential for implementing modal patterns and managing overlays effectively.

## Understanding Portals

Portals allow you to render React components into a DOM node that exists “outside” the main React tree. This is particularly useful for overlays, modal dialogs, and dropdowns that need to be positioned at the top level of the DOM or escape the styling constraints of a parent component.

### Why Use Portals?

- **Escape Parent Styles**: When a component is nested deep in the DOM and styled with `overflow: hidden` or `z-index`, it can prevent modal overlays from appearing correctly.
- **Overlay Management**: Portals let you manage overlays consistently across the app by rendering them in a predictable location.
- **Avoid Shadow DOM Limitations**: In complex apps, portals can help avoid issues with shadow DOM and scoped styles.

### Basic Portal Usage

Here's a simple example showing how to create a portal in a modal component:

```jsx
import React from 'react';
import ReactDOM from 'react-dom';

const Portal = ({ children }) => {
  const portalRoot = document.getElementById('portal-root');
  return ReactDOM.createPortal(children, portalRoot);
};

export default Portal;
```

In this example, `portal-root` is a `<div>` added to your HTML `body`:

```html
<body>
  <div id="root"></div>
  <div id="portal-root"></div>
</body>
```

You can then use the `Portal` component to render any UI outside the main component tree:

```jsx
<Portal>
  <div className="modal">
    <h2>Modal Title</h2>
    <p>This is a portal-based modal.</p>
  </div>
</Portal>
```

This approach ensures that the modal appears on top of the page and is not constrained by the parent component's CSS.

## Modal Patterns with Portals

Creating a modal dialog involves more than just rendering it in a portal. You also need to manage focus, accessibility, and overlay behavior.

### Accessible Modal Dialog

An accessible modal should trap focus within the modal, close on escape key press, and be announced by screen readers. Here’s a basic implementation:

```jsx
import React, { useEffect, useRef } from 'react';
import ReactDOM from 'react-dom';

const Modal = ({ isOpen, onClose, children }) => {
  const dialogRef = useRef(null);

  useEffect(() => {
    if (isOpen) {
      dialogRef.current.focus();
      document.body.style.overflow = 'hidden';
    } else {
      document.body.style.overflow = '';
    }

    const handleKeyDown = (e) => {
      if (e.key === 'Escape') {
        onClose();
      }
    };

    if (isOpen) {
      window.addEventListener('keydown', handleKeyDown);
    }

    return () => {
      window.removeEventListener('keydown', handleKeyDown);
    };
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  return ReactDOM.createPortal(
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content" onClick={(e) => e.stopPropagation()} ref={dialogRef}>
        <button className="close-button" onClick={onClose}>×</button>
        {children}
      </div>
    </div>,
    document.getElementById('portal-root')
  );
};

export default Modal;
```

This component uses `useRef` to trap focus and `useEffect` to manage overlay state and key events. The overlay closes when the user clicks outside the modal or presses the escape key.

## Portals for Tooltips and Dropdowns

Portals are also useful for tooltips and dropdowns that need to be positioned independently from their parent components.

### Tooltip Example

```jsx
import React, { useRef, useEffect } from 'react';
import ReactDOM from 'react-dom';

const Tooltip = ({ text, children }) => {
  const tooltipRef = useRef(null);
  const [isVisible, setIsVisible] = useState(false);

  useEffect(() => {
    const tooltip = tooltipRef.current;

    const handleMouseEnter = () => setIsVisible(true);
    const handleMouseLeave = () => setIsVisible(false);

    children.props.ref.current.addEventListener('mouseenter', handleMouseEnter);
    children.props.ref.current.addEventListener('mouseleave', handleMouseLeave);

    return () => {
      children.props.ref.current.removeEventListener('mouseenter', handleMouseEnter);
      children.props.ref.current.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, [children]);

  if (!isVisible) return null;

  return ReactDOM.createPortal(
    <div className="tooltip" ref={tooltipRef}>
      {text}
    </div>,
    document.body
  );
};
```

This example shows how to create a tooltip that appears when hovering over an element. The tooltip is rendered as a portal to avoid CSS constraints.

## Best Practices

When using portals and modal patterns, follow these best practices to ensure maintainable and accessible UIs:

- **Use a Single Portal Root**: It’s common to create a `<div id="portal-root">` in the body and reuse it across the app to manage overlays consistently.
- **Avoid Manual DOM Mutation**: Use React’s declarative API instead of DOM manipulation. If you must manipulate the DOM, do so in `useEffect` or lifecycle methods.
- **Handle Z-Index Properly**: Overlay components often require a high `z-index`. Maintain a consistent z-index theme across modals, tooltips, and dropdowns.
- **Maintain Focus Trapping and Accessibility**: Ensure that modals trap focus and support keyboard navigation. Use ARIA attributes like `role="dialog"` and `aria-modal="true"` for accessibility.
- **Unmount When Not Needed**: Always clean up when a modal or overlay is no longer visible to prevent memory leaks and improve performance.

## Troubleshooting and Common Pitfalls

- **Portal Not Rendering**: Ensure that the portal root exists in the DOM (`<div id="portal-root"></div>`) and is mounted before React tries to render into it.
- **CSS Conflicts**: Portals may inherit styles from parent components. Use CSS resets or scoped styles to avoid unexpected layout issues.
- **Focus Trapping Issues**: If focus is not properly trapped, users may tab out of the modal. Use `tabindex` and `focus()` on the modal content to manage focus.
- **Event Propagation**: Overlays that close on click may accidentally close when clicking on child elements. Use `e.stopPropagation()` in the modal container to prevent this.

## Comparison with Alternative Approaches

- **Shadow DOM**: While shadow DOM encapsulates styles, it can complicate integration with global styles and JavaScript. Portals provide a lighter-weight alternative.
- **Inline Modals**: Rendering modals directly in the component tree can lead to issues with CSS and z-index. Portals offer a cleaner, more consistent approach.

## Real-World Use Cases

Portals are essential in large-scale applications for:

- **Global Toast Notifications**: Toasts that appear across the app benefit from a consistent z-index and position.
- **Modals with Dynamic Content**: Modals that load content dynamically or are conditionally rendered from different parts of the app.
- **Dropdown Menus**: Dropdowns that appear below or beside a button, especially when constrained by parent elements.

By leveraging portals and modal patterns effectively, you can build robust, accessible, and maintainable UIs in React.