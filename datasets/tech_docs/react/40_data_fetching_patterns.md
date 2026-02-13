# Data Fetching Patterns

In modern web applications, fetching and managing data efficiently is critical for performance, user experience, and maintainability. React applications often use a variety of patterns and libraries to fetch data from APIs, handle caching, and manage loading states. Understanding these patterns helps developers choose the right tools for their needs, from low-level Fetch API to high-level abstractions like React Query and SWR. This document explores data fetching patterns in React, including key libraries, caching strategies, and best practices.

## Fetch API and Axios for Data Fetching

The Fetch API is a native JavaScript API for making HTTP requests. It is lightweight and works out of the box in modern browsers. For more complex applications, Axios is a popular HTTP client that supports features like request/response interceptors, auto-conversion of JSON data, and better browser support via polyfills.

Here is a simple example using the Fetch API:

```javascript
fetch('https://jsonplaceholder.typicode.com/posts/1')
  .then(response => {
    if (!response.ok) {
      throw new Error('Network response was not ok');
    }
    return response.json();
  })
  .then(data => console.log(data))
  .catch(error => console.error('There was a problem with the fetch operation:', error));
```

Axios provides a more developer-friendly API and includes built-in error handling:

```javascript
import axios from 'axios';

axios.get('https://jsonplaceholder.typicode.com/posts/1')
  .then(response => console.log(response.data))
  .catch(error => {
    if (error.response) {
      console.error('Server responded with a status other than 2xx:', error.response.status);
    } else if (error.request) {
      console.error('No response received:', error.request);
    } else {
      console.error('Error setting up the request:', error.message);
    }
  });
```

Both Fetch and Axios are excellent for basic data fetching, but they lack built-in caching and state management features. As applications grow in complexity, these low-level tools may be insufficient for managing data consistency and performance.

## Data Fetching with Custom React Hooks

React developers often encapsulate data fetching logic into reusable hooks. This approach promotes separation of concerns and makes it easier to manage side effects and loading states.

Here’s an example of a custom hook using Axios:

```javascript
import { useState, useEffect } from 'react';
import axios from 'axios';

const useFetch = (url) => {
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchData = async () => {
      try {
        const response = await axios.get(url);
        setData(response.data);
      } catch (err) {
        setError(err);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [url]);

  return { data, isLoading, error };
};
```

This hook can be used in components like so:

```javascript
import React from 'react';
import { useFetch } from './useFetch';

const PostComponent = () => {
  const { data, isLoading, error } = useFetch('https://jsonplaceholder.typicode.com/posts/1');

  if (isLoading) return <div>Loading...</div>;
  if (error) return <div>Error fetching data.</div>;

  return (
    <div>
      <h2>{data.title}</h2>
      <p>{data.body}</p>
    </div>
  );
};
```

This pattern is useful for simple cases but has limitations. If multiple components fetch the same data, the hook will make redundant requests each time. It doesn't handle cache invalidation, background refetching, or stale data — all of which are crucial for real-world applications.

## Caching Strategies and Performance Optimization

Caching data on the client can significantly improve application performance and reduce server load. There are several caching strategies to consider:

- **In-memory caching**: Store fetched data in memory to avoid redundant requests.
- **Time-based caching**: Set an expiration time (TTL) for cached data to ensure it remains fresh.
- **Conditional requests**: Use HTTP headers like `ETag` and `Last-Modified` to request only updated data.
- **Stale-while-revalidate**: Serve cached data while fetching a fresh copy in the background.

Implementing in-memory caching can be as simple as adding a cache object to your custom hooks:

```javascript
const useCachedFetch = (url) => {
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const cache = useRef({});

  useEffect(() => {
    const fetchData = async () => {
      if (cache.current[url]) {
        setData(cache.current[url]);
        setIsLoading(false);
        return;
      }

      try {
        const response = await axios.get(url);
        cache.current[url] = response.data;
        setData(response.data);
      } catch (err) {
        setError(err);
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();
  }, [url]);

  return { data, isLoading, error };
};
```

This caching mechanism avoids redundant requests for the same URL. However, it does not handle cache invalidation or time-based expiration. For more advanced use cases, consider using a library that provides built-in caching and background refetching.

## SWR and React Query for Advanced Data Fetching

SWR and React Query are powerful libraries for handling data fetching in React applications. They provide built-in caching, polling, optimistic updates, and background refetching — all of which are essential for scalable applications.

### SWR (Stale-While-Revalidate)

SWR is a lightweight data fetching library by Vercel that follows the stale-while-revalidate pattern. It automatically caches data, keeps it fresh in the background, and provides a declarative API for developers.

Here's an example using SWR:

```javascript
import useSWR from 'swr';

const fetcher = (url) => fetch(url).then((res) => res.json());

const PostComponent = () => {
  const { data, error } = useSWR('https://jsonplaceholder.typicode.com/posts/1', fetcher);

  if (error) return <div>Error fetching data.</div>;
  if (!data) return <div>Loading...</div>;

  return (
    <div>
      <h2>{data.title}</h2>
      <p>{data.body}</p>
    </div>
  );
};
```

SWR automatically revalidates data when the component mounts, when the URL changes, and in the background after a defined interval. It also supports features like revalidation on focus and reconnect, which is useful for SPAs.

### React Query

React Query is a more feature-rich library that provides similar functionality to SWR but with more control over caching, background refetching, and query invalidation.

Here's a basic example using React Query:

```javascript
import { useQuery } from 'react-query';

const fetchPost = async (id) => {
  const response = await fetch(`https://jsonplaceholder.typicode.com/posts/${id}`);
  if (!response.ok) {
    throw new Error('Failed to fetch post');
  }
  return response.json();
};

const PostComponent = () => {
  const { data, error, isLoading } = useQuery(['post', 1], () => fetchPost(1));

  if (isLoading) return <div>Loading...</div>;
  if (error) return <div>Error fetching data.</div>;

  return (
    <div>
      <h2>{data.title}</h2>
      <p>{data.body}</p>
    </div>
  );
};
```

React Query allows developers to group queries by key, invalidate queries when data changes, and even refetch data in the background. It supports optimistic updates, which are useful for forms and mutations that need to reflect changes immediately before the server responds.

## Best Practices for Data Fetching

- **Avoid fetching data in render functions**: Always move data fetching logic into `useEffect` or a custom hook to prevent unnecessary re-renders and side effects during rendering.
- **Use suspense when possible**: If using React 18 or later, consider using React.lazy and Suspense for data fetching to simplify loading states and avoid the need for explicit `isLoading` flags.
- **Implement proper error handling**: Always check for network errors, HTTP status codes, and server-side errors. Provide meaningful feedback to users when something goes wrong.
- **Use caching wisely**: Don't cache data that changes frequently. Use SWR or React Query to manage caching and invalidation automatically.
- **Avoid over-fetching**: Only request the data you need. Use GraphQL or REST APIs with filtering and pagination to reduce the amount of data transferred.
- **Use TypeScript for type safety**: When working with APIs, define TypeScript interfaces to ensure type safety and reduce runtime errors.

## Common Pitfalls and Troubleshooting Tips

- **Fetching data in the wrong lifecycle**: Fetching data in render functions can cause infinite loops or unnecessary re-renders. Use `useEffect` or custom hooks instead.
- **Forgetting to clean up subscriptions or abort controllers**: If using `fetch` or `axios` directly, always clean up requests when the component unmounts to prevent memory leaks.

Example using an abort controller with Fetch API:

```javascript
import { useEffect, useState } from 'react';

const useAbortableFetch = (url) => {
  const [data, setData] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const abortController = new AbortController();

    const fetchData = async () => {
      try {
        const response = await fetch(url, { signal: abortController.signal });
        if (!response.ok) {
          throw new Error('Network response was not ok');
        }
        const result = await response.json();
        setData(result);
      } catch (err) {
        if (err.name !== 'AbortError') {
          setError(err);
        }
      } finally {
        setIsLoading(false);
      }
    };

    fetchData();

    return () => {
      abortController.abort();
    };
  }, [url]);

  return { data, isLoading, error };
};
```

This example ensures that the request is canceled when the component unmounts, preventing memory leaks.

## Cross-Reference with React Features

- **useEffect (07)**: Data fetching is typically handled inside `useEffect` to avoid side effects in render functions. It’s important to include all dependencies in the effect to ensure correct behavior.
- **Suspense (19)**: In React 18 and above, Suspense can be used in combination with libraries like React Query to handle loading states more elegantly.
- **Custom Hooks**: Custom hooks are essential for encapsulating data fetching logic and making it reusable across components.

## Conclusion

Data fetching is a central part of modern web applications, and React provides various tools and patterns to handle it efficiently. From low-level Fetch API and Axios to high-level libraries like SWR and React Query, developers have many options to choose from based on their project’s needs. Understanding caching strategies, error handling, and lifecycle management is key to building performant and user-friendly React applications.