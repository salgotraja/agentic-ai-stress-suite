# SWR for Data Fetching

SWR is a powerful data fetching library designed for React applications. Built on the principle of **stale-while-revalidate (SWR)**, it provides an efficient way to fetch, cache, and update data with minimal boilerplate. At its core, SWR balances performance and user experience by serving stale data immediately while fetching fresh data in the background.

SWR is not just a caching layer; it supports optimistic updates, pagination, revalidation on focus, and more. It is framework-agnostic but integrates seamlessly with React, particularly when used with hooks. It is ideal for scenarios where you need consistent and fast access to data while maintaining reactivity and minimizing unnecessary re-fetches.

## Core Concepts

### Stale-While-Revalidate (SWR)

The SWR strategy ensures that once data is fetched, it is immediately available for rendering. If the data is stale (i.e., older than the defined cache duration), SWR revalidates it in the background while serving the cached data to the user. This reduces perceived latency and avoids blocking the UI during revalidation.

### Caching and Revalidation

SWR uses a local cache to store fetched data. By default, the cache is not updated until the background fetch is complete, ensuring the UI remains stable during revalidation. You can configure the cache behavior using options such as `refreshInterval`, `revalidateOnMount`, and `revalidateOnFocus`.

### Mutations

SWR supports mutation operations, allowing data to be updated both on the client and server sides. It provides optimistic updates, where the UI reflects changes immediately, and the server is updated asynchronously. This is particularly useful in applications where users expect immediate feedback, such as form submissions or data edits.

## Integration with React

### Basic API Integration

To start using SWR, you need to install the package and import the `useSWR` hook. This hook takes a key and a fetcher function and returns the state of the data, including loading and error states.

Here’s an example of fetching user data from an API:

```jsx
import useSWR from 'swr';

const fetcher = (url) => fetch(url).then(res => res.json());

function User({ id }) {
  const { data, error } = useSWR(`/api/users/${id}`, fetcher);

  if (error) return <div>Error loading user</div>;
  if (!data) return <div>Loading...</div>;

  return (
    <div>
      <h1>{data.name}</h1>
      <p>Email: {data.email}</p>
    </div>
  );
}
```

In this example, the component fetches user data when the `id` prop changes. If the data is available in the cache, it is returned immediately. If not, a new request is made.

### Caching Behavior and Configuration

You can control caching behavior using options passed to `useSWR`. For example:

```jsx
const { data, mutate } = useSWR('/api/data', fetcher, {
  revalidateOnMount: true,
  revalidateOnFocus: false,
  refreshInterval: 5000,
});
```

- `revalidateOnMount`: Whether to revalidate when the component mounts. Default is `true`.
- `revalidateOnFocus`: Whether to revalidate when the window is focused. Default is `true`.
- `refreshInterval`: Polling interval in milliseconds for periodic revalidation.

You can also configure global settings using the `SWRConfig` component:

```jsx
import { SWRConfig } from 'swr';

function App() {
  return (
    <SWRConfig value={{
      refreshInterval: 3000,
      shouldRetryOnError: false
    }}>
      {/* Your app components */}
    </SWRConfig>
  );
}
```

### Optimistic Updates

Optimistic updates allow the UI to reflect changes immediately before the server confirms them. This improves perceived responsiveness and user experience.

Here’s an example of adding a new item with optimistic updates:

```jsx
import useSWR, { mutate } from 'swr';

function AddTodoForm() {
  const handleSubmit = async (e) => {
    e.preventDefault();
    const newTodo = { id: Date.now(), text: e.target.todo.value, done: false };

    // Optimistically update the UI
    mutate('/api/todos', [...(await mutate('/api/todos') || []), newTodo]);

    // Submit to the server
    await fetch('/api/todos', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(newTodo)
    });
  };

  return (
    <form onSubmit={handleSubmit}>
      <input name="todo" placeholder="New todo" />
      <button type="submit">Add</button>
    </form>
  );
}
```

In this example, the `mutate` function is used to optimistically update the cached data before sending the actual request to the server. If the server returns an error, the optimistic update can be rolled back using the `undo` function.

## Use Cases and Best Practices

### Pagination and Infinite Scrolling

SWR supports pagination by passing a dynamic key that changes with each page request. This is especially useful for loading more data as the user scrolls.

```jsx
import useSWRInfinite from 'swr/infinite';

function usePaginatedData() {
  const getKey = (pageIndex, previousPageData) => {
    if (previousPageData && !previousPageData.hasNextPage) return null;
    return `/api/data?page=${pageIndex + 1}`;
  };

  const { data, size, setSize } = useSWRInfinite(getKey, fetcher);

  const loadMore = () => setSize(size + 1);

  return { data, loadMore };
}
```

This pattern allows efficient data loading while preventing unnecessary requests when the end of the dataset is reached.

### Error Handling and Retry Logic

SWR provides built-in error handling and retry mechanisms. You can customize how many times a failed request should be retried and the delay between retries using the `shouldRetryOnError` and `errorRetryCount` options.

```jsx
const { data, error, mutate } = useSWR('/api/data', fetcher, {
  errorRetryCount: 3,
  shouldRetryOnError: (error, { retryCount }) => retryCount < 3
});
```

You can also implement custom retry logic using `mutate`:

```jsx
const retry = () => mutate();
```

### Cross-Component Data Sharing

SWR keys are shared across components, which means that if multiple components use the same key, they will share the same cache. This is ideal for synchronizing data across different parts of the application.

```jsx
function UserList() {
  const { data } = useSWR('/api/users', fetcher);
  return <div>{data?.map(user => <UserCard key={user.id} user={user} />)}</div>;
}

function UserDetails({ id }) {
  const { data } = useSWR(`/api/users/${id}`, fetcher);
  return <div>{data?.name}</div>;
}
```

In this example, both components use the same base key (`/api/users`), but the `UserDetails` component uses a more specific key. SWR will cache the base data and reuse it where appropriate.

## Comparison with Alternatives

SWR can be compared with libraries like `React Query` and `RTK Query`. While React Query provides a more comprehensive set of tools, SWR is lighter and better suited for applications that require fast and simple data fetching with minimal configuration.

RTK Query is tightly coupled with Redux and is more suitable for large-scale applications with complex state management needs.

## Common Pitfalls and Troubleshooting

### 1. **Incorrect Key Usage**

Ensure that the key passed to `useSWR` is unique and consistent for the same data. Using dynamic keys incorrectly can lead to stale or inconsistent data.

### 2. **Overuse of Mutations**

Mutate only when necessary. Excessive use of `mutate` can lead to unnecessary re-renders and performance issues.

### 3. **Missing Error Handling**

Always include error handling in your components to provide a better user experience.

## Conclusion

SWR is a robust and efficient data fetching solution that simplifies handling async data in React applications. Its use of the stale-while-revalidate pattern ensures fast data access while minimizing unnecessary requests. With features like caching, optimistic updates, and pagination support, SWR is an excellent choice for building responsive and scalable applications.

When used correctly, SWR can significantly reduce boilerplate code and improve the developer experience. It is particularly well-suited for applications where fast data access and consistent UI state are critical.

For further reading, refer to the official SWR documentation and explore cross-references like **[Data fetching (40)]** and **[Custom hooks (08)]** for deeper insights into data fetching patterns in React.