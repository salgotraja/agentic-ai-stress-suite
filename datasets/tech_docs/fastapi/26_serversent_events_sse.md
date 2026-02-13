# Server-Sent Events (SSE)

Server-Sent Events (SSE) is a communication protocol that allows a server to push real-time updates to a web browser or client over HTTP in a one-way, persistent connection. Unlike WebSockets, which provide full-duplex communication, SSE is designed for unidirectional communication from server to client, making it ideal for scenarios like live news feeds, progress updates, or real-time notifications.

SSE leverages standard HTTP and supports reconnection, message IDs, and data streaming. It works well in environments where WebSockets may not be supported or where a lightweight alternative is needed. In this documentation, we explore the implementation of SSE using FastAPI, a high-performance Python framework for building APIs.

---

## SSE Implementation in FastAPI

FastAPI simplifies SSE implementation through its support for asynchronous endpoints and streaming responses. You can create an endpoint that yields data incrementally, with each yield corresponding to an event sent to the client.

### Basic SSE Setup

Here's a basic SSE endpoint in FastAPI that sends a sequence of messages:

```python
from fastapi import FastAPI, Response
import time

app = FastAPI()

@app.get('/sse')
async def sse_endpoint():
    def sse_generator():
        for i in range(1, 6):
            time.sleep(1)  # Simulate delay
            yield f"data: Message {i}\n\n"

    return Response(sse_generator(), media_type='text/event-stream')
```

This endpoint streams five messages at one-second intervals. The `media_type='text/event-stream'` tells the client the connection is an SSE stream. Each event is separated by `\n\n`, and the `data:` field defines the message content.

---

## Event Streams

An SSE stream can include multiple types of events, each with an identifier and optional custom fields. This allows clients to filter or process events differently based on their type.

```python
@app.get('/sse_events')
async def sse_with_events():
    def sse_generator():
        yield "event: notification\ndata: System update available\nid: 1\n\n"
        yield "event: status\ndata: All systems normal\nid: 2\n\n"
        yield "event: progress\ndata: Task 50% complete\nid: 3\n\n"

    return Response(sse_generator(), media_type='text/event-stream')
```

In this example, the client can listen specifically for `progress` or `notification` events using the `event:` field. The `id:` field is used for reconnection logic.

---

## Reconnection Handling

SSE supports automatic reconnection if the connection drops. The client will attempt to reconnect to the same endpoint after a default delay. You can also control reconnection intervals using the `retry:` field.

```python
@app.get('/sse_reconnect')
async def sse_with_retry():
    def sse_generator():
        yield "retry: 5000\n\n"  # 5 seconds
        for i in range(1, 6):
            yield f"data: Message {i}\n\n"

    return Response(sse_generator(), media_type='text/event-stream')
```

The `retry:` field specifies the number of milliseconds the client should wait before attempting to reconnect. This is particularly useful in unstable or mobile network environments.

---

## Message Formatting and Customization

SSE messages can include multiple fields, including:

- `data`: The message content.
- `id`: A unique identifier for the event stream position.
- `event`: A type or category for the message.
- `retry`: The recommended reconnection delay.

These fields can be used together to create more structured and robust communication between client and server.

### Example with Multiple Fields

```python
@app.get('/sse_multi')
async def sse_multi_fields():
    def sse_generator():
        yield "id: 1\nevent: status\ndata: Initializing...\n\n"
        time.sleep(1)
        yield "id: 2\nevent: progress\ndata: 25%\n\n"
        time.sleep(1)
        yield "id: 3\nevent: progress\ndata: 50%\n\n"
        time.sleep(1)
        yield "id: 4\nevent: completion\ndata: Task completed\n\n"

    return Response(sse_generator(), media_type='text/event-stream')
```

This example demonstrates a multi-part progress stream, where the client can listen for specific events (`progress`, `completion`) and track the stream using the `id` field.

---

## Client-Side Handling of SSE

On the client side, you can use the `EventSource` API to connect to the SSE endpoint and listen for events.

```javascript
const eventSource = new EventSource('http://localhost:8000/sse_multi');

eventSource.addEventListener('progress', function(event) {
    console.log('Progress update:', event.data);
});

eventSource.addEventListener('completion', function(event) {
    console.log('Task completed:', event.data);
});

eventSource.addEventListener('message', function(event) {
    console.log('General message:', event.data);
});

eventSource.onerror = function(event) {
    console.error('SSE error:', event);
};
```

The `EventSource` API handles reconnection and message parsing automatically. You can also register listeners for specific event types and handle messages accordingly.

---

## Practical Use Cases

### Progress Updates for Long Tasks

SSE is ideal for showing progress for long-running tasks. For example, a file upload or background job can report status updates to the user in real time.

### Real-Time Notifications

SSE can be used to push notifications to users without polling the server. For example, a task management app can notify users when a task is assigned or updated.

### Live Data Feeds

SSE is well-suited for live financial data, news feeds, or social media updates where the client needs to receive real-time updates without constant polling.

---

## Best Practices

### 1. Use Async Endpoints for Scalability

When using FastAPI, always implement SSE endpoints as `async def` for non-blocking I/O, especially when dealing with many clients or long-running tasks.

### 2. Implement Proper Idempotency and Reconnection

Ensure that the server can resume the stream from the last known position by using the `id` field. Clients can send the `Last-Event-ID` header to request events from a specific point.

### 3. Handle Errors and Timeouts

Always include error handling on the client side to manage disconnections, timeouts, or malformed messages. Use the `onerror` event handler to log or retry connections.

### 4. Optimize Performance with Caching

Avoid unnecessary computations on every request. Use caching or connection pooling where appropriate to reduce server load.

### 5. Secure SSE Endpoints

Protect SSE endpoints with authentication and authorization. Use HTTP Basic Auth, JWT, or session cookies to ensure only authorized clients receive data.

---

## Comparisons and Alternatives

### WebSockets vs. SSE

| Feature               | WebSockets                  | SSE                         |
|-----------------------|-----------------------------|-----------------------------|
| Directionality        | Full-duplex                 | One-way (server to client)  |
| Reconnection Support  | Manual                      | Automatic                   |
| Protocol Complexity   | Higher                      | Simpler                     |
| Browser Support       | Good                        | Excellent                   |
| Use Case              | Chat, gaming                | Notifications, progress     |

WebSockets are better suited for bidirectional communication, while SSE is ideal for one-way data streams with automatic reconnection and lightweight overhead.

### Streaming vs. Polling

Compared to HTTP polling, SSE reduces latency and network overhead by maintaining a single open connection. Polling can be inefficient for real-time updates due to repeated requests and potential delays.

---

## Troubleshooting and Common Pitfalls

### 1. CORS and Preflight Requests

Ensure that your FastAPI application includes CORS middleware when serving SSE endpoints from a different origin.

```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)
```

### 2. Incorrect MIME Type

Clients expect the `Content-Type` to be `text/event-stream`. If the server returns a different type, the client may not recognize the stream.

### 3. Missing Newline Character

Each SSE message must end with `\n\n`. Missing this can cause clients to wait indefinitely for a complete message.

### 4. Server-Side Timeouts

Ensure your server and reverse proxies (like NGINX) are configured to keep connections open for long enough to stream messages.

---

## Conclusion

Server-Sent Events offer a powerful and efficient way to implement real-time updates in web applications. With FastAPI, you can build robust, scalable SSE endpoints using asynchronous generators and standard HTTP. By leveraging event types, reconnection strategies, and message formatting, you can create flexible and maintainable communication channels for progress tracking, notifications, and more. Always consider the trade-offs between SSE and alternatives like WebSockets to choose the best fit for your use case.