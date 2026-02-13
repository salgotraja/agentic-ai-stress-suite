# useReducer for Complex State

In React, managing complex state logic often becomes unwieldy with the `useState` hook. When dealing with multiple interdependent values, form validation, or multi-step processes, `useReducer` becomes a powerful alternative. Inspired by Redux, `useReducer` is ideal for state logic that involves multiple sub-values or next-state dependent on previous state. This hook allows developers to manage state changes in a predictable manner using the reducer pattern.

This document explores the `useReducer` hook in depth, comparing it with `useState`, and demonstrating its application in real-world scenarios such as form state management, multi-step wizards, and undo/redo functionality.

---

## useReducer vs useState: When to Choose Which

While `useState` is perfect for simple state management, it becomes cumbersome when state transitions become complex. `useReducer`, on the other hand, shines when state involves multiple sub-values or when state transitions are not straightforward. Consider `useReducer` when:

- Your component has complex logic involving multiple related pieces of state.
- You need to handle form validation involving several fields.
- You're working with multi-step wizards or state machines.
- You want to implement undo/redo functionality or maintain a history of state changes.

In contrast, `useState` is better suited for:

- Simple state variables with minimal logic.
- Cases where the next state doesn’t depend on the previous state.
- Quick prototyping and small components.

---

## Core Concepts of useReducer

### Reducer Pattern Overview

The `useReducer` hook takes a reducer function and an initial state. The reducer is a pure function that takes the current state and an action, and returns the next state.

```javascript
const [state, dispatch] = useReducer(reducer, initialState);
```

- **Reducer function**: `(state, action) => newState`
- **Action**: An object describing what happened (e.g., `{ type: 'increment' }`)
- **dispatch**: A function used to send actions to update the state

The reducer function must be pure, meaning it cannot have side effects and should not mutate the existing state. Instead, it should return a new state object based on the current state and the action.

---

## Practical Example: Form State Management

Managing form state with `useReducer` becomes especially useful when validation, conditional fields, or dynamic fields are involved.

### Example: User Registration Form

```jsx
import React, { useReducer } from 'react';

function formReducer(state, action) {
  return {
    ...state,
    [action.field]: action.value,
    errors: {
      ...state.errors,
      [action.field]: action.error
    }
  };
}

const RegistrationForm = () => {
  const initialState = {
    username: '',
    email: '',
    password: '',
    errors: {
      username: '',
      email: '',
      password: ''
    }
  };

  const [state, dispatch] = useReducer(formReducer, initialState);

  const handleChange = (e) => {
    const { name, value } = e.target;
    let error = '';
    
    if (name === 'username' && value.length < 3) {
      error = 'Username must be at least 3 characters';
    } else if (name === 'email' && !/^\S+@\S+\.\S+$/.test(value)) {
      error = 'Invalid email format';
    } else if (name === 'password' && value.length < 6) {
      error = 'Password must be at least 6 characters';
    }

    dispatch({ field: name, value, error });
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    // Submit validation
    if (
      state.username.length < 3 ||
      !/^\S+@\S+\.\S+$/.test(state.email) ||
      state.password.length < 6
    ) {
      alert('Please fix form errors before submitting.');
      return;
    }

    console.log('Form submitted:', state);
  };

  return (
    <form onSubmit={handleSubmit}>
      <div>
        <label>Username</label>
        <input
          name="username"
          value={state.username}
          onChange={handleChange}
        />
        <p style={{ color: 'red' }}>{state.errors.username}</p>
      </div>

      <div>
        <label>Email</label>
        <input
          name="email"
          value={state.email}
          onChange={handleChange}
        />
        <p style={{ color: 'red' }}>{state.errors.email}</p>
      </div>

      <div>
        <label>Password</label>
        <input
          name="password"
          type="password"
          value={state.password}
          onChange={handleChange}
        />
        <p style={{ color: 'red' }}>{state.errors.password}</p>
      </div>

      <button type="submit">Register</button>
    </form>
  );
};

export default RegistrationForm;
```

---

## Multi-Step Wizard with useReducer

A common use case for `useReducer` is managing multi-step wizards, where each step has its own state and transitions are driven by user actions.

### Example: Onboarding Wizard

```jsx
import React, { useReducer } from 'react';

const wizardReducer = (state, action) => {
  switch (action.type) {
    case 'NEXT':
      return {
        ...state,
        currentStep: Math.min(state.currentStep + 1, state.totalSteps)
      };
    case 'BACK':
      return {
        ...state,
        currentStep: Math.max(state.currentStep - 1, 1)
      };
    case 'SET_ANSWER':
      return {
        ...state,
        answers: {
          ...state.answers,
          [action.questionId]: action.value
        }
      };
    default:
      return state;
  }
};

const OnboardingWizard = () => {
  const initialState = {
    currentStep: 1,
    totalSteps: 4,
    answers: {}
  };

  const [state, dispatch] = useReducer(wizardReducer, initialState);

  const steps = [
    <FirstStep onNext={() => dispatch({ type: 'NEXT' })} />,
    <SecondStep onNext={() => dispatch({ type: 'NEXT' })} onBack={() => dispatch({ type: 'BACK' })} />,
    <ThirdStep onNext={() => dispatch({ type: 'NEXT' })} onBack={() => dispatch({ type: 'BACK' })} />,
    <FinalStep onBack={() => dispatch({ type: 'BACK' })} onSubmit={() => console.log(state.answers)} />
  ];

  return (
    <div>
      <h2>Onboarding Wizard - Step {state.currentStep}</h2>
      {steps[state.currentStep - 1]}
    </div>
  );
};

// Dummy step components for illustration
const FirstStep = ({ onNext }) => (
  <div>
    <h3>Step 1: Welcome</h3>
    <button onClick={onNext}>Next</button>
  </div>
);

const SecondStep = ({ onNext, onBack }) => (
  <div>
    <h3>Step 2: Preferences</h3>
    <button onClick={onBack}>Back</button>
    <button onClick={onNext}>Next</button>
  </div>
);

const ThirdStep = ({ onNext, onBack }) => (
  <div>
    <h3>Step 3: Profile</h3>
    <button onClick={onBack}>Back</button>
    <button onClick={onNext}>Next</button>
  </div>
);

const FinalStep = ({ onBack, onSubmit }) => (
  <div>
    <h3>Step 4: Confirm</h3>
    <button onClick={onBack}>Back</button>
    <button onClick={onSubmit}>Submit</button>
  </div>
);

export default OnboardingWizard;
```

---

## Advanced Use Case: Undo/Redo with useReducer

Implementing undo/redo functionality is a natural fit for `useReducer` due to its ability to manage a history of state changes.

### Example: Text Editor with Undo/Redo

```jsx
import React, { useReducer } from 'react';

const editorReducer = (state, action) => {
  switch (action.type) {
    case 'INPUT':
      return {
        ...state,
        history: [...state.history, state.value],
        value: action.text,
        currentIndex: state.history.length
      };
    case 'UNDO':
      if (state.currentIndex > 0) {
        const prevIndex = state.currentIndex - 1;
        return {
          ...state,
          value: state.history[prevIndex],
          currentIndex: prevIndex
        };
      }
      return state;
    case 'REDO':
      if (state.currentIndex < state.history.length) {
        const nextIndex = state.currentIndex + 1;
        return {
          ...state,
          value: state.history[nextIndex],
          currentIndex: nextIndex
        };
      }
      return state;
    default:
      return state;
  }
};

const TextEditor = () => {
  const initialState = {
    value: '',
    history: [''],
    currentIndex: 0
  };

  const [state, dispatch] = useReducer(editorReducer, initialState);

  const handleChange = (e) => {
    dispatch({ type: 'INPUT', text: e.target.value });
  };

  const handleUndo = () => {
    dispatch({ type: 'UNDO' });
  };

  const handleRedo = () => {
    dispatch({ type: 'REDO' });
  };

  return (
    <div>
      <textarea value={state.value} onChange={handleChange} />
      <div>
        <button onClick={handleUndo}>Undo</button>
        <button onClick={handleRedo}>Redo</button>
      </div>
    </div>
  );
};

export default TextEditor;
```

---

## Best Practices for useReducer

### 1. Keep Reducers Pure

Reducers must be pure functions. Avoid side effects such as API calls, subscriptions, or `console.log` within the reducer. Instead, use `useEffect` for side effects based on state changes.

### 2. Use Immutability Correctly

Always return a new state object from the reducer. Avoid mutating the existing state. Use object spread or libraries like Immer for easier immutable updates.

### 3. Optimize Performance with useMemo

When passing dispatch functions as props or callbacks, wrap them with `useCallback` or memoize them with `useMemo` to avoid unnecessary re-renders.

### 4. Don’t Overuse useReducer

Use `useReducer` only when `useState` becomes unmanageable. Overusing it for simple state can introduce unnecessary complexity.

### 5. Debugging with DevTools

Redux DevTools can integrate with `useReducer` to provide a powerful debugging experience. Consider wrapping your reducer with the `useReducerWithDevTools` utility from Redux Toolkit or implementing custom logging.

---

## Common Pitfalls and Troubleshooting

### 1. Forgotten Immutability

Mutating the state directly inside the reducer will not trigger a re-render. Always create new state objects.

### 2. Overcomplicated Actions

Keep actions simple and avoid adding too much logic in the action object. Prefer using reducer logic for complex transitions.

### 3. Unintended Re-renders

Make sure that `dispatch` is not triggered unnecessarily. Use `useCallback` for derived event handlers to prevent redundant calls.

---

## Cross-References

- [`useState`](06-useState.md): Use for simple state without complex transitions.
- [State Management](state-management.md): Explore context, Redux, and custom hooks for managing global state.

---

## Conclusion

`useReducer` is a powerful tool for managing complex state in React applications. When used correctly, it provides a clear separation between state logic and rendering, making components easier to maintain and test. It is particularly effective in scenarios involving form validation, multi-step workflows, and undo/redo functionality.

While `useState` is a better fit for basic use cases, `useReducer` offers greater flexibility and control for state management at scale. By following best practices and avoiding common pitfalls, you can build robust, maintainable React applications even as your state logic grows in complexity.