# JSX Fundamentals

JSX (JavaScript XML) is a syntax extension for JavaScript that allows you to write HTML-like code within JavaScript. While not required to use React, JSX has become the de facto standard for writing React components due to its readability and expressiveness. Understanding JSX is fundamental to working effectively with React.

## What is JSX?

JSX looks like HTML but is actually syntactic sugar for JavaScript function calls. When you write JSX, build tools like Babel transform it into `React.createElement()` calls. This transformation happens at build time, meaning JSX never runs in the browser directly.

```javascript
// JSX syntax
const element = <h1>Hello, world!</h1>;

// Transforms to
const element = React.createElement('h1', null, 'Hello, world!');
```

The `React.createElement()` function returns a plain JavaScript object called a React element, which describes what should appear on screen. React reads these objects and uses them to construct and update the DOM efficiently.

## JSX Expressions

One of JSX's most powerful features is the ability to embed JavaScript expressions using curly braces. Any valid JavaScript expression can be embedded, including variables, function calls, arithmetic operations, and ternary operators.

```javascript
const name = 'Josh';
const element = <h1>Hello, {name}</h1>;

function formatName(user) {
  return user.firstName + ' ' + user.lastName;
}

const user = {
  firstName: 'Harper',
  lastName: 'Perez'
};

const greeting = (
  <h1>
    Hello, {formatName(user)}!
  </h1>
);
```

Expressions can appear anywhere within JSX, whether as element content, attribute values, or even as element types (when using component variables). The curly braces tell JSX to evaluate the contents as JavaScript rather than treating it as literal text.

## JSX is an Expression Too

After compilation, JSX expressions become regular JavaScript function calls that evaluate to JavaScript objects. This means you can use JSX within if statements, for loops, assign it to variables, accept it as arguments, and return it from functions.

```javascript
function getGreeting(user) {
  if (user) {
    return <h1>Hello, {formatName(user)}!</h1>;
  }
  return <h1>Hello, Stranger.</h1>;
}
```

This makes JSX feel like a natural part of JavaScript rather than a separate template language. Compare this to Angular's templates or Vue's Single File Components, where template logic is separated from JavaScript logic.

## Attributes in JSX

JSX allows you to specify attributes similar to HTML, but with some important differences. Since JSX is closer to JavaScript than HTML, React DOM uses camelCase property naming conventions instead of HTML attribute names.

```javascript
// HTML attributes
const element = <div class="container" tabindex="0"></div>;

// JSX attributes (note camelCase)
const element = <div className="container" tabIndex="0"></div>;
```

The most common naming differences include:
- `class` becomes `className`
- `for` becomes `htmlFor`
- `tabindex` becomes `tabIndex`
- `onclick` becomes `onClick`

These changes avoid conflicts with JavaScript reserved words. Event handlers in particular use camelCase (onClick, onChange, onSubmit) and receive React's synthetic event objects rather than native DOM events.

You can embed JavaScript expressions in attributes using curly braces:

```javascript
const avatarUrl = 'https://example.com/avatar.jpg';
const element = <img src={avatarUrl} alt="User avatar" />;

// Don't use quotes around curly braces
const wrong = <img src="{avatarUrl}" />; // This treats it as literal string
const correct = <img src={avatarUrl} />;
```

## Children in JSX

JSX elements can contain children, which can be text, other elements, or JavaScript expressions. If a tag is empty, you can close it immediately with `/>`, similar to XML:

```javascript
const element = <img src={user.avatarUrl} />;
```

JSX tags can contain children between opening and closing tags:

```javascript
const element = (
  <div>
    <h1>Hello!</h1>
    <h2>Good to see you here.</h2>
  </div>
);
```

Children can be mixed types, including text, elements, and expressions:

```javascript
function TodoList({ todos }) {
  return (
    <ul>
      {todos.map(todo => (
        <li key={todo.id}>
          {todo.completed && <span>✓ </span>}
          {todo.text}
        </li>
      ))}
    </ul>
  );
}
```

## JSX Prevents Injection Attacks

JSX is safe from injection attacks by default. React DOM escapes any values embedded in JSX before rendering them, ensuring that nothing unintended can be injected into your application.

```javascript
const userInput = '<script>alert("XSS")</script>';
const element = <div>{userInput}</div>;
// Renders as literal text: <script>alert("XSS")</script>
```

Everything is converted to a string before being rendered, preventing XSS (cross-site scripting) attacks. This is similar to template engines like Jinja2 or Thymeleaf that auto-escape content by default. If you genuinely need to render raw HTML (which should be rare), React provides `dangerouslySetInnerHTML`:

```javascript
const htmlContent = { __html: '<p>This is <em>raw</em> HTML</p>' };
const element = <div dangerouslySetInnerHTML={htmlContent} />;
```

The verbose name `dangerouslySetInnerHTML` is intentional, warning developers about potential security risks.

## Boolean, Null, and Undefined in JSX

React ignores boolean values, `null`, and `undefined` in JSX, rendering nothing. This behavior is useful for conditional rendering:

```javascript
function Greeting({ isLoggedIn }) {
  return (
    <div>
      <h1>Welcome</h1>
      {isLoggedIn && <p>You are logged in</p>}
      {!isLoggedIn && <p>Please log in</p>}
    </div>
  );
}
```

Be careful with falsy values like `0` or `NaN`, which React will render:

```javascript
const count = 0;
return <div>{count && <p>Count: {count}</p>}</div>;
// Renders: <div>0</div>

// Better approach
return <div>{count > 0 && <p>Count: {count}</p>}</div>;
```

## Fragments

Sometimes you need to return multiple elements from a component without adding an extra DOM node. React Fragments let you group children without adding wrapper elements:

```javascript
function Table() {
  return (
    <table>
      <tbody>
        <tr>
          <Columns />
        </tr>
      </tbody>
    </table>
  );
}

function Columns() {
  return (
    <React.Fragment>
      <td>Column 1</td>
      <td>Column 2</td>
    </React.Fragment>
  );
}
```

There's a shorter syntax using empty tags:

```javascript
function Columns() {
  return (
    <>
      <td>Column 1</td>
      <td>Column 2</td>
    </>
  );
}
```

The short syntax doesn't support keys or attributes. Use the full `<React.Fragment>` syntax when you need to pass keys, particularly in lists.

## Spread Attributes

JSX supports the spread operator for passing multiple props to components, similar to JavaScript object spreading:

```javascript
function App() {
  const props = {
    firstName: 'Ben',
    lastName: 'Hector',
    role: 'Developer'
  };

  return <Greeting {...props} />;
}

// Equivalent to
<Greeting firstName="Ben" lastName="Hector" role="Developer" />
```

This pattern is useful when forwarding props or when working with HOCs (Higher-Order Components). However, overusing spread can make prop flow harder to trace and may pass unnecessary props, so use it judiciously.

## Comments in JSX

Comments within JSX require curly braces and JavaScript comment syntax:

```javascript
function App() {
  return (
    <div>
      {/* This is a comment in JSX */}
      <h1>Hello</h1>
      {
        // This is also a comment
        // Spanning multiple lines
      }
    </div>
  );
}
```

Comments outside JSX expressions use normal JavaScript comment syntax.

## JSX Compilation and React 17+ Transform

Prior to React 17, JSX transformed into `React.createElement()` calls, requiring React to be in scope even if not explicitly used:

```javascript
import React from 'react'; // Required even if not directly used

function App() {
  return <h1>Hello</h1>;
}
```

React 17 introduced a new JSX transform that eliminates this requirement. The new transform automatically imports special functions from `react/jsx-runtime`:

```javascript
// No React import needed
function App() {
  return <h1>Hello</h1>;
}

// Transforms to
import {jsx as _jsx} from 'react/jsx-runtime';

function App() {
  return _jsx('h1', { children: 'Hello' });
}
```

This change reduces boilerplate and enables future optimizations. Most modern build tools (Create React App 4+, Next.js 11+, Vite) use the new transform by default.

## Comparison with Other Template Systems

JSX differs from template languages in frameworks like Angular, Vue, and Svelte:

**Angular Templates** use a custom syntax with directives like `*ngFor` and `*ngIf`. JSX uses plain JavaScript logic instead, which some developers find more intuitive.

**Vue Templates** use a HTML-based template syntax with directives like `v-for` and `v-if`. Vue 3's Composition API supports JSX as an alternative, giving developers flexibility similar to React.

**Svelte** uses HTML-enhanced templates with `{#each}` and `{#if}` blocks. While Svelte's approach is more template-like, it compiles to highly optimized JavaScript, whereas JSX compiles to function calls that run in a virtual DOM.

JSX's JavaScript-first approach means you leverage existing JavaScript knowledge rather than learning a template DSL, though it requires understanding the subtle differences between HTML and JSX attributes.

## Best Practices

When working with JSX, follow these conventions:

1. **Use Parentheses**: Wrap multi-line JSX in parentheses to avoid automatic semicolon insertion issues
2. **Close All Tags**: Self-closing tags must end with `/>`, like `<img />` and `<input />`
3. **Use camelCase**: Attribute names should use camelCase (className, onClick, htmlFor)
4. **Extract Complex Logic**: Move complex expressions into functions or variables for readability
5. **Consistent Formatting**: Use Prettier or similar tools to maintain consistent JSX formatting

JSX is central to the React development experience, making UI code more readable and maintainable by combining markup and logic in a natural way. Mastering JSX patterns and conventions is essential for effective React development.
