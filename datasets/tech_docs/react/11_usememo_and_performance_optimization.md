# useMemo and Performance Optimization

In React, performance optimization is a critical aspect of building scalable applications. One of the most powerful tools available for this purpose is `useMemo`, a React Hook that memoizes the result of expensive computations. By avoiding unnecessary recalculations, `useMemo` ensures that your components remain efficient, especially when rendering large datasets or performing complex logic.

This documentation dives deep into how `useMemo` works, when to apply it, and how to use it effectively in conjunction with other optimization strategies like `useCallback`.

---

## How useMemo Works

At its core, `useMemo` caches the result of a function and returns it only when one of its dependencies changes. This is particularly useful when dealing with expensive computations that do not need to re-run on every render.

The signature of `useMemo` is:

```js
const memoizedValue = useMemo(() => computeExpensiveValue(a, b), [a, b]);
```

This hook takes a function and an array of dependencies. The function is only executed when any of the dependencies change. If the dependencies remain the same, the previously computed value is returned.

---

## When to Use useMemo

### 1. **Expensive Calculations**

If you have a function that performs heavy computations—such as sorting, filtering, or transforming large datasets—`useMemo` can prevent redundant work.

```js
const expensiveComputation = (data, filter) => {
  console.log('Computing...');
  return data.filter(item => item.includes(filter));
};

const FilteredList = ({ data, filter }) => {
  const filteredData = useMemo(() => expensiveComputation(data, filter), [data, filter]);

  return (
    <ul>
      {filteredData.map((item, index) => (
        <li key={index}>{item}</li>
      ))}
    </ul>
  );
};
```

In this example, `expensiveComputation` is only run when either `data` or `filter` changes, not on every render. This leads to significant performance improvements, especially when `data` is large.

---

### 2. **Computed Values in Lists**

When displaying lists or grids and you need to derive values (e.g., totals, averages, or derived UI states), `useMemo` ensures these values are computed once and reused efficiently.

```js
const ProductList = ({ products }) => {
  const totalValue = useMemo(() => {
    return products.reduce((sum, product) => sum + product.price * product.quantity, 0);
  }, [products]);

  return (
    <div>
      <h2>Total Value: ${totalValue.toFixed(2)}</h2>
      <ul>
        {products.map(product => (
          <li key={product.id}>{product.name} - ${product.price}</li>
        ))}
      </ul>
    </div>
  );
};
```

---

### 3. **Avoiding Prop Drilling Overhead**

When passing deeply nested components, complex objects—like computed values or derived props—can be expensive to compute repeatedly. `useMemo` helps keep these props stable between renders, reducing unnecessary re-renders.

```js
const ParentComponent = ({ items }) => {
  const processedItems = useMemo(() => {
    return items.map(item => ({
      ...item,
      formatted: `$${item.price.toFixed(2)}`,
    }));
  }, [items]);

  return <ChildComponent items={processedItems} />;
};
```

---

## How Dependency Arrays Work

The second argument to `useMemo` is a **dependency array**. React uses this to determine if the memoized value needs to be recalculated.

### Key Rules:
- **If no dependencies provided**, the value is only computed once on the initial render.
- **If the array is empty**, the same behavior occurs.
- **If the array contains values**, React will recompute the memoized value only when any of the dependencies change.

### Example: Empty Dependency Array

```js
const [count, setCount] = useState(0);

const heavyCalculation = useMemo(() => {
  console.log('Computing...');
  return expensiveFunction();
}, []); // Only computes once
```

> ⚠️ Be cautious when using empty dependency arrays in contexts where the computation should be re-evaluated based on component state or props.

---

## useMemo vs useCallback

While `useMemo` memoizes computed values, `useCallback` memoizes functions. Both are useful for optimization, but they serve different purposes.

- **useMemo**: For memoizing values (e.g., filtered lists, derived data).
- **useCallback**: For memoizing functions (e.g., event handlers, callbacks passed to child components).

```js
const Parent = () => {
  const [value, setValue] = useState('');

  const memoizedFunction = useCallback(() => {
    console.log('Function called with', value);
  }, [value]);

  const memoizedValue = useMemo(() => {
    return `Value is: ${value}`;
  }, [value]);

  return <Child onAction={memoizedFunction} message={memoizedValue} />;
};
```

- `memoizedFunction` is stable between renders unless `value` changes.
- `memoizedValue` is re-computed only when `value` changes.

---

## Best Practices for Using useMemo

### 1. **Don’t Overuse It**

Only use `useMemo` when a computation is truly expensive. It introduces overhead in tracking dependencies and managing caches. Profiling with tools like the React DevTools Performance tab is essential.

### 2. **Keep Dependency Arrays Accurate**

Incorrect or incomplete dependency arrays can lead to stale or incorrect results. Always ensure every value the function relies on is included.

```js
const [searchTerm, setSearchTerm] = useState('');
const [filterType, setFilterType] = useState('all');

const filteredData = useMemo(() => {
  if (filterType === 'active') {
    return data.filter(item => item.isActive);
  }
  return data.filter(item => item.name.includes(searchTerm));
}, [data, searchTerm]); // ❌ Missing dependency: filterType

// Correct version:
}, [data, searchTerm, filterType]);
```

---

### 3. **Avoid Memoizing Values That Change Frequently**

If a value changes on every render, memoizing it may not provide any benefit and could even hurt performance.

```js
const [counter, setCounter] = useState(0);

const memoizedCounter = useMemo(() => counter + 1, [counter]); // ❌ No benefit here

// Better to compute directly
const incremented = counter + 1;
```

---

### 4. **Use in Conjunction with React.memo**

For large component trees, `useMemo` should be paired with `React.memo` to prevent unnecessary re-renders of child components.

```js
const ChildComponent = React.memo(({ data }) => {
  return <div>{data.length} items</div>;
});

const ParentComponent = ({ items }) => {
  const processedItems = useMemo(() => items.filter(i => i.isActive), [items]);

  return <ChildComponent data={processedItems} />;
};
```

---

## Common Pitfalls and Troubleshooting

### 1. **Stale Values in Callbacks**

If you're using `useMemo` to memoize a value that is used inside a `useEffect` or `useCallback`, be cautious about stale closures.

```js
const [count, setCount] = useState(0);
const memoizedValue = useMemo(() => {
  return `Count is ${count}`;
}, [count]);

useEffect(() => {
  console.log(memoizedValue);
}, [memoizedValue]); // Correctly updates with count
```

> ✅ Ensure that the `useEffect` hook depends on the `useMemo` value if it needs to react to changes.

---

### 2. **Unstable Objects in Dependencies**

If a dependency is an object or array that's re-created on each render (e.g., from `useState({})`), `useMemo` will recompute even if the object's contents haven’t changed.

```js
const [settings, setSettings] = useState({ theme: 'dark' });

const memoizedValue = useMemo(() => {
  return `Theme is ${settings.theme}`;
}, [settings]); // ❌ settings changes on every render

// Better approach:
const theme = settings.theme;

const memoizedValue = useMemo(() => `Theme is ${theme}`, [theme]);
```

---

## Real-World Use Cases

### 1. **Filtering and Sorting UI Tables**

In applications with large datasets, `useMemo` helps manage dynamic filtering and sorting without reprocessing data every render.

```js
const TableComponent = ({ data, filter, sortKey }) => {
  const processedData = useMemo(() => {
    let sorted = [...data];
    if (sortKey) {
      sorted.sort((a, b) => a[sortKey] - b[sortKey]);
    }
    return sorted.filter(item => item.name.includes(filter));
  }, [data, filter, sortKey]);

  return (
    <table>
      <thead>
        <tr>
          <th>Name</th>
          <th>Value</th>
        </tr>
      </thead>
      <tbody>
        {processedData.map(item => (
          <tr key={item.id}>
            <td>{item.name}</td>
            <td>{item.value}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
};
```

---

### 2. **Memoizing Chart Data**

When building data visualizations, `useMemo` can help avoid recalculating datasets for each chart render.

```js
const ChartComponent = ({ data }) => {
  const chartData = useMemo(() => {
    return aggregateData(data);
  }, [data]);

  return <Chart data={chartData} />;
};
```

---

## Cross-Comparison with Other Frameworks

In Vue, **computed properties** serve a similar purpose to `useMemo`, automatically recalculating only when their reactive dependencies change. Angular’s **pure pipes** offer similar behavior but are less flexible in complex scenarios.

```js
// Vue (computed property)
computed: {
  filteredList() {
    return this.items.filter(item => item.includes(this.filter));
  }
}
```

```js
// React (useMemo)
const filteredList = useMemo(() => items.filter(item => item.includes(filter)), [items, filter]);
```

While the syntax varies, the underlying optimization strategy is consistent across frameworks.

---

## Conclusion

`useMemo` is a powerful tool for optimizing performance in React applications by avoiding redundant computations. When used correctly, it can significantly improve rendering efficiency, especially in complex component trees or large datasets.

However, it’s important to apply it judiciously and only when the cost of recomputation is high. Always profile your app before and after adding memoization to ensure it's providing real performance benefits.

By combining `useMemo` with `useCallback` and `React.memo`, you can create highly optimized, scalable applications that maintain responsiveness even under heavy load.

Remember: performance optimization is about making the right trade-offs. Use your judgment and always measure the impact.