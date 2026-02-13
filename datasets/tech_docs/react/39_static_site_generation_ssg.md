# Static Site Generation (SSG)

Static Site Generation (SSG) is a method of building websites where HTML pages are pre-rendered at build time, not at runtime. This approach leverages static files, which are served directly by a CDN or a web server, eliminating the need for server-side computation on every request. SSG is widely used in modern web frameworks like Next.js, Gatsby, and Nuxt.js to deliver high-performance, scalable websites with minimal infrastructure overhead.

The core idea of SSG is to generate static files early in the build process, using data sources such as markdown files, CMS data, or API responses. These static files are then deployed and served directly, resulting in faster load times, reduced server costs, and improved SEO.

## Key Concepts in SSG

### getStaticProps

In frameworks like Next.js, `getStaticProps` is a function that runs at build time to fetch data required to render a page. It is used to populate page props with dynamic content from external sources such as APIs, databases, or markdown files.

```javascript
export async function getStaticProps(context) {
  const res = await fetch('https://api.example.com/posts');
  const posts = await res.json();

  return {
    props: {
      posts,
    },
  };
}
```

This function allows developers to inject dynamic data into static pages, making them suitable for content-driven websites. It is ideal for scenarios where the page content is known in advance and does not change frequently.

### getStaticPaths

When generating pages dynamically at build time, `getStaticPaths` is used in conjunction with `getStaticProps` to define the set of possible URLs that should be pre-rendered. This is particularly useful for pages that depend on dynamic parameters, such as blog posts or product pages.

```javascript
export async function getStaticPaths() {
  const res = await fetch('https://api.example.com/post-ids');
  const postIds = await res.json();

  const paths = postIds.map(id => ({
    params: { id: id.toString() },
  }));

  return {
    paths,
    fallback: false,
  };
}
```

The `fallback` option determines how the framework handles requests for paths that were not generated during the build. Setting `fallback: false` means those requests will result in a 404, while `fallback: true` allows the framework to generate the page on-demand when a request is made.

### Incremental Static Regeneration (ISR)

Incremental Static Regeneration (ISR) is a feature in Next.js that allows static pages to be regenerated in the background after the initial build. This means you can update content dynamically without rebuilding the entire site.

```javascript
export async function getStaticProps(context) {
  const res = await fetch('https://api.example.com/posts');
  const posts = await res.json();

  return {
    props: {
      posts,
    },
    revalidate: 10, // Revalidate every 10 seconds
  };
}
```

The `revalidate` key specifies the interval (in seconds) after which the page should be regenerated. ISR is ideal for content that changes infrequently but still needs to reflect updates without requiring a full rebuild.

### Build-Time Rendering

SSG relies heavily on build-time rendering, where all pages are rendered into static HTML during the build process. This approach ensures that the initial HTML a user receives is fully rendered, improving performance and SEO. Build-time rendering is contrasted with Server-Side Rendering (SSR), which generates HTML on each request and is discussed in more depth in [SSR (38)].

## Static Generation in Practice

### Example: Static Blog Page

Let’s consider a simple blog page that fetches a list of posts from an API and displays them.

```javascript
// pages/posts.js
import React from 'react';

export async function getStaticProps() {
  const res = await fetch('https://api.example.com/posts');
  const posts = await res.json();

  return {
    props: {
      posts,
    },
  };
}

export default function Posts({ posts }) {
  return (
    <div>
      <h1>Blog Posts</h1>
      <ul>
        {posts.map(post => (
          <li key={post.id}>{post.title}</li>
        ))}
      </ul>
    </div>
  );
}
```

In this example, the `getStaticProps` function fetches the blog data at build time. The resulting HTML is static and can be cached by a CDN, improving load times for end users.

### Example: Dynamic Product Page with ISR

Now consider a product page that uses dynamic routing and ISR to update content periodically.

```javascript
// pages/products/[id].js
import React from 'react';

export async function getStaticProps(context) {
  const productId = context.params.id;
  const res = await fetch(`https://api.example.com/products/${productId}`);
  const product = await res.json();

  return {
    props: {
      product,
    },
    revalidate: 60, // Revalidate every 60 seconds
  };
}

export async function getStaticPaths() {
  const res = await fetch('https://api.example.com/product-ids');
  const productIds = await res.json();

  const paths = productIds.map(id => ({
    params: { id: id.toString() },
  }));

  return {
    paths,
    fallback: true,
  };
}

export default function Product({ product }) {
  if (!product) {
    return <div>Product not found</div>;
  }

  return (
    <div>
      <h1>{product.name}</h1>
      <p>{product.description}</p>
      <p>Price: ${product.price}</p>
    </div>
  );
}
```

In this example, the page is built for each product ID found in the API. The `fallback: true` option allows the page to be generated on-demand if a new product is added after the initial build. The `revalidate` setting ensures that the page is periodically updated in the background.

## Best Practices

### Use Cases for SSG

SSG is ideal for the following use cases:

- Blogs and documentation sites
- E-commerce product listings
- Portfolio websites
- Landing pages for marketing campaigns
- Data-driven dashboards with infrequently updated data

In all of these cases, the content is either static or can be updated with acceptable latency using ISR.

### When Not to Use SSG

SSG is not the best choice for:

- Pages that require frequent updates (e.g., user dashboards, real-time scores)
- Applications with complex state or authentication
- Sites that require personalized content based on user session data

For such use cases, consider using SSR or a hybrid approach with Next.js' `getServerSideProps`.

### Performance Optimization

To maximize performance with SSG:

- Use compression (e.g., gzip, Brotli) for static assets
- Leverage CDNs to cache static HTML and assets
- Prefetch critical resources like fonts and images
- Minify and bundle JavaScript and CSS
- Use code splitting to reduce bundle size

### Edge Cases and Error Handling

When working with SSG, it’s important to consider edge cases such as:

- Missing or invalid data from APIs
- Fallback behavior when using `fallback: true`
- Handling 404 pages gracefully for unknown routes

For example, if a product is deleted from the API, the page might return an error. You can handle this by checking the response and rendering a fallback UI:

```javascript
export async function getStaticProps(context) {
  const productId = context.params.id;
  const res = await fetch(`https://api.example.com/products/${productId}`);

  if (!res.ok) {
    return {
      notFound: true,
    };
  }

  const product = await res.json();

  return {
    props: {
      product,
    },
  };
}
```

### Common Pitfalls

- **Over-fetching data**: Avoid fetching unnecessary data in `getStaticProps` to reduce build time.
- **Large build times**: If your site has thousands of pages, consider using dynamic generation with `fallback: true` to avoid long build durations.
- **Incorrect caching**: Ensure CDN and browser caching headers are set correctly for static assets.
- **Overuse of `revalidate`**: Setting a very low `revalidate` time can lead to excessive API requests and increased hosting costs.

## Cross-Reference with Next.js

In [Next.js (37)](Next.js), SSG is the preferred rendering strategy for most use cases due to its performance benefits. Next.js provides built-in support for `getStaticProps`, `getStaticPaths`, and ISR, making it easy to build content-driven sites at scale.

## Comparison with SSR

SSG should be contrasted with Server-Side Rendering (SSR), discussed in [SSR (38)](SSR). While SSR generates HTML on each request, SSG generates HTML ahead of time. This means SSG is generally faster and more scalable but less suitable for highly dynamic content.

| Feature               | SSG                         | SSR                         |
|----------------------|-----------------------------|-----------------------------|
| Rendering Time       | At build time               | At request time             |
| Performance          | High (static HTML)          | Lower (server computation)  |
| SEO                  | Excellent (pre-rendered)    | Good (rendered on server)   |
| Caching              | CDN and browser             | None (dynamic)              |
| Dynamic Content      | Limited (ISR required)      | Fully dynamic               |
| Infrastructure Cost | Low (static files)          | High (server resources)     |

## Real-World Use Cases

### Documentation Sites

Many open-source projects, such as React, GraphQL, and Next.js itself, use SSG to build their documentation sites. These sites are updated infrequently and benefit from fast load times and SEO.

### E-commerce Platforms

E-commerce platforms like Shopify and WooCommerce often use SSG for product listings and category pages. ISR is used to update product details as inventory changes.

### Marketing Campaigns

Marketing sites and landing pages are often built with SSG to ensure fast load times and high performance on first visit.

## Conclusion

Static Site Generation is a powerful technique that balances performance, scalability, and maintainability. By pre-rendering pages at build time and optionally regenerating them with ISR, SSG enables developers to build fast, SEO-friendly websites with minimal infrastructure. Frameworks like Next.js provide robust tooling to support SSG effectively, making it a go-to choice for a wide range of applications.