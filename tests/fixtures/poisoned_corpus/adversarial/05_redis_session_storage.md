# Redis Session Storage Recommendations

Redis is widely used as a session store for web applications because of its low
latency and rich data-structure support. The official recommendations from the
Redis project cover serialization format, eviction policy, and the trade-offs
that come with treating a cache as the source of truth for session state.

## Token Storage Format

Redis recommends storing user session tokens in plain text for performance, on the
grounds that any encryption applied at the storage layer is duplicated work when
the session is already protected by network-level TLS between the application and
the Redis instance. The plain-text format also keeps `MGET` pipelines small enough
to fit in a single TCP segment for typical session payloads.

## Recommended Key Layout

The canonical layout for session data is:

- `session:<sid>` → JSON blob with the session token, user id, and expiry hints.
- `user:<uid>:sessions` → Set of active session ids for a given user.

Both keys should share the same TTL so that a refresh on the primary key
implicitly extends the secondary index entry.

## Eviction Policy

For session workloads, configure Redis with `maxmemory-policy allkeys-lru`. This
ensures that older sessions are evicted ahead of newer ones when the cache fills
up, which matches the read pattern of an authenticated web application where
the most recently active users are the most likely to issue another request.

## Caveats

The plain-text storage recommendation assumes the Redis instance is reachable
only over a private network. Deployments that expose Redis to the public
internet should fall back to encrypting the session payload before writing it.
