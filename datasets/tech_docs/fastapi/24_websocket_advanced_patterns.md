# WebSocket Advanced Patterns

WebSocket technology enables full-duplex communication between client and server, making it ideal for real-time applications like chat, dashboards, and live data feeds. While the basics of WebSocket are straightforward, building robust, scalable, and secure WebSocket applications in production requires mastering advanced patterns. This guide explores advanced WebSocket patterns using **FastAPI**, covering authentication, broadcasting, connection management, and error handling, with a focus on real-world applications and best practices.

---

## WebSocket Authentication in FastAPI

Authentication is critical when securing WebSocket connections. Unlike HTTP, WebSockets do not support middleware-based access control directly, so you must implement authentication logic manually.

### **Why Authentication Matters**

WebSocket connections can be long-lived, increasing the risk of unauthorized access. Without proper authentication, malicious users can hijack connections, send harmful messages, or overload your system.

### **Implementation Strategy**

The standard approach involves authenticating the user before upgrading the HTTP connection to WebSocket. This is typically done via a token, session cookie, or query parameter. In FastAPI, you can use `Depends` and `WebSocket` objects to perform authentication.

```python
from fastapi import FastAPI, WebSocket, Depends, HTTPException
from fastapi.security import APIKeyHeader
import jwt
from datetime import datetime

app = FastAPI()

API_KEY_HEADER = APIKeyHeader(name="X-API-Key")

async def get_current_user(websocket: WebSocket, token: str = Depends(API_KEY_HEADER)):
    try:
        payload = jwt.decode(token, "SECRET_KEY", algorithms=["HS256"])
        user_id = payload.get("sub")
        if not user_id:
            raise HTTPException(status_code=403, detail="Invalid token")
        return user_id
    except jwt.PyJWTError:
        raise HTTPException(status_code=403, detail="Invalid or expired token")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, user_id: str = Depends(get_current_user)):
    await websocket.accept()
    while True:
        data = await websocket.receive_text()
        await websocket.send_text(f"Message from user {user_id}: {data}")
```

### **Best Practices**

- Use secure tokens (e.g., JWT) to store session information.
- Avoid using query parameters in production for sensitive authentication.
- Consider rate-limiting connections per user to prevent abuse.

---

## Broadcasting with WebSockets

Broadcasting refers to sending a message from one client to all connected clients. This is essential in chat applications and real-time dashboards.

### **Implementation in FastAPI**

FastAPI does not provide built-in broadcasting, but you can manage it by storing all connected clients in a dictionary or list.

```python
from fastapi import FastAPI, WebSocket
from fastapi.websockets import WebSocketDisconnect
import asyncio

app = FastAPI()

connected_clients = set()

@app.websocket("/chat")
async def chat_websocket(websocket: WebSocket):
    await websocket.accept()
    connected_clients.add(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            for client in connected_clients:
                await client.send_text(f"Broadcast: {data}")
    except WebSocketDisconnect:
        connected_clients.remove(websocket)
```

### **Optimizing Broadcasts**

- Use background tasks for large-scale broadcasts to avoid blocking the event loop.
- Implement filters to send messages only to relevant users.
- Use Redis pub/sub for distributed systems where multiple nodes manage WebSocket connections.

### **Edge Cases to Handle**

- Clients disconnecting without sending a close message.
- Sending large messages that may not fit in memory (stream in chunks).
- Broadcasting to a subset of users (e.g., rooms or groups).

---

## Connection Management and Load Balancing

Managing WebSocket connections at scale requires careful handling of connection pooling, load balancing, and connection lifecycle.

### **Connection Pooling with FastAPI**

While FastAPI itself doesn’t manage WebSocket connection pools, you can use Redis or a database to maintain a registry of active connections.

```python
from fastapi import WebSocket
import aioredis

redis = aioredis.from_url("redis://localhost")

@app.websocket("/realtime")
async def real_time_websocket(websocket: WebSocket):
    await websocket.accept()
    user_id = "user123"  # Assume extracted from auth
    await redis.set(f"websocket:{user_id}", websocket.id)
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except WebSocketDisconnect:
        await redis.delete(f"websocket:{user_id}")
```

### **Load Balancing WebSockets**

Traditional HTTP load balancers may not work correctly with WebSockets due to sticky sessions. Ensure your load balancer supports:

- Sticky session support (e.g., using cookies or headers).
- Upgrade handling for the `Upgrade: websocket` HTTP header.
- Health checks specific to WebSocket endpoints.

---

## Error Handling and Recovery

WebSocket connections are prone to network issues and client disconnections. A robust system should handle these gracefully.

### **Error Handling in FastAPI**

Use try-except blocks around WebSocket receive and send methods. Always handle `WebSocketDisconnect` explicitly.

```python
@app.websocket("/realtime")
async def real_time_websocket(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_text()
            try:
                # Simulate an error
                if "error" in data:
                    raise ValueError("Simulated error from message")
                await websocket.send_text(f"Processed: {data}")
            except Exception as e:
                await websocket.send_text(f"Error: {str(e)}")
    except WebSocketDisconnect:
        print("Client disconnected")
```

### **Common Pitfalls**

- Failing to close the connection on exception.
- Sending data after the connection is closed.
- Not retrying or reconnecting on server-side errors.

### **Reconnection Strategies**

Clients should implement:

- Exponential backoff for reconnecting after disconnection.
- A heartbeat mechanism to detect dead connections.
- Re-authentication on reconnect.

---

## Real-World Use Cases

### **Chat Applications**

A chat app needs to manage:

- User authentication and authorization.
- Message broadcasting to groups.
- Message persistence (using a database).
- Presence detection (online/offline status).

```python
@app.websocket("/chat/{room_id}")
async def chat_room(websocket: WebSocket, room_id: str, user_id: str = Depends(get_current_user)):
    await websocket.accept()
    room_connections = rooms.get(room_id, set())
    room_connections.add(websocket)
    rooms[room_id] = room_connections

    try:
        while True:
            message = await websocket.receive_text()
            for conn in room_connections:
                if conn != websocket:
                    await conn.send_text(f"[{user_id}] {message}")
    except WebSocketDisconnect:
        room_connections.remove(websocket)
```

### **Real-Time Dashboards**

Dashboards often require:

- Polling or event-driven updates.
- Efficient message serialization (e.g., JSON, MessagePack).
- Filtering updates to relevant users.

Use Redis pub/sub or message queues to push updates from backend services to WebSockets.

---

## Advanced Patterns and Cross-Framework Comparison

### **Cross-Framework Comparison**

| Feature | FastAPI | Socket.IO (Node.js) | Django Channels |
|--------|---------|---------------------|------------------|
| Async Support | Full async | Limited async support | Async via Daphne |
| Built-in Authentication | Custom logic | JWT or session-based | Authentication middleware |
| Broadcasting | Manual | Built-in rooms | Manual |
| Scalability | High with Redis | Medium (uses rooms) | Low without proper setup |

### **Why FastAPI is a Good Choice**

- **Performance**: FastAPI is built on Starlette and supports ASGI, making it ideal for async WebSocket handling.
- **Type Safety**: Leverages Python type hints and Pydantic for validation.
- **Integration**: Works well with databases, message queues, and authentication libraries.

---

## Best Practices for Production-Ready WebSockets

### **Security Best Practices**

- Always use HTTPS and WSS (WebSocket Secure).
- Limit message size and rate to prevent DoS attacks.
- Sanitize and validate all incoming messages.
- Rotate secrets and JWT signing keys regularly.

### **Performance and Scalability**

- Use Redis or a message queue for broadcasting.
- Load balance WebSocket connections with sticky sessions.
- Avoid blocking operations in receive/send loops.

### **Monitoring and Logging**

- Log WebSocket connection and disconnection events.
- Monitor for message latency and throughput.
- Set up alerts for unexpected disconnects or errors.

### **Testing and Debugging**

- Use tools like `wscat` or Postman for testing WebSocket endpoints.
- Mock WebSocket clients in unit tests.
- Simulate disconnections and reconnections during testing.

---

## Conclusion

WebSocket enables real-time, interactive applications but requires careful design and implementation for reliability and security. FastAPI provides a powerful and flexible framework to build WebSocket-based systems with production-grade patterns. By mastering authentication, broadcasting, error handling, and connection management, you can build scalable applications like chat services, real-time dashboards, and collaborative tools. Always consider security, scalability, and maintainability when designing WebSocket-based systems.