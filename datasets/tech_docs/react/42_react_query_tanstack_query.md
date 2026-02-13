# React Query (TanStack Query)

React Query, now known as **TanStack Query**, is a powerful data fetching and state management library for React applications. It simplifies the process of managing server state by providing a declarative API for handling asynchronous operations, caching, pagination, and more. Designed with React's rendering model in mind, it offers a robust solution for handling API interactions without getting bogged down in boilerplate or complex state management logic.

This documentation will cover key concepts such as query management, mutation patterns, caching strategies, and integration with development tools like React Query Devtools. We’ll also explore advanced features like infinite scrolling, pagination, and error handling, along with best practices and comparisons to other state management or data fetching libraries like SWR.

---

## Core Concepts in TanStack Query

### Query Management

Queries in TanStack Query are defined using the `useQuery` hook. Each query is identified by a unique key and function that fetches data from an API. The library handles the lifecycle of these queries automatically, including caching, invalidation, refetching, and background synchronization.

```tsx
import { useQuery } from '@tanstack/react-query';

async function fetchUsers() {
  const response = await fetch('/api/users');
  return response.json();
}

function UserList() {
  const { data, isLoading, error } = useQuery(['users'], fetchUsers);

  if (isLoading) return <div>Loading...</div>;
  if (error) return <div>Error fetching users</div>;

  return (
    <ul>
      {data.map(user => (
        <li key={user.id}>{user.name}</li>
      ))}
    </ul>
  );
}
```

This example demonstrates a basic query. The first argument to `useQuery` is a key array (which can include dynamic parameters), and the second is the data fetching function.

### Mutations

Mutations are handled via the `useMutation` hook and are used when you need to perform write operations (POST, PATCH, DELETE). Mutations are typically used for actions like form submissions or API calls that modify server-side data.

```tsx
import { useMutation } from '@tanstack/react-query';

async function createUser(data) {
  const response = await fetch('/api/users', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  });
  return response.json();
}

function UserForm() {
  const mutation = useMutation(createUser, {
    onSuccess: (data) => {
      alert('User created successfully!');
      // Optionally invalidate a query to refresh data
    },
    onError: (error) => {
      console.error('Creation failed:', error);
    },
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    const name = e.target.name.value;
    mutation.mutate({ name });
  };

  return (
    <form onSubmit={handleSubmit}>
      <input type="text" name="name" placeholder="Enter name" required />
      <button type="submit" disabled={mutation.isLoading}>
        {mutation.isLoading ? 'Creating...' : 'Create'}
      </button>
      {mutation.isError && <div>Error: {mutation.error.message}</div>}
    </form>
  );
}
```

This `useMutation` example includes error handling, a success callback, and a UI state that reflects mutation status.

---

## Advanced Query Patterns

### Infinite Queries

Infinite scrolling is a common UI pattern for large datasets. TanStack Query supports this with the `useInfiniteQuery` hook, allowing you to paginate and fetch data incrementally.

```tsx
import { useInfiniteQuery } from '@tanstack/react-query';

async function fetchPosts({ pageParam = 1 }) {
  const response = await fetch(`/api/posts?page=${pageParam}`);
  const data = await response.json();
  return {
    posts: data.posts,
    nextPage: data.nextPage,
  };
}

function PostList() {
  const {
    data,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading,
    error,
  } = useInfiniteQuery(['infinite-posts'], fetchPosts, {
    getNextPageParam: (lastPage) => lastPage.nextPage,
  });

  if (isLoading) return <div>Loading posts...</div>;
  if (error) return <div>Error fetching posts</div>;

  return (
    <div>
      {data.pages.map((page, i) => (
        <div key={i}>
          {page.posts.map(post => (
            <div key={post.id}>{post.title}</div>
          ))}
        </div>
      ))}
      <button onClick={fetchNextPage} disabled={!hasNextPage || isFetchingNextPage}>
        {isFetchingNextPage ? 'Loading more...' : 'Load more'}
      </button>
    </div>
  );
}
```

In this example, `getNextPageParam` determines the next page number to fetch, and the UI loads data incrementally as the user scrolls.

---

## Caching and Stale Data

TanStack Query provides a flexible caching system to optimize performance and reduce redundant network calls. Queries can be configured to return stale data while fetching fresh data in the background.

```tsx
const { data, isFetching } = useQuery(
  ['posts', page],
  fetchPosts,
  {
    staleTime: 1000 * 60 * 5, // 5 minutes
    cacheTime: 1000 * 60 * 10, // 10 minutes
    refetchOnWindowFocus: false, // optional: avoid refetching on focus
  }
);
```

- **`staleTime`**: Duration to consider data fresh.
- **`cacheTime`**: Duration to keep the data in the cache after it becomes stale.
- **`refetchOnWindowFocus`**: Whether to refetch when the window regains focus.

These options help balance performance and data freshness.

---

## Devtools and Debugging

TanStack Query includes built-in **Devtools**, a browser extension and in-app UI that lets you inspect queries, mutations, and the cache.

To use it:

1. Install the browser extension or import the Devtools component.
2. Add the Devtools component to your app:

```tsx
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      {/* Your app */}
      <ReactQueryDevtools initialIsOpen={false} />
    </QueryClientProvider>
  );
}
```

The Devtools allow you to:
- Inspect query status and data.
- Simulate errors or network failures.
- Force refetches or clear the cache.
- View query keys and their dependencies.

This is invaluable for debugging and optimizing your application’s data flow.

---

## Cross-Context Comparisons

### With SWR (41)

**SWR** is another popular data fetching library for React. While both aim to simplify data fetching, TanStack Query provides more advanced features like mutations, cache invalidation, and infinite scrolling.

| Feature               | TanStack Query           | SWR                      |
|-----------------------|--------------------------|--------------------------|
| Query caching         | ✅ Yes                   | ✅ Yes                   |
| Mutations             | ✅ Yes                   | ❌ No                    |
| Infinite scrolling    | ✅ Yes                   | ❌ No                    |
| Devtools              | ✅ Built-in              | ❌ No                    |
| Data invalidation     | ✅ Query key-based       | ✅ SWR key-based         |
| Performance focus     | ✅ Heavy                 | ✅ Moderate              |

SWR is lighter and simpler for basic data fetching, but TanStack Query is better suited for applications with complex data requirements.

### With State Management (40)

While state management libraries like Redux or Zustand are great for managing local or application-wide state, they typically don't handle asynchronous API calls. TanStack Query complements these libraries by handling server state and data fetching concerns separately.

A common pattern is to use TanStack Query for API data and Redux for derived or UI state. This separation of concerns leads to more maintainable code.

---

## Best Practices

1. **Use Query Keys Wisely**  
   Query keys should be stable and unique for each data set. Use arrays to include dynamic parameters, like `['user', userId]` for user-specific data.

2. **Prefetch Data**  
   Use `queryClient.prefetchQuery` to load data before it's needed, improving perceived performance.

   ```tsx
   queryClient.prefetchQuery(['user', userId], fetchUser);
   ```

3. **Optimize for Pagination**  
   Use `useInfiniteQuery` or `keepPreviousData` to avoid flickering during pagination.

4. **Invalidate Caches Properly**  
   After mutations, invalidate queries to ensure data stays up to date.

   ```tsx
   mutation = useMutation(createPost, {
     onSuccess: () => queryClient.invalidateQueries(['posts']),
   });
   ```

5. **Avoid Over-Fetching**  
   Only fetch what you need. Use pagination, filters, or query parameters to limit data returned from the server.

6. **Use Background Refetching**  
   Keep data fresh in the background by setting `refetchInterval` or `refetchOnWindowFocus`.

7. **Handle Errors Gracefully**  
   Always include error handling in your queries and mutations:

   ```tsx
   useQuery(['data'], fetchData, {
     onError: (error) => {
       console.error('Query failed:', error);
       alert('Failed to load data');
     }
   });
   ```

---

## Real-World Use Cases

### 1. User Profile Page

Fetching and displaying a user’s profile using `useQuery`, along with a form for updating it using `useMutation`.

```tsx
function UserProfile({ userId }) {
  const { data, isLoading, error } = useQuery(['user', userId], fetchUser);
  const updateMutation = useMutation(updateUser, {
    onSuccess: () => queryClient.invalidateQueries(['user', userId]),
  });

  if (isLoading) return <div>Loading user...</div>;
  if (error) return <div>Error loading user</div>;

  const handleSubmit = (e) => {
    e.preventDefault();
    updateMutation.mutate({ userId, name: e.target.name.value });
  };

  return (
    <div>
      <h1>{data.name}</h1>
      <form onSubmit={handleSubmit}>
        <input type="text" defaultValue={data.name} name="name" />
        <button type="submit">Update</button>
      </form>
    </div>
  );
}
```

### 2. Chat Application with Infinite Scrolling

Load messages incrementally as the user scrolls, using `useInfiniteQuery` to fetch older messages.

---

## Common Pitfalls and Troubleshooting

### 1. Stale or Outdated Data

If data feels stale, ensure `staleTime` is not set too high. Consider setting `refetchOnWindowFocus: true` or using `refetchInterval`.

### 2. Duplicate Query Keys

Always use unique keys for different data requests. Avoid using the same key for different queries.

### 3. Unnecessary Refetching

Use `keepPreviousData` in `useQuery` to prevent flickering during pagination or sorting.

### 4. Missing Error Boundaries

Wrap components using queries in React Error Boundaries to handle fetch errors gracefully.

### 5. Overusing Devtools in Production

Avoid using the Devtools component in production builds to prevent performance issues or unnecessary logs.

---

## Conclusion

TanStack Query (React Query) is a robust, mature library that simplifies data fetching and state management in React applications. By leveraging its powerful features like query management, mutations, infinite scrolling, and caching, developers can build performant, scalable applications with minimal boilerplate.

Compared to alternatives like SWR or Redux, TanStack Query offers a more comprehensive solution for data-centric applications. Its integration with Devtools and support for advanced patterns make it a go-to choice for senior engineers looking to maintain clean, efficient React codebases.

By following best practices and understanding the core concepts, you can reduce unnecessary API calls, improve performance, and enhance the user experience across your application.