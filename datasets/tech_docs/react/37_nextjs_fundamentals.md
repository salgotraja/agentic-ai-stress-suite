# Next.js Fundamentals

Next.js is a powerful framework built on top of React that enables server-side rendering (SSR), static site generation (SSG), and API route handling. It simplifies the development process by providing a file-based routing system, built-in support for React components, and production-optimized features like image optimization and code splitting. This guide explores the core fundamentals of Next.js, including file-based routing, pages, API routes, and image optimization, and provides practical examples and best practices for building production-ready applications.

## File-Based Routing System

Next.js introduces a file-based routing mechanism that eliminates the need for complex configuration in routing libraries like React Router. The `pages` directory in a Next.js app acts as the routing system where each file or directory corresponds to a URL path.

For example, consider the following file structure:

```
pages/
├── index.js        // maps to /
├── about.js        // maps to /about
├── users/
│   ├── [id].js     // dynamic route: /users/[id] → /users/1
│   └── index.js    // maps to /users
```

### Dynamic Routes

Dynamic routes allow you to create paths that vary based on URL segments. This is useful for rendering data-driven pages such as user profiles, product listings, or blog posts.

```jsx
// pages/users/[id].js
import { useRouter } from 'next/router';

export default function UserPage() {
  const router = useRouter();
  const { id } = router.query;

  return (
    <div>
      <h1>User ID: {id}</h4>
      <p>This is the profile for user {id}.</p>
    </div>
  );
}
```

Next.js automatically handles the query extraction and rendering. You can also generate static paths using `getStaticPaths` for SSG:

```jsx
export async function getStaticPaths() {
  return {
    paths: [
      { params: { id: '1' } },
      { params: { id: '2' } },
    ],
    fallback: false,
  };
}
```

### Nested and Layout Routes

Although Next.js doesn't support nested routes directly within the `pages/` directory, you can simulate them using the `next.js/app` directory structure introduced in Next.js 13+. For legacy versions, use layout components to share UI across pages.

```jsx
// pages/dashboard/index.js
export default function Dashboard() {
  return (
    <div>
      <h1>Dashboard</h1>
      <p>Welcome to your dashboard.</p>
    </div>
  );
}
```

### Cross-Reference with React Router

In contrast to React Router, where routing is explicitly configured via `<Route>` components, Next.js abstracts this complexity and provides a declarative, file-based system. This reduces boilerplate and makes routing more intuitive and easier to maintain, especially in large applications.

## Pages and Server-Side Rendering (SSR)

Next.js introduces the concept of **pages**, which are individual React components used to render a single URL. These components can be enhanced with **data fetching methods** to pre-render content server-side or at build time.

### Data Fetching Methods

Next.js provides several lifecycle methods for data fetching:

- `getServerSideProps`: Fetch data on each request (SSR)
- `getStaticProps`: Fetch data at build time (SSG)
- `getStaticPaths`: Generate static paths for dynamic routes (SSG)

#### Example: SSR with `getServerSideProps`

```jsx
// pages/server-rendered.js
export default function ServerRendered({ data }) {
  return (
    <div>
      <h1>Server-Rendered Data</h1>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}

export async function getServerSideProps() {
  const res = await fetch('https://api.example.com/data');
  const data = await res.json();

  return {
    props: {
      data,
    },
  };
}
```

#### Example: SSG with `getStaticProps`

```jsx
// pages/static-rendered.js
export default function StaticRendered({ data }) {
  return (
    <div>
      <h1>Static-Rendered Data</h1>
      <pre>{JSON.stringify(data, null, 2)}</pre>
    </div>
  );
}

export async function getStaticProps() {
  const res = await fetch('https://api.example.com/data');
  const data = await res.json();

  return {
    props: {
      data,
    },
    revalidate: 60, // Re-generate every 60 seconds
  };
}
```

### When to Use SSR vs SSG

- **SSR (`getServerSideProps`)** is ideal for pages requiring real-time data, such as dashboards or private user content.
- **SSG (`getStaticProps`)** is optimal for content that changes infrequently, like blog posts or product listings. It improves performance by serving pre-rendered content from a CDN.

## API Routes

Next.js includes a built-in API route system that allows you to create serverless functions within your application. These routes are placed in the `pages/api` directory and are automatically exposed as HTTP endpoints.

### Basic API Route Example

```js
// pages/api/hello.js
export default function handler(req, res) {
  res.status(200).json({ message: 'Hello from the API!' });
}
```

This creates an endpoint at `/api/hello`, accessible via `GET`, `POST`, etc.

### Custom HTTP Methods

You can handle different HTTP methods by inspecting the `req.method` property:

```js
// pages/api/user.js
export default function handler(req, res) {
  if (req.method === 'GET') {
    res.status(200).json({ name: 'John Doe' });
  } else if (req.method === 'POST') {
    res.status(201).json({ message: 'User created' });
  } else {
    res.status(405).json({ message: 'Method not allowed' });
  }
}
```

### Edge Case Handling and Security

Best practices when building API routes include:

- Validating and sanitizing input
- Handling errors gracefully
- Using middleware for authentication
- Limiting request body size
- Returning appropriate HTTP status codes

#### Example: Middleware for Authentication

```js
// pages/api/secure.js
export default function handler(req, res) {
  const token = req.headers.authorization;

  if (!token || token !== 'your-secret-token') {
    return res.status(401).json({ message: 'Unauthorized' });
  }

  res.status(200).json({ message: 'Access granted' });
}
```

### Cross-Origin Requests (CORS)

By default, API routes are protected against CORS. To allow cross-origin requests, enable CORS explicitly:

```js
export default function handler(req, res) {
  res.setHeader('Access-Control-Allow-Origin', '*');
  res.setHeader('Access-Control-Allow-Methods', 'GET, POST, OPTIONS');

  if (req.method === 'OPTIONS') {
    return res.status(200).end();
  }

  res.status(200).json({ message: 'CORS enabled' });
}
```

## Image Optimization

Next.js includes a built-in image optimization API that automatically optimizes and resizes images for better performance. It uses the `next/image` component, which integrates with the Next.js Image Optimization endpoint.

### Basic Usage of `next/image`

```jsx
import Image from 'next/image';

export default function ProductCard() {
  return (
    <div>
      <Image
        src="/product.jpg"
        alt="Product Image"
        width={500}
        height={300}
        layout="responsive"
      />
    </div>
  );
}
```

### Benefits of `next/image`

- **Automatic resizing and format conversion** (e.g., JPEG → WebP)
- **Lazy loading** by default
- **Responsive images** using `layout="responsive"` or `layout="fill"`
- **CDN caching** for optimized images

### Best Practices for Image Optimization

- Always specify `width` and `height` to avoid layout shifts
- Use `layout="fill"` carefully, as it can cause overflow if not contained
- Use `objectFit` to control image scaling within the container
- Avoid `layout="fixed"` unless you need pixel-precise dimensions

#### Example: Optimized Responsive Image

```jsx
<Image
  src="/hero.jpg"
  alt="Hero Image"
  width={1200}
  height={600}
  layout="responsive"
  objectFit="cover"
  priority
/>
```

- `priority` loads the image earlier in the page lifecycle for above-the-fold content.
- `objectFit="cover"` ensures the image fills the container without distortion.

### Custom Image Optimization

If you want to bypass Next.js’s image optimizer, you can use the built-in `Image` component with a custom Image loader:

```jsx
import Image from 'next/image';

const customLoader = ({ src, width, quality }) => {
  return `https://custom-cdn.com/images/${src}?w=${width}&q=${quality || 75}`;
};

export default function CustomImage() {
  return (
    <Image
      loader={customLoader}
      src="my-image.jpg"
      alt="Custom Image"
      width={400}
      height={300}
    />
  );
}
```

This is useful when integrating with third-party image CDNs or legacy systems.

## Best Practices

When building Next.js applications for production, consider the following best practices:

### 1. Use `getStaticProps` and `getStaticPaths` for SSG

Leverage static generation whenever possible to reduce server load and improve performance. This is especially useful for content-based sites like blogs, e-commerce, or documentation.

### 2. Optimize Images with `next/image`

Always use the `next/image` component to take advantage of automatic optimization and lazy loading. Avoid using standard `<img>` tags in production for performance-sensitive content.

### 3. Handle Dynamic Routes with Care

When using `getStaticPaths`, ensure that the list of paths is generated reliably and doesn't include unnecessary or invalid routes. Use `fallback: false` for predictable content and `fallback: true` for dynamic data fetching on the fly.

### 4. Use API Routes for Internal Data

Avoid exposing external APIs directly in the client. Instead, use API routes to mediate between the frontend and backend. This adds a layer of abstraction and allows for authentication, caching, and rate limiting.

### 5. Enable Incremental Static Regeneration (ISR)

For content that changes infrequently but requires some update frequency, use ISR with `revalidate` in `getStaticProps`. This helps reduce build times and keeps content fresh.

### 6. Follow Naming Conventions

Use consistent and semantic file names to improve maintainability. For example:

- `index.js` for the default route (`/`)
- `[id].js` for dynamic routes
- `404.js` for custom 404 pages

### 7. Use `next/link` for Internal Navigation

Always use the `next/link` component for internal routing instead of `<a>` tags. This enables client-side navigation without full page reloads.

```jsx
import Link from 'next/link';

export default function Home() {
  return (
    <nav>
      <Link href="/about"><a>About</a></Link>
      <Link href="/contact"><a>Contact</a></Link>
    </nav>
  );
}
```

### 8. Leverage Server-Side Rendering for Dynamic Content

Use `getServerSideProps` when the content must be rendered on the server at request time, such as user-specific data or time-sensitive information.

### 9. Use TypeScript for Type Safety

TypeScript is fully supported in Next.js and can help catch errors early. Use type definitions for props, API responses, and dynamic routes to improve development ergonomics.

### 10. Monitor Performance and Optimize Builds

Use tools like `next build --profile` and browser performance tools (e.g., Lighthouse) to identify bottlenecks. Optimize loading strategies such as code splitting and asset compression.

## Troubleshooting and Common Pitfalls

### 1. Missing `Next.js` Page Not Found Error

If your app doesn't define a `404.js` page, Next.js will show a default error page. Always define a custom 404 page for a better user experience.

```jsx
// pages/404.js
export default function Custom404() {
  return <h1>404 - Page Not Found</h1>;
}
```

### 2. Over-fetching or Under-fetching in `getStaticProps`

Ensure that `getStaticProps` only fetches necessary data. Avoid calling APIs that return large payloads or unnecessary fields.

### 3. Incorrect Dynamic Route Parameters

If `router.query.id` is undefined, it means the page hasn't fully hydrated yet. Use `useRouter().isReady` to wait until the query is available.

```jsx
import { useRouter } from 'next/router';

export default function UserPage() {
  const router = useRouter();

  if (!router.isReady) return <p>Loading...</p>;

  const { id } = router.query;

  return <h1>User ID: {id}</h1>;
}
```

### 4. Image Optimization Failing in Development

Next.js doesn’t optimize images in development mode. Always test image optimization in a production build (`next build && next start`).

### 5. API Route Timeout or 500 Errors

Ensure API routes are not performing long-running operations synchronously. Use asynchronous operations with `async/await` or background workers for heavy tasks.

## Conclusion

Next.js provides a robust foundation for building scalable, high-performance React applications. By leveraging file-based routing, API routes, and built-in optimizations like image and code splitting, developers can build complex apps with minimal configuration. Understanding the strengths and limitations of SSR, SSG, and API routes is critical for making the right architectural decisions.

In senior engineering roles, it's essential to focus on maintainability, performance, and scalability. This guide has covered the core fundamentals of Next.js and provided real-world use cases and best practices to help you build production-grade applications.