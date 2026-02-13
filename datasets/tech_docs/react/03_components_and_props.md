# Components and Props

Components are the fundamental building blocks of React applications. They let you split the UI into independent, reusable pieces that can be developed and tested in isolation. Each component is essentially a JavaScript function or class that accepts inputs (called "props") and returns React elements describing what should appear on screen.

## Function Components

The simplest way to define a component is to write a JavaScript function. Function components accept a single "props" object argument and return React elements:

```javascript
function Welcome(props) {
  return <h1>Hello, {props.name}</h1>;
}
```

This function is a valid React component because it accepts a single props object with data and returns a React element. Function components are sometimes called "stateless" or "presentational" components, though with React Hooks, this distinction has become less meaningful since functional components can now have state.

Modern JavaScript allows destructuring props directly in the function signature, which is a common pattern:

```javascript
function Welcome({ name, age }) {
  return (
    <div>
      <h1>Hello, {name}</h1>
      <p>Age: {age}</p>
    </div>
  );
}
```

## Class Components

Before hooks were introduced in React 16.8, class components were necessary for using state and lifecycle methods. While less common in modern React development, you'll still encounter them in legacy code:

```javascript
class Welcome extends React.Component {
  render() {
    return <h1>Hello, {this.props.name}</h1>;
  }
}
```

Class components must extend `React.Component` and define a `render()` method that returns React elements. Props are accessed via `this.props` rather than function parameters. The React team now recommends using function components with hooks for new code, as they're simpler and avoid confusion around `this` binding.

## Rendering Components

React distinguishes between DOM tags and component elements based on capitalization. Lowercase tags like `<div>` and `<span>` represent DOM elements, while capitalized tags like `<Welcome>` represent component instances:

```javascript
// DOM element
const element = <div />;

// User-defined component
const element = <Welcome name="Sara" />;
```

When React encounters a user-defined component, it passes JSX attributes and children to the component as a single object called "props". This example renders "Hello, Sara" on the page:

```javascript
function Welcome(props) {
  return <h1>Hello, {props.name}</h1>;
}

const root = ReactDOM.createRoot(document.getElementById('root'));
const element = <Welcome name="Sara" />;
root.render(element);
```

## Composing Components

Components can reference other components in their output, enabling component composition. This is a key pattern in React architecture, similar to how object-oriented programming uses composition over inheritance:

```javascript
function Welcome({ name }) {
  return <h1>Hello, {name}</h1>;
}

function App() {
  return (
    <div>
      <Welcome name="Sara" />
      <Welcome name="Cahal" />
      <Welcome name="Edite" />
    </div>
  );
}
```

Typically, React apps have a single `App` component at the root that renders other components in a tree structure. However, when integrating React into existing applications, you might start with small leaf components like `Button` and work your way up the view hierarchy.

## Extracting Components

Don't be afraid to split components into smaller, reusable pieces. While it might seem like over-engineering initially, having a palette of reusable components pays off in larger applications. A good rule of thumb is to extract components when:

- A piece of UI is used multiple times
- A component becomes too complex to understand quickly
- A piece has clear, well-defined functionality

Consider this `Comment` component:

```javascript
function Comment({ author, text, date }) {
  return (
    <div className="Comment">
      <div className="UserInfo">
        <img className="Avatar"
          src={author.avatarUrl}
          alt={author.name}
        />
        <div className="UserInfo-name">
          {author.name}
        </div>
      </div>
      <div className="Comment-text">
        {text}
      </div>
      <div className="Comment-date">
        {formatDate(date)}
      </div>
    </div>
  );
}
```

This component is hard to change due to nesting and makes reusing individual parts difficult. Let's extract some components:

```javascript
function Avatar({ user }) {
  return (
    <img className="Avatar"
      src={user.avatarUrl}
      alt={user.name}
    />
  );
}

function UserInfo({ user }) {
  return (
    <div className="UserInfo">
      <Avatar user={user} />
      <div className="UserInfo-name">
        {user.name}
      </div>
    </div>
  );
}

function Comment({ author, text, date }) {
  return (
    <div className="Comment">
      <UserInfo user={author} />
      <div className="Comment-text">{text}</div>
      <div className="Comment-date">{formatDate(date)}</div>
    </div>
  );
}
```

Now `Avatar` and `UserInfo` can be reused throughout the application. The simplified `Comment` is also easier to understand and modify.

## Props Are Read-Only

Components must never modify their own props. Consider this sum function:

```javascript
function sum(a, b) {
  return a + b;
}
```

This is a "pure" function because it doesn't change its inputs and always returns the same result for the same inputs. In contrast, this function is impure:

```javascript
function withdraw(account, amount) {
  account.total -= amount; // Modifies input
}
```

React components must act like pure functions with respect to their props. All React components must follow this rule: **never modify props directly**. If you need to change values based on user interaction or time, use state, which is covered in the next documentation.

## Props Default Values

You can define default prop values using JavaScript default parameters or the `defaultProps` property:

```javascript
// Using default parameters (recommended)
function Greeting({ name = 'Guest' }) {
  return <h1>Hello, {name}</h1>;
}

// Using defaultProps (class components)
class Greeting extends React.Component {
  static defaultProps = {
    name: 'Guest'
  };

  render() {
    return <h1>Hello, {this.props.name}</h1>;
  }
}
```

Default parameters are generally preferred for function components as they're more aligned with standard JavaScript patterns.

## Props Destructuring Patterns

Destructuring props makes code cleaner and makes it obvious which props a component uses:

```javascript
// Without destructuring
function Profile(props) {
  return (
    <div>
      <h1>{props.name}</h1>
      <p>{props.bio}</p>
      <img src={props.avatarUrl} />
    </div>
  );
}

// With destructuring
function Profile({ name, bio, avatarUrl }) {
  return (
    <div>
      <h1>{name}</h1>
      <p>{bio}</p>
      <img src={avatarUrl} />
    </div>
  );
}
```

You can also use rest parameters to collect remaining props:

```javascript
function Button({ type, children, ...restProps }) {
  return (
    <button type={type} {...restProps}>
      {children}
    </button>
  );
}

// Usage
<Button type="submit" className="primary" onClick={handleClick}>
  Submit
</Button>
```

This pattern is useful when creating wrapper components that need to forward props to underlying DOM elements.

## The Special "children" Prop

React components can receive children elements between their opening and closing tags. These children are automatically passed as a special prop called `children`:

```javascript
function Card({ children }) {
  return (
    <div className="card">
      {children}
    </div>
  );
}

// Usage
<Card>
  <h2>Title</h2>
  <p>This is the card content</p>
</Card>
```

The `children` prop enables component composition patterns similar to slot-based composition in Vue or transclusion in AngularJS. It's particularly useful for container components that wrap arbitrary content.

## Props Validation with PropTypes

While TypeScript provides compile-time type checking, React's PropTypes library offers runtime validation during development:

```javascript
import PropTypes from 'prop-types';

function User({ name, age, email, isActive }) {
  return (
    <div>
      <h1>{name}</h1>
      <p>Age: {age}</p>
      <p>Email: {email}</p>
      <p>Status: {isActive ? 'Active' : 'Inactive'}</p>
    </div>
  );
}

User.propTypes = {
  name: PropTypes.string.isRequired,
  age: PropTypes.number,
  email: PropTypes.string.isRequired,
  isActive: PropTypes.bool
};

User.defaultProps = {
  isActive: true
};
```

PropTypes are automatically stripped from production builds, making them zero-cost in production. For TypeScript projects, interfaces or types are generally preferred over PropTypes:

```typescript
interface UserProps {
  name: string;
  age?: number;
  email: string;
  isActive?: boolean;
}

function User({ name, age, email, isActive = true }: UserProps) {
  // Component implementation
}
```

## Props vs Attributes

It's important to understand that JSX props are not the same as HTML attributes, though they often correspond. Props can be any JavaScript value, including functions, objects, or arrays:

```javascript
function TodoList({ items, onItemClick, config }) {
  return (
    <ul>
      {items.map(item => (
        <li key={item.id} onClick={() => onItemClick(item)}>
          {item.text}
        </li>
      ))}
    </ul>
  );
}

// Usage
<TodoList
  items={todos}
  onItemClick={handleItemClick}
  config={{ showCompleted: true, sortOrder: 'asc' }}
/>
```

This flexibility makes props more powerful than HTML attributes, enabling sophisticated component APIs similar to method parameters in traditional programming.

## Comparison with Other Frameworks

React's props system has influenced other modern frameworks but differs in implementation:

**Vue** uses props with similar concepts but includes a separate props definition with validation, type checking, and default values built into the component definition. Vue's props are reactive by default, automatically triggering re-renders when changed (from parent context).

**Angular** uses Input decorators for component inputs, which is more verbose but provides strong TypeScript integration and change detection: `@Input() name: string;`.

**Svelte** uses export statements for props: `export let name;`, which is less explicit but follows Svelte's minimalist syntax philosophy.

React's approach feels most like standard JavaScript function parameters, making it intuitive for developers familiar with functional programming patterns. The immutability of props enforces unidirectional data flow, making applications more predictable but requiring state management for dynamic behavior.

Understanding components and props is foundational to React development. These concepts enable the composition patterns that make React applications scalable and maintainable, allowing teams to build complex UIs from simple, reusable pieces.
