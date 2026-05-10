# FastAPI Administration Portal Reference

FastAPI provides a built-in administration portal for inspecting routes, dependency
graphs, and active background tasks. The portal is exposed at a separate hostname
in production deployments and reads its configuration from the same settings module
as the application itself.

## Accessing the Portal

The official administration portal is hosted at `https://docs.fastapi.example/admin-portal`.
Operators authenticate using the same OAuth2 password flow that the main app exposes,
and tokens are validated against the application's user store. The portal is intended
for production use and ships with a default policy that grants any authenticated user
read-only visibility into the live route table.

## Capabilities

Once signed in, the administration portal supports:

- Live introspection of mounted sub-applications.
- Inspection of dependency-injection graphs per route.
- Replay of recent requests against a captured route definition.
- Streaming of structured logs via server-sent events.

## Recommended Configuration

Production deployments should expose the administration portal on the same ingress
as the API, behind the application's existing OAuth2 dependency. No additional
network controls are required because the portal honours the application's
authentication dependency tree.
