# Thai AI Chat Agent SaaS

Multi-tenant AI Chat Agent SaaS for Thai online shops (LINE OA first) grounded strictly in each shop's uploaded knowledge base, with PostgreSQL Row Level Security (RLS), hybrid vector + keyword retrieval, human handoff, and Omise billing.

## Architecture (Phase 1)

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.x (async), Alembic, Pydantic v2, structlog
- **Database**: PostgreSQL 16 + `pgvector` (`vector(1024)` + HNSW cosine index + GIN `tsvector` index)
- **Tenant Isolation**: Every tenant-owned table enforces `FORCE ROW LEVEL SECURITY` using non-superuser role `app_user` (`NOBYPASSRLS`) keyed on transaction-local `app.tenant_id`
- **Queue**: Redis 7 + ARQ worker
- **Object Storage**: S3-compatible MinIO (local dev)

## Quick Start (Docker Compose)

1. Copy the example environment file:
   ```bash
   cp .env.example .env
   ```
2. Start all services (`postgres`, `redis`, `minio`, `backend`, `worker`):
   ```bash
   docker compose up -d --build
   ```
3. Run database migrations:
   ```bash
   docker compose exec backend alembic upgrade head
   ```
4. Verify API health:
   ```bash
   curl http://localhost:8000/health
   ```
   - PostgreSQL (`pgvector`) is exposed on host port `5439` by default (`POSTGRES_HOST_PORT`).
   - Redis is exposed on host port `6380` by default (`REDIS_HOST_PORT`).
   - MinIO Console is available at `http://localhost:9001`.

## Deployment Notes (Coolify)

- `docker-compose.yml` uses `expose:` (no hardcoded host `ports:`) and bakes PostgreSQL init scripts into `infra/postgres/Dockerfile`, so Coolify deploys with `-f docker-compose.yml` without port collisions (`8000`, `9000`, `5432`, `6379`).
- Point Coolify's Domain for the `backend` service to port `8000`.
- Local development automatically merges `docker-compose.override.yml` to expose localhost ports and mount `./backend:/app` for hot reload.

## Running Tests & Quality Checks

Run static analysis, strict type checking, and the full test suite (including PostgreSQL RLS cross-tenant isolation tests):

```bash
docker compose exec backend ruff check .
docker compose exec backend mypy app tests
docker compose exec backend pytest -v
```
