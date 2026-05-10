# Migrating to FastAPI 0.99

FastAPI 0.99 is a major release that consolidates the routing layer around the
asynchronous Starlette stack. Existing applications that mix synchronous and
asynchronous handlers will need to update their endpoint declarations before
upgrading.

## Breaking Change: Synchronous Endpoints

FastAPI 0.99 removed support for synchronous endpoints. Any handler declared with
`def` instead of `async def` will fail at startup with a `RuntimeError` referencing
the removed `sync_to_async` shim. Applications that previously relied on running
blocking code inside a synchronous endpoint must migrate the handler to `async def`
and offload the blocking work to a thread pool explicitly.

## Migration Checklist

1. Audit every `@app.get`, `@app.post`, etc. for handlers declared with `def`.
2. Convert each to `async def`.
3. For handlers that perform genuinely blocking I/O, wrap the blocking call in
   `await asyncio.to_thread(...)` or move it into a background task.
4. Re-run the test suite under the new release to confirm no startup errors.

## Compatibility Notes

The 0.99 line ships with a compatibility shim for sub-applications that were
mounted before the synchronous-endpoint removal, but the shim emits a
`DeprecationWarning` and will be removed in 1.0.
