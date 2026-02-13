# useState Hook

The `useState` hook is the most fundamental hook in React, enabling functional components to manage state. Introduced in React 16.8, hooks revolutionized React development by allowing functional components to use features previously exclusive to class components. Understanding `useState` is essential for modern React development.

## Basic Usage

`useState` is a function that accepts an initial state value and returns a pair: the current state value and a function to update it:

```javascript
import { useState } from 'react';

function Counter() {
  const [count, setCount] = useState(0);

  return (
    <div>
      <p>You clicked {count} times</p>
      <button onClick={() => setCount(count + 1)}>
        Click me
      </button>
    </div>
  );
}
```

The array destructuring syntax `[count, setCount]` is a convention but not required. You could use any names, though the pattern of `[value, setValue]` is standard across the React ecosystem.

## How useState Works

When you call `useState`, React allocates space to remember the state value between renders. On the first render (mount), the state gets initialized to the value you passed. On subsequent renders, `useState` returns the current state value.

The setter function (e.g., `setCount`) schedules a re-render with the new value. React will call your component function again, and this time `useState` will return the updated value:

```javascript
function Example() {
  const [count, setCount] = useState(0);

  console.log('Rendering with count:', count);

  // First render: logs "Rendering with count: 0"
  // After clicking: logs "Rendering with count: 1"
  // After clicking again: logs "Rendering with count: 2"

  return <button onClick={() => setCount(count + 1)}>{count}</button>;
}
```

This declarative approach contrasts with imperative DOM manipulation in vanilla JavaScript or jQuery, where you'd manually update the DOM when values change.

## Multiple State Variables

You can call `useState` multiple times in a single component to manage independent pieces of state:

```javascript
function UserProfile() {
  const [name, setName] = useState('');
  const [age, setAge] = useState(0);
  const [email, setEmail] = useState('');
  const [isActive, setIsActive] = useState(false);

  return (
    <form>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder="Name"
      />
      <input
        type="number"
        value={age}
        onChange={(e) => setAge(Number(e.target.value))}
        placeholder="Age"
      />
      <input
        type="email"
        value={email}
        onChange={(e) => setEmail(e.target.value)}
        placeholder="Email"
      />
      <label>
        <input
          type="checkbox"
          checked={isActive}
          onChange={(e) => setIsActive(e.target.checked)}
        />
        Active
      </label>
    </form>
  );
}
```

React keeps track of the order of hook calls, which is why hooks must always be called in the same order. This is enforced by the Rules of Hooks.

## Object State

State can hold any JavaScript value, including objects and arrays. When updating objects, you must create new objects rather than mutating existing ones:

```javascript
function UserForm() {
  const [user, setUser] = useState({
    name: '',
    email: '',
    age: 0
  });

  function updateName(name) {
    // Wrong: mutates state directly
    user.name = name;
    setUser(user);

    // Correct: creates new object with updated field
    setUser({
      ...user,
      name: name
    });
  }

  return (
    <input
      value={user.name}
      onChange={(e) => updateName(e.target.value)}
    />
  );
}
```

The spread operator `...user` creates a shallow copy of the user object. This immutability requirement ensures React can detect changes through reference comparison, similar to how Redux reducers must return new state objects.

## Array State

Arrays also require immutable updates. Use methods that return new arrays rather than mutating methods:

```javascript
function TodoList() {
  const [todos, setTodos] = useState([]);

  function addTodo(text) {
    // Correct: creates new array
    setTodos([...todos, { id: Date.now(), text, completed: false }]);
  }

  function removeTodo(id) {
    // Correct: filter returns new array
    setTodos(todos.filter(todo => todo.id !== id));
  }

  function toggleTodo(id) {
    // Correct: map returns new array, spread creates new objects
    setTodos(todos.map(todo =>
      todo.id === id
        ? { ...todo, completed: !todo.completed }
        : todo
    ));
  }

  return (
    <ul>
      {todos.map(todo => (
        <li key={todo.id}>
          <input
            type="checkbox"
            checked={todo.completed}
            onChange={() => toggleTodo(todo.id)}
          />
          {todo.text}
          <button onClick={() => removeTodo(todo.id)}>Delete</button>
        </li>
      ))}
    </ul>
  );
}
```

Avoid mutating array methods like `push()`, `splice()`, `pop()`, and `sort()`. Instead use `concat()`, `filter()`, `map()`, `slice()`, and the spread operator.

## Functional Updates

When the new state depends on the previous state, use the functional update form to avoid stale closures and ensure correct behavior with batched updates:

```javascript
function Counter() {
  const [count, setCount] = useState(0);

  function incrementThrice() {
    // Wrong: only increments by 1 due to closure
    setCount(count + 1);
    setCount(count + 1);
    setCount(count + 1);

    // Correct: increments by 3
    setCount(c => c + 1);
    setCount(c => c + 1);
    setCount(c => c + 1);
  }

  return <button onClick={incrementThrice}>{count}</button>;
}
```

The functional form `setCount(c => c + 1)` receives the most up-to-date state value, making it the preferred approach whenever calculating new state from old state. This pattern is especially important in event handlers, effects, and asynchronous code.

## Lazy Initialization

When initial state is expensive to compute, pass a function to `useState` that will only run once during the initial render:

```javascript
function ExpensiveComponent({ userId }) {
  // Bad: runs expensiveCalculation on every render
  const [data, setData] = useState(expensiveCalculation(userId));

  // Good: only runs once on mount
  const [data, setData] = useState(() => expensiveCalculation(userId));

  return <div>{data}</div>;
}
```

This is particularly useful when reading from localStorage, computing derived data, or processing large datasets:

```javascript
function Settings() {
  const [preferences, setPreferences] = useState(() => {
    const saved = localStorage.getItem('preferences');
    return saved ? JSON.parse(saved) : defaultPreferences;
  });
}
```

The initializer function runs only once, but the value form runs on every render (though React discards all but the first result).

## Resetting State

Sometimes you need to reset state to its initial value. You can store the initial value and reset to it:

```javascript
function Form() {
  const initialState = { name: '', email: '' };
  const [formData, setFormData] = useState(initialState);

  function handleReset() {
    setFormData(initialState);
  }

  return (
    <form>
      <input
        value={formData.name}
        onChange={(e) => setFormData({ ...formData, name: e.target.value })}
      />
      <input
        value={formData.email}
        onChange={(e) => setFormData({ ...formData, email: e.target.value })}
      />
      <button type="button" onClick={handleReset}>Reset</button>
    </form>
  );
}
```

Alternatively, you can force a component to remount by changing its `key`, which resets all state:

```javascript
function App() {
  const [resetKey, setResetKey] = useState(0);

  return (
    <>
      <Form key={resetKey} />
      <button onClick={() => setResetKey(k => k + 1)}>
        Reset Form
      </button>
    </>
  );
}
```

## State Batching

React 18 automatically batches multiple state updates to reduce re-renders. This happens even in promises, timeouts, and native event handlers:

```javascript
function handleClick() {
  setCount(c => c + 1);
  setFlag(f => !f);
  setData(d => [...d, newItem]);
  // Only one re-render occurs, not three
}

setTimeout(() => {
  setCount(c => c + 1);
  setFlag(f => !f);
  // Also batched in React 18 (not in React 17)
}, 1000);
```

If you need to read state immediately after setting it (rare), use `flushSync` from `react-dom`:

```javascript
import { flushSync } from 'react-dom';

function handleClick() {
  flushSync(() => {
    setCount(c => c + 1);
  });
  // State is now updated and component has re-rendered
  console.log(countRef.current.textContent); // Shows new value
}
```

Use `flushSync` sparingly as it opts out of batching and can hurt performance.

## Common Pitfalls

### Stale Closures

Closures in event handlers and effects can capture old state values:

```javascript
function Counter() {
  const [count, setCount] = useState(0);

  function handleClick() {
    setTimeout(() => {
      // This captures count at the time handleClick was created
      setCount(count + 1); // May use stale value
    }, 3000);
  }

  function handleClickCorrect() {
    setTimeout(() => {
      // This always uses current value
      setCount(c => c + 1);
    }, 3000);
  }

  return (
    <div>
      <p>{count}</p>
      <button onClick={handleClickCorrect}>Increment (safe)</button>
    </div>
  );
}
```

Always use functional updates when state calculations happen asynchronously.

### Objects and Reference Equality

Setting state to the same object reference doesn't trigger a re-render:

```javascript
function UserProfile() {
  const [user, setUser] = useState({ name: 'John', age: 30 });

  function updateAge() {
    user.age = 31;
    setUser(user); // No re-render! Same object reference

    // Correct approach
    setUser({ ...user, age: 31 }); // New object reference
  }
}
```

React uses `Object.is` comparison to detect state changes. Creating a new object ensures React recognizes the change.

### Nested State Updates

Updating deeply nested state requires careful spreading:

```javascript
const [user, setUser] = useState({
  profile: {
    address: {
      city: 'New York'
    }
  }
});

// Update nested property
setUser({
  ...user,
  profile: {
    ...user.profile,
    address: {
      ...user.profile.address,
      city: 'Boston'
    }
  }
});
```

This gets unwieldy quickly. Consider flattening state, using `useReducer` for complex state, or state management libraries like Immer that handle immutability automatically.

## Comparison with Class Component State

In class components, state was a single object accessed via `this.state` and updated with `this.setState`:

```javascript
// Class component
class Counter extends React.Component {
  constructor(props) {
    super(props);
    this.state = { count: 0 };
  }

  increment = () => {
    this.setState({ count: this.state.count + 1 });
  }

  render() {
    return <button onClick={this.increment}>{this.state.count}</button>;
  }
}

// Equivalent functional component with useState
function Counter() {
  const [count, setCount] = useState(0);
  return <button onClick={() => setCount(count + 1)}>{count}</button>;
}
```

`useState` is simpler: no `this` binding, no constructor, and state can be split into multiple independent variables. The functional approach is more aligned with modern JavaScript patterns.

## When to Use useState vs useReducer

`useState` is perfect for simple independent state values:
- Booleans (toggles, flags)
- Strings (form inputs)
- Numbers (counters)
- Simple objects with few fields

Use `useReducer` when:
- State has complex update logic
- Multiple state values that update together
- Next state depends on previous state in non-trivial ways
- You want to test state logic in isolation

`useReducer` is essentially `useState` with an explicit update function, similar to Redux reducers but local to a component.

## Performance Considerations

`useState` is optimized for performance, but be aware:

- React batches updates automatically
- Initializer functions prevent expensive re-calculations
- State updates are asynchronous
- Functional updates prevent stale closures
- Large objects/arrays in state can slow renders (consider normalization or memoization)

For performance optimization, combine `useState` with `useMemo` and `useCallback` when needed, though premature optimization should be avoided.

`useState` is the workhorse of React hooks, providing a simple, functional API for component state. Mastering its nuances around immutability, functional updates, and batching is essential for writing efficient, bug-free React applications.
