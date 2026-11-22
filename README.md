# Thai AI Chat Agent SaaS

Multi-tenant AI Chat Agent SaaS for Thai online shops (LINE OA first) grounded strictly in each shop's uploaded knowledge base, with PostgreSQL Row Level Security (RLS), hybrid vector + keyword retrieval, human handoff, and Omise billing.

## Architecture (Phase 1–2)

- **Backend**: Python 3.12, FastAPI, SQLAlchemy 2.x (async), Alembic, Pydantic v2, structlog
- **Database**: PostgreSQL 16 + `pgvector` (`vector(1024)` + HNSW cosine index + GIN `tsvector` index)
- **Tenant Isolation**: Every tenant-owned table enforces `FORCE ROW LEVEL SECURITY` using non-superuser role `app_user` (`NOBYPASSRLS`) keyed on transaction-local `app.tenant_id`
- **RAG Core**:
  - Parsing: PyMuPDF (text PDF), python-docx (DOCX), pandas/openpyxl (XLSX/CSV preserving atomic rows), TXT
  - Thai NLP & Chunking: PyThaiNLP sentence/word segmentation (~500 tokens, ~50 overlap, zero mid-word splits)
  - Embeddings: pluggable 1024-dim interface (Google Gemini `gemini-embedding-001`, `BAAI/bge-m3` via optional `[local-embeddings]`, OpenAI `text-embedding-3-small`, deterministic `mock`)
  - Hybrid Retrieval: pgvector cosine (top 20) + PyThaiNLP `tsvector` keyword search (top 20) merged via Reciprocal Rank Fusion (top 6), tenant-filtered + RLS-enforced
  - Generation: Thai system prompt, untrusted XML delimiting, last 10 messages of history, pluggable Google Gemini (structured JSON schema) & Anthropic Claude (forced tool use `respond_to_customer`) for structured handoff + source citations
- **Queue**: Redis 7 + ARQ worker (`ingest_document_job`)
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
docker compose exec backend mypy app tests evals
docker compose exec backend pytest -v
```

## Phase 2 RAG CLI & Evaluation Suite

Ingest a document and ask grounded Thai questions directly via CLI:

```bash
# 1. Ingest a knowledge base document (uploads to MinIO -> parses -> chunks -> embeds -> indexes)
docker compose exec backend python -m app.cli ingest \
  --tenant 11111111-1111-1111-1111-111111111111 \
  --create-tenant "สยามสไตล์" \
  --file evals/fixtures/sample_thai_shop_policy.txt \
  --embedding-provider mock

# 2. Ask a grounded Thai question (omit --mock-llm when ANTHROPIC_API_KEY is set)
docker compose exec backend python -m app.cli ask \
  --tenant 11111111-1111-1111-1111-111111111111 \
  --embedding-provider mock \
  --mock-llm \
  "ค่าจัดส่งกี่บาท ส่งฟรีครบเท่าไหร่คะ"
```

Run the 20-case Thai e-commerce RAG evaluation suite:

```bash
# Auto mode uses live Claude when ANTHROPIC_API_KEY is set, otherwise runs offline mock mode
docker compose exec backend python -m evals.runner
```

> To enable local `BAAI/bge-m3` embeddings on a machine with PyTorch support, install the optional extra: `pip install -e ".[local-embeddings]"`.
