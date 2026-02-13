# React Native Fundamentals

React Native is a powerful open-source framework for building mobile applications using JavaScript and React. It allows developers to write code once and deploy it to both iOS and Android platforms with a single codebase. Built on top of the React JavaScript library, React Native leverages native components under the hood, offering performance closer to native apps than hybrid frameworks like Cordova or Ionic.

This document provides in-depth coverage of the fundamental concepts, core components, and best practices in React Native, with practical examples tailored for senior engineers.

---

## Core Concepts

At the heart of React Native are the following principles:

- **Declarative UI**: Like React, UI is described using components and declarative syntax.
- **Component-Based Architecture**: UI is composed of reusable, self-contained components.
- **JSX**: JavaScript syntax extension used to write UI logic in a more readable format.
- **Platform-Aware Rendering**: Conditional rendering allows for platform-specific UI and behavior.

### React Native and React

React Native builds upon React’s core concepts like components, props, state, and the virtual DOM. However, unlike React for web, React Native does not use HTML or CSS directly. Instead, it uses a custom rendering pipeline to map components to native views.

---

## Core Components

React Native comes with a set of built-in components that map to native UI elements. These include:

- `View`: A container component for layout.
- `Text`: Renders text.
- `Image`: Displays images.
- `TouchableOpacity`, `Button`: Interactive components for user actions.
- `ScrollView`, `FlatList`, `SectionList`: For rendering lists and scrollable content.

Here is a simple component using these core components:

```jsx
import React from 'react';
import { View, Text, Button, Image } from 'react-native';

const WelcomeScreen = () => {
  return (
    <View style={{ padding: 20, backgroundColor: '#f0f0f0' }}>
      <Image
        source={require('./logo.png')}
        style={{ width: 100, height: 100, alignSelf: 'center' }}
      />
      <Text style={{ fontSize: 24, textAlign: 'center', marginVertical: 10 }}>
        Welcome to React Native
      </Text>
      <Button
        title="Get Started"
        onPress={() => alert('Button clicked!')}
      />
    </View>
  );
};

export default WelcomeScreen;
```

This example demonstrates how to build a basic UI using core components. The `Image` is loaded using a local file path, and the `Button` triggers an alert when pressed.

---

## Styling in React Native

React Native does not use CSS, but it uses a JavaScript object-based syntax for styling. Styles are created using the `StyleSheet.create()` API for better performance and reusability.

### Example of Styling

```jsx
import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

const StyledComponent = () => {
  return (
    <View style={styles.container}>
      <Text style={styles.text}>Hello, React Native!</Text>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#e6e6e6',
  },
  text: {
    fontSize: 20,
    fontWeight: 'bold',
    color: '#333',
  },
});

export default StyledComponent;
```

### Key Styling Concepts

| Concept | Description |
|--------|-------------|
| `flexbox` | Layout using the flexbox model (similar to CSS flexbox) |
| `flexDirection` | Direction of layout items (row/column) |
| `justifyContent` | Alignment along the main axis |
| `alignItems` | Alignment across the cross axis |
| `padding`, `margin` | Spacing similar to CSS |
| `width`, `height` | Should be used carefully due to platform differences |

---

## Platform Differences and Conditional Rendering

React Native apps must account for differences between iOS and Android. This can be done using `Platform.select()` or by detecting the OS within the code:

```jsx
import { Platform, Text, View } from 'react-native';

const PlatformSpecificMessage = () => {
  return (
    <View>
      <Text>
        {Platform.select({
          ios: 'This is running on iOS.',
          android: 'This is running on Android.',
          default: 'Unknown platform',
        })}
      </Text>
    </View>
  );
};
```

### When to Use Platform Checks

Platform checks should be used sparingly and only when necessary. Prefer writing cross-platform compatible UI first, and only use platform-specific logic for:

- Different layout behavior.
- Platform-specific APIs (e.g., Android `BackHandler`, iOS `StatusBar`).
- Handling different navigation patterns.

---

## Cross-Platform Components

React Native provides a number of cross-platform components that abstract away platform differences. Examples include:

- `TouchableOpacity`: Works consistently on both platforms.
- `ActivityIndicator`: A loading spinner.
- `Modal`: Platform-specific modals with consistent API.

However, for more complex UI patterns, it's sometimes better to use third-party libraries like:

- `react-native-modal` for advanced modals.
- `react-native-reanimated` for animations.
- `react-native-paper` for Material UI components.

---

## Native Modules and Bridging

For integrating native code, React Native allows developers to write native modules for iOS (Swift/Objective-C) and Android (Java/Kotlin) and call them from JavaScript.

### Example: Native Module for Battery Level (Java)

```java
// Android: BatteryModule.java
public class BatteryModule extends ReactContextBaseJavaModule {
    public BatteryModule(ReactApplicationContext reactContext) {
        super(reactContext);
    }

    @ReactMethod
    public void getBatteryLevel(Callback successCallback, Callback errorCallback) {
        try {
            BatteryManager batteryManager = (BatteryManager) getReactApplicationContext()
                .getSystemService(Context.BATTERY_SERVICE);
            int batteryLevel = batteryManager.getIntProperty(BatteryManager.BATTERY_PROPERTY_CAPACITY);
            successCallback.invoke(batteryLevel);
        } catch (Exception e) {
            errorCallback.invoke(e.getMessage());
        }
    }

    @Override
    public String getName() {
        return "Battery";
    }
}
```

### Registering the Native Module

On Android, register the module in `MainApplication.java`:

```java
@Override
protected List<ReactPackage> getPackages() {
    return Arrays.<ReactPackage>asList(
        new MainReactPackage(),
        new ReactPackage() {
            @Override
            public List<NativeModule> createNativeModules(ReactApplicationContext reactContext) {
                return Arrays.asList(
                    new BatteryModule(reactContext)
                );
            }
        }
    );
}
```

### Calling the Native Module from JavaScript

```jsx
import { NativeModules } from 'react-native';

const { Battery } = NativeModules;

Battery.getBatteryLevel(
  (level) => {
    console.log(`Battery Level: ${level}%`);
  },
  (error) => {
    console.error('Battery Module Error:', error);
  }
);
```

> **Note**: While native modules offer deep access to device features, they add complexity and reduce maintainability. Always consider using existing libraries or React Native APIs first.

---

## Performance and Best Practices

### Use `PureComponent` or `React.memo`

To avoid unnecessary re-renders, especially in large lists, use `React.memo` for functional components or `PureComponent` for class components.

```jsx
import React, { memo } from 'react';
import { View, Text } from 'react-native';

const MemoizedListItem = memo(({ item }) => (
  <View style={{ padding: 10, borderBottomWidth: 1 }}>
    <Text>{item}</Text>
  </View>
));

export default MemoizedListItem;
```

### Use FlatList for Large Lists

For rendering large datasets, prefer `FlatList` over `ScrollView` to benefit from virtualization and on-demand rendering:

```jsx
import React from 'react';
import { FlatList, Text, View } from 'react-native';

const DATA = Array.from({ length: 100 }, (_, i) => `Item ${i + 1}`);

const ListScreen = () => {
  return (
    <FlatList
      data={DATA}
      keyExtractor={(item) => item}
      renderItem={({ item }) => (
        <View style={{ padding: 15, borderBottomWidth: 1 }}>
          <Text>{item}</Text>
        </View>
      )}
    />
  );
};

export default ListScreen;
```

> **Best Practice**: Always provide `keyExtractor` when using `FlatList` or `SectionList`.

---

## Error Handling and Debugging

React Native apps can encounter a variety of issues, especially when dealing with asynchronous code or third-party libraries.

### Common Errors

- **Redbox Errors**: Appear in the developer menu. Useful for debugging JavaScript errors.
- **Native Crashes**: Hard-to-catch native exceptions. Use `adb logcat` for Android or Xcode logs for iOS.
- **Network Requests**: Use `fetch` or `axios`, and wrap in try/catch blocks:

```jsx
try {
  const response = await fetch('https://api.example.com/data');
  const data = await response.json();
  console.log(data);
} catch (error) {
  console.error('Fetch error:', error.message);
}
```

### Debugging Tools

- **React Native Debugger**: A standalone tool that supports Redux and React DevTools.
- **Remote Debugging**: Use Chrome DevTools or VS Code to debug JS code.
- **Flipper**: A native development inspection tool for React Native from Facebook.

---

## Cross-Platform Comparison with Other Frameworks

| Framework | Language | UI | Performance | Native Access | Hot Reload |
|-----------|----------|----|-------------|----------------|-------------|
| React Native | JavaScript / TypeScript | JSX | Good | Moderate to Full | Yes |
| Flutter | Dart | Widget-based | Excellent | Full | Yes |
| Ionic | JavaScript / TypeScript | HTML/CSS | Moderate | Limited | Yes |
| Xamarin | C# | XAML | Good | Full | No |

React Native excels in rapid development and ecosystem maturity, but may lag in performance compared to Flutter. However, Flutter's widget-based architecture is less familiar to React developers.

---

## Real-World Use Cases

### 1. E-commerce App

A cross-platform e-commerce app can leverage React Native for:

- Product listing (using `FlatList`)
- Shopping cart (state management with Redux or Context API)
- User authentication (Firebase or custom auth)
- Push notifications (using `react-native-push-notification`)

### 2. Social Media App

React Native can power UI-heavy apps like:

- News feed (using `FlatList` + `react-native-reanimated`)
- Comment threads (nested lists)
- User profiles (with conditional rendering based on device)

---

## Conclusion

React Native is a powerful tool for building high-quality mobile applications with a single codebase. By mastering its core concepts—components, styling, platform differences, and native integration—developers can build apps that are performant, maintainable, and scalable.

Understanding when to use native modules, when to leverage third-party libraries, and when to build custom components is critical for senior engineers aiming to build production-grade applications. With the right patterns and practices, React Native can be a top choice for mobile development in both small teams and enterprise environments.