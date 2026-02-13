# TypeScript with React

TypeScript enhances React by providing compile-time type checking and improving developer productivity through auto-completion and refactoring support. By combining React's component-based architecture with TypeScript's static typing, developers can build scalable and maintainable applications. This document explores key TypeScript concepts in React development, including type definitions, prop types, hooks typing, and generics. We'll also look at best practices for structuring typed components and custom hooks, while addressing common pitfalls and advanced use cases.

---

## Type Definitions in React Components

TypeScript allows for explicit type definitions for props and state, reducing runtime errors and improving code readability. This is especially valuable in large-scale applications where maintaining component contracts is critical.

```ts
import React from 'react';

// Define a type for the component props
type UserProps = {
  id: number;
  name: string;
  email?: string; // optional property
};

// Function component with typed props
const UserCard: React.FC<UserProps> = ({ id, name, email }) => {
  return (
    <div>
      <p>ID: {id}</p>
      <p>Name: {name}</p>
      {email && <p>Email: {email}</p>}
    </div>
  );
};

export default UserCard;
```

The `React.FC` generic type defines the component signature. It includes `props` as the generic argument and implicitly includes `children` as a property. However, for more control or when using default props, it's often better to define the props type explicitly without `React.FC`.

---

## Prop Types and Default Props

In TypeScript, you can define default values for props and ensure they are typed correctly. This is particularly useful when working with components that may not always receive certain props.

```ts
import React from 'react';

// Define a type with optional properties
type ButtonProps = {
  label: string;
  onClick: () => void;
  disabled?: boolean;
};

// Default props can be defined separately
const defaultProps: ButtonProps = {
  disabled: false,
};

// Function component with default props
const CustomButton: React.FC<ButtonProps> = ({ label, onClick, disabled = defaultProps.disabled }) => {
  return (
    <button disabled={disabled} onClick={onClick}>
      {label}
    </button>
  );
};

export default CustomButton;
```

In this example, `disabled` has a default value of `false`, ensuring the component is more flexible. TypeScript will enforce that all required props are passed in, and optional ones are handled safely.

---

## Typing React Hooks

One of the most powerful features of React is hooks, and TypeScript allows for strong typing of both built-in and custom hooks. This helps enforce correct usage patterns and prevents subtle bugs.

### useState

When using `useState`, you can provide a generic type to define the shape of the state:

```ts
import React, { useState } from 'react';

type TodoItem = {
  id: number;
  text: string;
  completed: boolean;
};

const TodoList: React.FC = () => {
  const [todos, setTodos] = useState<TodoItem[]>([]);

  // Add a new todo
  const addTodo = () => {
    const newTodo: TodoItem = {
      id: Date.now(),
      text: 'New task',
      completed: false,
    };
    setTodos([...todos, newTodo]);
  };

  return (
    <div>
      <button onClick={addTodo}>Add Todo</button>
      <ul>
        {todos.map((todo) => (
          <li key={todo.id}>{todo.text}</li>
        ))}
      </ul>
    </div>
  );
};
```

Using a type like `TodoItem` makes the component more maintainable and easier to refactor.

---

## Custom Hooks with TypeScript

Custom hooks can encapsulate reusable logic and are a key part of React’s functional component model. TypeScript allows for strong typing and better IDE support when writing custom hooks.

```ts
import { useState, useEffect } from 'react';

type UseFetchResult<T> = {
  data: T | null;
  loading: boolean;
  error: string | null;
};

// Custom hook with generic typing
const useFetch = <T,>(url: string): UseFetchResult<T> => {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await fetch(url);
        if (!response.ok) throw new Error('Network response was not ok');
        const result: T = await response.json();
        setData(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'An error occurred');
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [url]);

  return { data, loading, error };
};

export default useFetch;
```

In this example, `useFetch` is typed with a generic `<T>`, allowing it to work with various response shapes. This hook returns an object with typed properties for `data`, `loading`, and `error`.

---

## Generics in React Components

Generics are not limited to hooks. You can use them to build flexible React components that can accept and return different types dynamically.

```ts
import React from 'react';

type ListProps<T> = {
  items: T[];
  renderItem: (item: T, index: number) => React.ReactNode;
};

const List = <T,>({ items, renderItem }: ListProps<T>): JSX.Element => {
  return (
    <ul>
      {items.map((item, index) => (
        <li key={index}>{renderItem(item, index)}</li>
      ))}
    </ul>
  );
};

export default List;
```

This `List` component can render any type of item, as long as the `renderItem` function is provided. Generics allow the component to be reused across different data types and UI structures.

---

## Best Practices

When working with TypeScript and React, it's important to follow best practices that ensure code quality, maintainability, and scalability. Here are some key recommendations:

### 1. Avoid `any` and Prefer `unknown`

Use `unknown` instead of `any` when you don’t know the type of a value. This ensures type safety and prevents silent type errors.

```ts
const processValue = (value: unknown) => {
  if (typeof value === 'string') {
    console.log(value.toUpperCase());
  }
};
```

### 2. Define Types at the Top Level

Always define types at the top of a file or in a shared types file. This improves readability and makes it easier to share types between components.

```ts
// types.ts
export type User = {
  id: number;
  name: string;
  email: string;
};
```

### 3. Use Discriminated Unions for Complex Data

When working with complex or conditional data structures, use discriminated unions with a common discriminant field.

```ts
type SuccessResponse = {
  type: 'success';
  data: string;
};

type ErrorResponse = {
  type: 'error';
  message: string;
};

type ApiResponse = SuccessResponse | ErrorResponse;

const handleResponse = (response: ApiResponse) => {
  if (response.type === 'success') {
    console.log('Success:', response.data);
  } else {
    console.error('Error:', response.message);
  }
};
```

This pattern helps TypeScript narrow the type during conditional checks, reducing the need for type assertions.

---

## Component Patterns with TypeScript

Using TypeScript with React encourages more robust component patterns. Here are some common patterns and how to type them.

### 1. Conditional Rendering with TypeScript

Conditional rendering is a core part of React. TypeScript helps ensure that the correct types are available in each branch of the condition.

```ts
type Post = {
  id: number;
  title: string;
  content: string;
};

type LoadingState = {
  status: 'loading';
};

type ErrorState = {
  status: 'error';
  message: string;
};

type PostState = Post | LoadingState | ErrorState;

const PostView = ({ state }: { state: PostState }) => {
  if (state.status === 'loading') {
    return <p>Loading post...</p>;
  }

  if (state.status === 'error') {
    return <p>Error: {state.message}</p>;
  }

  return (
    <div>
      <h1>{state.title}</h1>
      <p>{state.content}</p>
    </div>
  );
};
```

Here, TypeScript infers the correct type based on the `status` field and ensures the appropriate properties are available in each branch.

---

## Common Pitfalls and Troubleshooting

While TypeScript helps find many bugs at compile time, there are still some pitfalls to be aware of when working with React.

### 1. Overusing `React.FC`

`React.FC` is convenient, but it adds implicit `children` and `ReactNode` type assumptions. For stricter control, define props explicitly and avoid using `React.FC` unless necessary.

### 2. Incorrect Typing of Event Handlers

Event handlers like `onChange` for inputs often involve complex types. Always use `React.ChangeEvent` for better type inference.

```ts
const Input = ({ onChange }: { onChange: (e: React.ChangeEvent<HTMLInputElement>) => void }) => {
  return <input type="text" onChange={onChange} />;
};
```

Using the specific `React.ChangeEvent` type ensures that `e.target.value` is correctly typed.

### 3. Misusing `any` or Missing Types

Avoid using `any` or `unknown` without a reason. Instead, define precise types or use `never` for unreachable code paths.

---

## Real-World Use Cases

### 1. Building a Form with Validation

In enterprise applications, forms often require complex validation and state management. TypeScript ensures that each form field has the correct type and validation rules.

```ts
type FormState = {
  name: string;
  email: string;
  password: string;
};

type FormErrors = {
  name?: string;
  email?: string;
  password?: string;
};

const useForm = (initialState: FormState): [FormState, FormErrors, (field: keyof FormState, value: string) => void] => {
  const [form, setForm] = useState<FormState>(initialState);
  const [errors, setErrors] = useState<FormErrors>({});

  const handleChange = (field: keyof FormState, value: string) => {
    setForm({ ...form, [field]: value });
    // Add validation logic here
  };

  return [form, errors, handleChange];
};
```

### 2. API Fetching with TypeScript

When integrating with REST or GraphQL APIs, TypeScript helps ensure that the response shape matches your expectations.

```ts
type UserResponse = {
  id: number;
  name: string;
  email: string;
};

const useUser = (id: number): UseFetchResult<UserResponse> => {
  return useFetch<UserResponse>(`/api/users/${id}`);
};
```

This pattern ensures type safety when consuming API responses in components.

---

## Comparison with Other Frameworks

### React + TypeScript vs. Vue 3 + TypeScript

Vue 3 has strong TypeScript support through the Options API and Composition API. However, React’s ecosystem is more mature in terms of TypeScript tooling and community patterns. Vue provides automatic type inference in the Options API, but React requires explicit type definitions, which can lead to more predictable and maintainable code.

### React + TypeScript vs. Angular

Angular is built with TypeScript from the ground up, making it easier to adopt in large-scale enterprise environments. However, React offers more flexibility and a lighter footprint, making it preferable for teams that want more control over their architecture.

---

## Conclusion

TypeScript brings significant value to React development by enhancing type safety, improving developer productivity, and reducing runtime errors. By leveraging type definitions, hooks typing, generics, and custom types, you can build robust and maintainable applications. This guide has explored key TypeScript concepts in React, including typed components, hooks, prop types, and best practices for real-world applications. By applying these patterns, you’ll be equipped to build scalable, type-safe React applications that are easy to maintain and evolve over time.