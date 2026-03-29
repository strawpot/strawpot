# API

This is the **api** component of ExampleApp, a Python web API using FastAPI with PostgreSQL. Authentication via JWT.

## Build Commands

```bash
pip install -e ".[dev]"
pytest --cov=app tests/
uvicorn app.main:app --reload  # Development server
```

## Hard Rules

These rules must always be followed:

- All user input must be validated at the API boundary using Pydantic models. Never pass raw `request.body` to business logic or database queries. Define a Pydantic model for every request and response.
- Never return internal error details (stack traces, SQL errors, file paths) in API responses. Log the full error internally with `logger.exception()`, return a generic error with a correlation ID to the client.
- All API endpoints must have explicit rate limiting. Apply stricter limits to authentication endpoints (login, token refresh). Use sliding window rate limiting, not fixed window.
- Always use parameterized queries or SQLAlchemy ORM methods. Never construct SQL strings by concatenating user input. This includes `ORDER BY` clauses — validate sort field names against an allowlist.
- Database migrations (Alembic) must be backward-compatible. Never drop columns or tables in the same deploy that removes the code using them — use a two-phase migration: (1) stop using the column, deploy, (2) drop the column, deploy.
- Use connection pooling (`asyncpg` pool or SQLAlchemy async engine). Never open a new connection per request. Set `statement_timeout` to 30s to prevent runaway queries from holding connections.
- JWT secrets must come from environment variables, never hardcoded. Tokens must have expiration (`exp` claim). Validate issuer (`iss`) and audience (`aud`) claims. Use RS256 (asymmetric) for production, HS256 only for development.
- Authentication middleware must run before any route handler. No endpoint should be accidentally unprotected — use a dependency injection pattern with `Depends(get_current_user)` and an explicit allowlist for public routes.
- Use Pydantic models for all request/response schemas. Never use `dict` for API contracts — typed models catch errors at the boundary and generate OpenAPI docs automatically.

## Soft Rules

Follow these conventions unless there's a good reason not to:

- Use structured logging (JSON format) with `structlog` or `python-json-logger`. Every log entry must include the request ID for traceability. Add the request ID via middleware, not manually per handler.
- Configuration must come from environment variables validated at startup via a Pydantic `Settings` class. Never use `os.getenv()` deep in business logic — import from the settings module.
- Every API must have a `/health` endpoint that checks database connectivity and returns 200/503. Include a `/ready` endpoint for Kubernetes that also checks downstream dependencies.
- Implement graceful shutdown — finish in-flight requests, close database connections, then exit. FastAPI handles SIGTERM via uvicorn; verify this works in your deployment.
- API responses must include appropriate cache headers. Use `ETag` or `Last-Modified` for GET endpoints that serve cacheable data. Set `Cache-Control: no-store` for authenticated endpoints.
- Use consistent REST conventions: plural nouns for collections (`/users`), HTTP verbs for actions (POST to create, PATCH to update). Return 201 for creation, 204 for deletion, 200 for everything else.
- Use `async def` for all route handlers. Never mix sync and async — a single blocking call in an async handler blocks the entire event loop. Use `run_in_executor` for unavoidable blocking operations.
- Dependency injection via FastAPI's `Depends()` for database sessions, auth, and shared services. Never import globals or singletons directly in route handlers — they're untestable.
- Write integration tests that hit the actual API via `httpx.AsyncClient` and TestClient. Mock external services, not your own code. Every endpoint needs at least: success case, validation error case, auth error case.

## Cross-Component Awareness

- API contract changes must be coordinated with the client (`client/`). Update the OpenAPI schema and notify the frontend team before deploying breaking changes. Use API versioning (`/v1/`, `/v2/`) for breaking changes.
- Shared types and constants live in `shared/`. Import from there — never duplicate type definitions between server and client.

## Architecture Guide

```
app/
├── main.py          # FastAPI app, middleware, lifespan
├── api/             # Route handlers (thin — delegate to services)
│   ├── v1/          # Versioned routes
│   └── deps.py      # Shared dependencies (auth, db session)
├── services/        # Business logic (no HTTP concepts)
├── models/          # SQLAlchemy ORM models
├── schemas/         # Pydantic request/response schemas
├── core/            # Config, security, exceptions
└── tests/           # Mirrors app/ structure
```

Route handlers are thin: validate input, call a service, return a schema. Business logic lives in `services/`. Database access lives in `models/`. Never import `fastapi` in `services/`.

## Project-Specific Rules

<!-- TODO: Add rules specific to your project -->
<!-- Examples: specific PostgreSQL extensions used, custom auth flow details, third-party API integration patterns -->
