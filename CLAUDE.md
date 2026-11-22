# Project: Thai AI Chat Agent SaaS

## Product
A multi-tenant SaaS that lets Thai online shops auto-reply to customer chats
(LINE OA first, then Facebook Messenger / Instagram / web widget) using an AI agent
grounded ONLY in each shop's own knowledge base (PDF, DOCX, XLSX/CSV, TXT uploads).
Answers track source citations (`document_id`, `filename`, `page`). Unknown answers are
handed off to a human admin. Shops self-serve sign-up with a 7-day free trial (no credit
card), then pay monthly via Omise (credit card auto-renew / PromptPay manual monthly QR).

## Tech stack (do not change without asking)
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x (async), Alembic, Pydantic v2
- DB: PostgreSQL 16 + pgvector (Supabase-compatible), Row Level Security by `tenant_id`
- Queue: Redis + ARQ for background jobs (document ingestion, outbound replies, crons)
- Embeddings: pluggable interface locked to `vector(1024)`; default `BAAI/bge-m3`
  (1024 dims) via sentence-transformers, alternative OpenAI `text-embedding-3-small`
  (`dimensions=1024`), plus deterministic mock for unit tests. Selected via config.
- LLM: Anthropic Claude API (`anthropic` Python SDK). `LLM_DEFAULT_MODEL` and
  `LLM_ESCALATION_MODEL` come from config; escalation hook is opt-in via config.
- Thai NLP: PyThaiNLP for sentence/word segmentation (chunking + keyword search)
- Parsing: PyMuPDF (text-based PDF, no OCR in MVP), python-docx (DOCX), pandas (XLSX/CSV)
- File storage: S3-compatible (MinIO locally)
- Dashboard: Next.js 15 (App Router) + TypeScript + Tailwind + shadcn/ui (Phase 5)
- Auth: Supabase Auth JWKS JWT verified in FastAPI (+ local Dev JWT in dev/test only)
- Payments: Omise (Card recurring + 3-day grace period; PromptPay manual QR + 3-day reminder)
- Local dev: docker-compose (`postgres`+pgvector, `redis`, `minio`, `backend`, `worker`)
- Tests: pytest + pytest-asyncio + httpx; Playwright for dashboard smoke tests

## Repository layout
```text
/backend
  /alembic        # Async migrations (run via DATABASE_MIGRATION_URL)
  /app
    /api          # FastAPI routers (health, auth, documents, chat, webhooks, billing, admin)
    /core         # config, logging, database, tenant_context, security
    /models       # Split by domain: base, tenant, knowledge, messaging, operations
    /schemas      # Pydantic v2 request/response schemas
    /rag          # parsing, chunking, embeddings, retrieval, generation, prompts
    /channels     # base.py, line.py, facebook.py, web.py (ChannelAdapter interface)
    /services     # handoff, usage/quota, billing, notifications
    /workers      # ARQ tasks and WorkerSettings
  /tests
  /evals          # RAG evaluation set + runner
/dashboard        # Next.js 15 app (added in Phase 5)
/infra/postgres   # Local PostgreSQL role bootstrap (app_user non-superuser)
docker-compose.yml
.env.example
```

## Data model (all 13 tables have tenant isolation + FORCE RLS)
- `tenants(id, name, plan, trial_ends_at, status, pdpa_retention_days, auto_return_hours, created_at)`
- `users(id, tenant_id, email, role['owner','admin','agent'], is_super_admin, created_at)`
- `documents(id, tenant_id, filename, mime, storage_key, status['pending','processing','ready','failed'], error, uploaded_at)`
- `chunks(id, tenant_id, document_id, content, page, chunk_index, tokens, embedding vector(1024), tsv tsvector)`
- `channels(id, tenant_id, type['line','facebook','instagram','web'], name, credentials_encrypted, webhook_secret, active, created_at)`
- `conversations(id, tenant_id, channel_id, external_user_id, customer_name, mode['bot','human'], last_message_at, last_agent_reply_at)`
- `messages(id, tenant_id, conversation_id, role['customer','bot','agent'], content, sources jsonb, model, input_tokens, output_tokens, created_at)`
- `bot_settings(tenant_id PK, shop_name, tone, greeting, handoff_keywords text[], extra_instructions, fallback_message, show_citations_to_customer)`
- `subscriptions(tenant_id PK, plan, status, omise_customer_id, current_period_end)`
- `usage_monthly(tenant_id, month, message_count, input_tokens, output_tokens) PK(tenant_id, month)`
- `unanswered_questions(id, tenant_id, conversation_id, question, created_at)`
- `webhook_events(id, tenant_id, channel_id, external_event_id, received_at)`
- `notifications(id, tenant_id, type, title, body, metadata jsonb, read_at, created_at)`

## RAG & channel rules
- Chunking: Thai-aware via PyThaiNLP sentence segmentation; ~500 tokens, ~50 overlap;
  never split mid-word; keep page number; keep table rows together for XLSX/CSV.
- Retrieval: hybrid = pgvector cosine (top 20) + keyword search on PyThaiNLP-tokenized
  `tsvector` (top 20), merged with Reciprocal Rank Fusion, return top 6. ALWAYS filter by `tenant_id`.
- Generation: system prompt in Thai; answer ONLY from `<context>`; if not answerable,
  reply with tenant's `fallback_message` and emit a structured handoff flag (tool call / JSON,
  never a magic string). Never invent prices, discounts, promises, or policies. Short,
  chat-friendly, polite Thai (ค่ะ/ครับ per tenant setting). Include last 10 messages of history.
- Prompt-injection defense: wrap customer text and document chunks in clearly delimited tags
  and treat both as untrusted data.
- Citations: store `[{document_id, filename, page}]` in `messages.sources` (retained as audit
  snapshot even if document is deleted); show to customer only when `show_citations_to_customer=true`.
- LINE UX: debounce rapid customer bursts (2.5s window in Redis per conversation); fallback
  from expired `replyToken` to Push API; images/slips trigger polite reply + immediate human
  handoff; stickers receive polite fallback without handoff.
- Trial expired / Quota 100%: bot stays silent, switches conversation to `human` mode, and
  notifies the shop owner.

## RBAC & security rules
- Tenant isolation is the #1 security requirement:
  - Every query filters `tenant_id` AND PostgreSQL enforces `FORCE ROW LEVEL SECURITY` via
    non-superuser `app_user` (`NOBYPASSRLS`) keyed on transaction-local `app.tenant_id`.
  - Webhook endpoints resolve `tenant_id` from `channel_id` via `SECURITY DEFINER` function
    `resolve_channel_tenant(uuid)` before setting `app.tenant_id`.
- RBAC roles:
  - `agent`: `/inbox` read/reply and bot/human toggle only.
  - `admin`: `agent` + documents, channels, bot settings, playground, analytics.
  - `owner`: full tenant control including billing, team management, and PDPA delete/export.
- Secrets only from env; channel credentials encrypted at rest (Fernet key from env).
- Verify every webhook signature (LINE `X-Line-Signature`, Meta `X-Hub-Signature-256`, Omise).
- Webhooks respond 200 fast; heavy work goes to ARQ; dedupe events via `webhook_events`.
- Enforce quota + trial/subscription status before calling the LLM; log tokens in `usage_monthly`.

## Engineering rules
- Modularity: keep source files concise (< 200 lines), single-responsibility, cleanly layered.
- Strict typing everywhere: `ruff` + `mypy --strict` clean; zero `Any` unless justified at boundary.
- Write tests proving every feature and cross-tenant isolation before finishing a phase.
- Keep `README.md` updated with setup and run instructions.
- When unsure about a product decision, stop and ask instead of guessing.
