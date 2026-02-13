# WebSockets and Server-Sent Events in FastAPI

Real-time communication is a critical feature in modern web applications, enabling live updates, chat systems, notifications, and collaborative tools. FastAPI, being built on top of Starlette and compatible with modern async frameworks like Uvicorn, provides robust and efficient support for both WebSockets and Server-Sent Events (SSE), two of the most commonly used protocols for real-time data transfer. This document explores how to implement and manage WebSockets and SSE with FastAPI, covering their use cases, implementation details, and best practices.

---

## Understanding WebSockets and Server-Sent Events

### WebSockets

WebSockets provide a full-duplex communication channel over a single TCP connection. Unlike HTTP, which is request-response based, WebSockets allow both the server and client to send data at any time, making them ideal for applications requiring high interactivity or frequent updates.

**Use Cases**:
- Live chat and messaging
- Real-time gaming
- Collaborative document editing
- IoT data streaming

### Server-Sent Events (SSE)

SSE is a simpler protocol for one-way communication from the server to the client. It works over HTTP and allows the server to push updates to the client as they become available. Unlike WebSockets, SSE is unidirectional and uses standard HTTP, which simplifies deployment behind proxies and load balancers.

**Use Cases**:
- Live news feeds
- Notifications and status updates
- Stock ticker or weather updates

---

## Implementing WebSockets in FastAPI

FastAPI supports WebSockets through its integration with Starlette's WebSocket module. A WebSocket endpoint is defined using the `@app.websocket()` decorator.

### Basic WebSocket Endpoint

```python
from fastapi import FastAPI, WebSocket
from fastapi.responses import HTMLResponse

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Message received: {data}")
```

This endpoint accepts a connection, then enters a loop where it receives text messages and sends them back.

### Broadcasting Messages

WebSockets are often used for broadcasting to multiple connected clients. This can be achieved by maintaining a list of connected clients.

```python
from fastapi import FastAPI, WebSocket
import asyncio

app = FastAPI()
connected_clients = set()

@app.websocket("/ws/broadcast")
async def broadcast_websocket(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            for client in connected_clients:
                await client.send_text(f"Broadcast: {data}")
    finally:
        connected_clients.remove(websocket)
```

**Considerations**:
- Ensure `await websocket.receive_text()` is inside a loop or managed correctly to prevent connection hangs.
- Handle disconnections gracefully to avoid memory leaks.
- Use `asyncio.sleep()` or `await asyncio.get_event_loop().create_task()` for rate limiting or throttling.

---

## Implementing Server-Sent Events (SSE) in FastAPI

SSE is implemented in FastAPI by streaming a continuous HTTP response using the `EventSourceResponse` class.

### Basic SSE Endpoint

```python
from fastapi import FastAPI
from fastapi.responses import EventSourceResponse
from datetime import datetime
import asyncio

app = FastAPI()

@app.get("/sse")
async def sse_endpoint():
    async def event_generator():
        while True:
            current_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            yield f"data: {current_time}\n\n"
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())
```

This endpoint sends the current time every second.

### Sending Events on Demand

Sometimes you need to push events based on server-side events or external triggers. This can be done using a global queue or async event handler.

```python
from fastapi import FastAPI, BackgroundTasks
from fastapi.responses import EventSourceResponse
from datetime import datetime
import asyncio
import random

app = FastAPI()
event_queue = asyncio.Queue()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(event_producer())

async def event_producer():
    while True:
        await asyncio.sleep(random.uniform(1, 3))
        event_queue.put_nowait(f"data: {datetime.now()}\n\n")

@app.get("/sse-dynamic")
async def dynamic_sse():
    async def event_stream():
        while True:
            event = await event_queue.get()
            yield event

    return EventSourceResponse(event_stream())
```

This setup allows for dynamic, event-driven SSE updates from server-side logic.

---

## Comparing WebSockets and SSE in FastAPI

| Feature                     | WebSockets                                 | Server-Sent Events (SSE)                     |
|---------------------------|--------------------------------------------|---------------------------------------------|
| Communication Direction   | Full-duplex                                | Unidirectional (server to client)           |
| Connection Type           | Persistent TCP connection                  | Persistent HTTP connection                  |
| Protocol Complexity       | More complex (handshaking, framing)        | Simpler (standard HTTP with `text/event-stream`) |
| Reconnection Handling     | Requires custom logic                      | Automatic reconnection via `retry` field    |
| Scalability               | More scalable with message brokers         | Limited by HTTP session management          |
| Performance               | Higher throughput for frequent messages    | Lower overhead for simple updates           |
| Browser Support           | Good                                       | Good                                        |

Use WebSockets when you need two-way communication, and SSE when a simple, one-way stream is sufficient.

---

## Best Practices and Production Considerations

### Connection Management

- **WebSocket**: Always close connections gracefully when clients disconnect. Use a `try...finally` block to remove clients from the connected set.
- **SSE**: Use `keep-alive` and `retry` headers for better client behavior during network issues.

### Scalability and Load Balancing

- **WebSockets**: Use a load balancer that supports sticky sessions to ensure clients connect to the same backend node. For larger applications, consider using message brokers like Redis or RabbitMQ to broadcast messages across servers.
- **SSE**: SSE over HTTP can be more easily load-balanced, but the server must maintain session state for each connection. Consider using HTTP/2 and multiplexing for better performance.

### Error Handling and Client Reconnection

- Implement retry logic on the client side using the `EventSource` API's retry mechanism.
- On the server side, log disconnections and send heartbeat messages to keep the connection alive.

```javascript
// Example client-side retry logic
const eventSource = new EventSource('/sse-dynamic');
eventSource.addEventListener('error', (e) => {
    console.error('SSE error occurred, retrying...');
    setTimeout(() => {
        window.location.reload();
    }, 5000);
});
```

### Security Considerations

- Always authenticate and authorize WebSocket and SSE connections using tokens or session cookies.
- Use HTTPS and `wss://` for secure communication.
- Apply rate limiting to prevent abuse.

---

## Use Cases and Real-World Examples

### Live Chat Application

A chat application can use WebSockets for real-time messaging and SSE for notifications of new messages or user activity.

```python
@app.websocket("/chat/{room_id}")
async def chat_websocket(websocket: WebSocket, room_id: str):
    await websocket.accept()
    # Add to room-specific group
    while True:
        message = await websocket.receive_text()
        # Broadcast to all users in the same room
        # (using Redis or in-memory room management)
        await broadcast_to_room(room_id, message)
```

### Real-Time Analytics Dashboard

An analytics dashboard can use SSE to receive updates from the backend about user activity or system metrics.

```python
@app.get("/analytics/stream")
async def analytics_stream():
    async def event_stream():
        while True:
            data = await fetch_realtime_data()
            yield f"data: {data}\n\n"
            await asyncio.sleep(5)

    return EventSourceResponse(event_stream())
```

### Collaborative Tools

WebSockets enable collaborative tools like real-time document editors or whiteboards by allowing bidirectional communication between clients and server.

---

## Troubleshooting Common Issues

### WebSockets Not Connecting

**Symptoms**:
- `WebSocket connection failed`
- No handshake or handshake timeout

**Possible Causes**:
- Incorrect endpoint URL (`ws://` instead of `wss://`)
- Missing `Upgrade: websocket` header in request
- Load balancer or proxy not supporting WebSockets

**Solutions**:
- Ensure correct URL and use secure `wss://` in production
- Configure proxy to pass WebSocket connections

### SSE Not Receiving Events

**Symptoms**:
- No events received or connection drops
- No retry behavior from the client

**Possible Causes**:
- Server not sending valid `data` or `id` fields
- Network timeouts or proxies closing idle connections
- Missing `Content-Type: text/event-stream`

**Solutions**:
- Add `retry:` lines in SSE messages
- Use `keep-alive` headers or heartbeat events
- Verify that all response headers are correct

---

## Cross-References and Further Reading

- **Async Support in FastAPI** (Section 06): FastAPI's deep integration with async and await makes it ideal for high-performance real-time applications.
- **WebSocket Advanced Features** (Section 24): Covers advanced patterns like rate limiting, authentication, and WebSocket groups.

For more on WebSockets and SSE in FastAPI, refer to the official documentation at [https://fastapi.tiangolo.com](https://fastapi.tiangolo.com) and the Starlette documentation at [https://www.starlette.io](https://www.starlette.io).

---

## Conclusion

FastAPI provides a powerful, flexible, and efficient way to implement real-time communication using both WebSockets and Server-Sent Events. WebSockets are ideal for bidirectional, high-frequency updates, while SSE is a lighter-weight option for server-to-client streaming. Understanding the trade-offs between these protocols and applying best practices for connection management, security, and scalability is essential for building robust real-time applications. With the examples and guidance provided, developers can confidently integrate real-time features into their FastAPI-based services.