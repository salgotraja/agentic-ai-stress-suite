# State Management Basics

State represents the data that changes over time in your application. While props are passed from parent to child and remain immutable within a component, state is managed within a component and can be updated in response to user actions, network responses, or other events. Understanding state is crucial for building interactive React applications.

## What is State?

State is private data owned and controlled by a component. Unlike props which flow down from parent components, state is local and fully controlled by the component that declares it. When state changes, React automatically re-renders the component and its children to reflect the new data.

Consider a simple counter:

```javascript
import { useState } from 'react';

function Counter() {
  const [count, setCount] = useState(0);

  return (
    <div>
      <p>Count: {count}</p>
      <button onClick={() => setCount(count + 1)}>
        Increment
      </button>
    </div>
  );
}
```

Every time the button is clicked, `setCount` updates the state, triggering a re-render with the new count value. This reactive pattern is similar to observables in RxJS or reactive programming in frameworks like Vue 3's Composition API.

## State vs Props

The distinction between state and props is fundamental to React's component model:

**Props** (short for properties):
- Passed from parent to child components
- Read-only within the receiving component
- Used to configure a component
- Trigger re-renders when changed by the parent

**State**:
- Managed within the component
- Can be updated using setter functions
- Private to the component unless explicitly shared
- Triggers re-renders when updated

Think of props like function parameters and state like local variables declared within a function. Props are inputs from outside, while state represents internal data that the component tracks.

## Where to Put State

Deciding where to place state is one of the most important architectural decisions in React applications. The general principle is to keep state as local as possible and lift it up only when necessary.

### Local State

When data is only needed within a single component, keep it local:

```javascript
function SearchBar() {
  const [searchTerm, setSearchTerm] = useState('');

  return (
    <input
      type="text"
      value={searchTerm}
      onChange={(e) => setSearchTerm(e.target.value)}
      placeholder="Search..."
    />
  );
}
```

### Lifted State

When multiple components need to share the same state, lift it to their closest common ancestor:

```javascript
function SearchableProductList() {
  const [searchTerm, setSearchTerm] = useState('');

  return (
    <div>
      <SearchBar searchTerm={searchTerm} onSearchChange={setSearchTerm} />
      <ProductList searchTerm={searchTerm} />
    </div>
  );
}

function SearchBar({ searchTerm, onSearchChange }) {
  return (
    <input
      type="text"
      value={searchTerm}
      onChange={(e) => onSearchChange(e.target.value)}
    />
  );
}

function ProductList({ searchTerm }) {
  // Filter and display products based on searchTerm
}
```

This pattern of "lifting state up" is central to React's data flow architecture. It's similar to how data flows through a function call stack, with parent functions passing data to child functions.

## State Updates Are Asynchronous

React batches state updates for performance, meaning state changes don't happen immediately. This is an important concept that can trip up beginners:

```javascript
function Counter() {
  const [count, setCount] = useState(0);

  function handleClick() {
    setCount(count + 1);
    console.log(count); // Still logs old value!
  }

  return <button onClick={handleClick}>Count: {count}</button>;
}
```

The `console.log` shows the old value because `setCount` doesn't immediately update `count`. React schedules the update and re-renders the component later. In React 18, this batching happens automatically for all updates, including those in promises, timeouts, and native event handlers.

## Functional Updates

When the new state depends on the previous state, use the functional update form to avoid stale closures:

```javascript
function Counter() {
  const [count, setCount] = useState(0);

  function handleClick() {
    // This doesn't work as expected with multiple rapid clicks
    setCount(count + 1);
    setCount(count + 1); // Still only increments by 1
  }

  function handleClickCorrectly() {
    // Functional updates work correctly
    setCount(c => c + 1);
    setCount(c => c + 1); // Increments by 2
  }

  return (
    <div>
      <button onClick={handleClick}>Bad: {count}</button>
      <button onClick={handleClickCorrectly}>Good: {count}</button>
    </div>
  );
}
```

The functional form `setCount(c => c + 1)` receives the most recent state value, ensuring updates chain correctly even when batched.

## State Immutability

State must be treated as immutable. Never directly modify state objects or arrays:

```javascript
function TodoList() {
  const [todos, setTodos] = useState([]);

  function addTodo(text) {
    // Wrong: mutates state directly
    todos.push({ id: Date.now(), text });
    setTodos(todos);

    // Correct: creates new array
    setTodos([...todos, { id: Date.now(), text }]);
  }

  function toggleTodo(id) {
    // Correct: creates new array with updated object
    setTodos(todos.map(todo =>
      todo.id === id
        ? { ...todo, completed: !todo.completed }
        : todo
    ));
  }

  return (/* JSX */);
}
```

This immutability requirement exists because React uses shallow comparison to detect changes. If you mutate an object and pass the same reference to `setState`, React won't detect the change and won't re-render. This pattern is similar to Redux's reducer immutability requirement.

## Derived State

Avoid storing values in state that can be calculated from existing state or props. Instead, compute them during render:

```javascript
function ProductList({ products }) {
  // Bad: Redundant state
  const [filteredProducts, setFilteredProducts] = useState([]);
  const [searchTerm, setSearchTerm] = useState('');

  useEffect(() => {
    setFilteredProducts(
      products.filter(p => p.name.includes(searchTerm))
    );
  }, [products, searchTerm]);

  // Good: Derived during render
  const [searchTerm, setSearchTerm] = useState('');
  const filteredProducts = products.filter(p =>
    p.name.toLowerCase().includes(searchTerm.toLowerCase())
  );
}
```

Derived state introduces synchronization bugs and extra complexity. Calculate values directly during render unless performance profiling shows a problem, at which point `useMemo` can help.

## State Structure

How you structure state affects code clarity and performance. Follow these principles:

### Group Related State

If two state variables always update together, consider combining them:

```javascript
// Separate (might get out of sync)
const [x, setX] = useState(0);
const [y, setY] = useState(0);

// Combined (always in sync)
const [position, setPosition] = useState({ x: 0, y: 0 });
```

### Avoid Redundant State

Don't store the same information in multiple places:

```javascript
// Bad: firstName and lastName redundant with fullName
const [firstName, setFirstName] = useState('');
const [lastName, setLastName] = useState('');
const [fullName, setFullName] = useState('');

// Good: Derive fullName
const [firstName, setFirstName] = useState('');
const [lastName, setLastName] = useState('');
const fullName = `${firstName} ${lastName}`;
```

### Avoid Deeply Nested State

Deeply nested state is hard to update immutably. Consider flattening or normalizing:

```javascript
// Difficult to update
const [data, setData] = useState({
  user: {
    profile: {
      settings: {
        notifications: true
      }
    }
  }
});

// Easier to manage
const [notifications, setNotifications] = useState(true);
```

For complex nested data, consider state management libraries like Redux with normalized state shapes, similar to database normalization.

## State Initialization

`useState` can accept a value or a function. Use the function form for expensive initialization:

```javascript
// Value form (runs every render but only uses initial value)
const [state, setState] = useState(expensiveCalculation());

// Function form (only runs once on mount)
const [state, setState] = useState(() => expensiveCalculation());
```

The function form is particularly useful when reading from localStorage or performing calculations:

```javascript
function MyComponent() {
  const [data, setData] = useState(() => {
    const savedData = localStorage.getItem('myData');
    return savedData ? JSON.parse(savedData) : defaultValue;
  });
}
```

## State and Controlled Components

Forms in React typically use controlled components where form data is stored in state:

```javascript
function LoginForm() {
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');

  function handleSubmit(e) {
    e.preventDefault();
    // Process email and password
  }

  return (
    <form onSubmit={handleSubmit}>
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
      />
      <input
        type="password"
        value={password}
        onChange={(e) => setPassword(e.target.value)}
      />
      <button type="submit">Login</button>
    </form>
  );
}
```

This pattern gives you complete control over form data, enabling validation, formatting, and synchronization. The alternative, uncontrolled components, uses refs to access DOM values directly, similar to traditional JavaScript form handling.

## When to Use Global State

Local component state works well for isolated data, but some state needs to be accessible across many components. Consider global state management (Context API, Redux, Zustand) when:

- Many components need the same data (user authentication, theme)
- State updates are complex with many interdependencies
- You need middleware for logging, persistence, or time-travel debugging
- State changes originate from multiple sources

For simple global state, React's Context API often suffices. For complex applications with sophisticated state logic, Redux or similar libraries provide predictable state containers similar to Vuex or NgRx.

## State Management Patterns

Different patterns suit different scenarios:

**Local State**: Perfect for UI state like modal visibility, form inputs, toggles
**Lifted State**: Sharing state between sibling components
**Context**: Global state like theme, authentication, locale
**Reducers**: Complex state with multiple update operations (covered in useReducer)
**External Libraries**: Large applications with complex state interdependencies

## Comparison with Other Frameworks

React's state management approach differs from other frameworks:

**Vue** uses a reactivity system where mutations to state objects automatically trigger updates. React requires explicit setter calls, making data flow more explicit but requiring more discipline.

**Angular** uses change detection that runs after events, similar to React, but allows direct property mutation. React's immutability requirement is stricter.

**Svelte** provides reactive declarations using `$:` that automatically recompute when dependencies change, similar to computed properties in Vue or derived values in MobX.

React's explicit update model through setter functions makes data flow traceable and predictable, though it requires more boilerplate than Vue or Svelte's automatic reactivity.

## Best Practices

When working with state:

1. **Keep state minimal**: Only store what can't be calculated from props or other state
2. **Use immutable updates**: Always create new objects/arrays rather than mutating
3. **Avoid unnecessary state**: Prefer derived values computed during render
4. **Colocate state**: Keep state close to where it's used
5. **Lift state sparingly**: Only lift when multiple components need access
6. **Use functional updates**: When new state depends on old state
7. **Initialize lazily**: Use function initialization for expensive setup

State is the foundation of interactivity in React. Understanding when and how to use state effectively is essential for building maintainable React applications that scale from simple widgets to complex dashboards.
