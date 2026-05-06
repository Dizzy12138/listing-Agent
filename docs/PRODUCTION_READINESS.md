# Production Readiness Checklist

This project is currently an internal MVP with a production-oriented domain structure. Before external commercial deployment, the following items should be treated as release gates.

## Required Gates

- Persistent task state: move background task status from in-memory dictionaries to Redis, PostgreSQL, or another durable store.
- Worker queue: replace ad hoc background threads with a queue-backed worker such as Celery, Dramatiq, or RQ.
- Secret management: keep API keys out of local JSON files in production and load them from a managed secret store.
- Test coverage: require unit tests for schemas, workflow routing, repositories, and non-model service logic.
- CI: run compile checks, tests, and linting on every pull request.
- Artifact storage: store uploaded and generated assets outside git, preferably in object storage with lifecycle rules.
- Observability: emit structured logs and traces for API requests, workflow nodes, model calls, cost, duration, and failures.
- Deployment contract: provide Docker image, health endpoint, environment variables, and migration/init commands.

## Current Boundaries

- Model calls are still runtime dependencies and should be mocked in automated tests.
- `server.py` remains a monolithic FastAPI module and should be split into route modules as the API surface grows.
- SQLite document storage is acceptable for local demos and internal evaluation, but commercial multi-user usage should move to a managed database.
