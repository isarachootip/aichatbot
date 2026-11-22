"""Manual testing CLI for Phase 2 RAG ingestion and grounded Q&A.

Usage:
  python -m app.cli ingest --tenant <UUID> --file <path> [--create-tenant "Shop Name"]
  python -m app.cli ask --tenant <UUID> "คำถาม" [--conversation <UUID>] [--mock-llm] [--json]
"""

import argparse
import asyncio
import json
import mimetypes
import sys
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import create_engine_from_url, create_session_factory
from app.core.logging import configure_logging
from app.core.storage import S3ObjectStorage
from app.core.tenant_context import tenant_scoped_session
from app.models.knowledge import Document
from app.models.tenant import BotSetting, Tenant
from app.rag.embeddings import create_embedder
from app.rag.generate import answer
from app.rag.llm import LLMClient, MockLLMClient, create_llm_client
from app.rag.types import AnswerResult
from app.workers.ingest import ingest_document


async def _ensure_tenant(
    admin_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: UUID,
    create_name: str | None,
) -> None:
    async with admin_factory() as session, session.begin():
        found = (
            await session.execute(select(Tenant).where(Tenant.id == tenant_id))
        ).scalar_one_or_none()
        if found is not None:
            return
        if not create_name:
            raise SystemExit(
                f"Tenant {tenant_id} not found. Pass --create-tenant 'Shop Name' to create it."
            )
        session.add(Tenant(id=tenant_id, name=create_name))
        await session.flush()
        session.add(BotSetting(tenant_id=tenant_id, shop_name=create_name))


async def _run_ingest(args: argparse.Namespace, settings: Settings) -> int:
    tenant_id = UUID(args.tenant)
    file_path = Path(args.file).resolve()
    if not file_path.is_file():
        raise SystemExit(f"File not found: {file_path}")

    app_engine = create_engine_from_url(settings.database_url)
    admin_engine = create_engine_from_url(settings.database_migration_url)
    try:
        app_factory = create_session_factory(app_engine)
        await _ensure_tenant(
            create_session_factory(admin_engine),
            tenant_id=tenant_id,
            create_name=args.create_tenant,
        )
        storage = S3ObjectStorage.from_settings(settings)
        await storage.ensure_bucket()

        mime = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"
        doc_id = uuid4()
        storage_key = f"{tenant_id}/{doc_id}/{file_path.name}"
        await storage.upload_bytes(storage_key, file_path.read_bytes(), mime)

        async with tenant_scoped_session(app_factory, tenant_id) as session:
            session.add(
                Document(
                    id=doc_id,
                    tenant_id=tenant_id,
                    filename=file_path.name,
                    mime=mime,
                    storage_key=storage_key,
                    status="pending",
                )
            )

        res = await ingest_document(
            app_factory,
            storage,
            create_embedder(settings),
            tenant_id=tenant_id,
            document_id=doc_id,
        )
        payload = {
            "tenant_id": str(tenant_id),
            "document_id": str(res.document_id),
            "filename": file_path.name,
            "status": res.status,
            "chunk_count": res.chunk_count,
            "error": res.error,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0 if res.status == "ready" else 1
    finally:
        await app_engine.dispose()
        await admin_engine.dispose()


def _print_answer(result: AnswerResult, *, as_json: bool) -> None:
    if as_json:
        payload = {
            "text": result.text,
            "handoff": result.handoff,
            "handoff_reason": result.handoff_reason,
            "sources": [src.to_json_dict() for src in result.sources],
            "tokens": {
                "input_tokens": result.tokens.input_tokens,
                "output_tokens": result.tokens.output_tokens,
                "model": result.tokens.model,
            },
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return
    sources_str = ", ".join(f"{s.filename} p.{s.page}" for s in result.sources) or "-"
    print(f"Answer : {result.text}")
    print(f"Handoff: {result.handoff} ({result.handoff_reason or '-'})")
    print(f"Sources: {sources_str}")
    print(
        f"Tokens : in={result.tokens.input_tokens} "
        f"out={result.tokens.output_tokens} ({result.tokens.model})"
    )


async def _run_ask(args: argparse.Namespace, settings: Settings) -> int:
    llm: LLMClient = MockLLMClient() if args.mock_llm else create_llm_client(settings)
    app_engine = create_engine_from_url(settings.database_url)
    try:
        result = await answer(
            create_session_factory(app_engine),
            create_embedder(settings),
            llm,
            settings,
            tenant_id=UUID(args.tenant),
            conversation_id=UUID(args.conversation) if args.conversation else None,
            question=args.question,
        )
        _print_answer(result, as_json=bool(args.json))
        return 0
    finally:
        await app_engine.dispose()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="RAG manual testing CLI")
    sub = parser.add_subparsers(dest="command", required=True)
    providers = ["gemini", "bge_m3", "openai", "mock"]

    p_in = sub.add_parser("ingest", help="Upload and ingest a document for a tenant")
    p_in.add_argument("--tenant", required=True, help="Tenant UUID")
    p_in.add_argument("--file", required=True, help="Path to PDF/DOCX/XLSX/CSV/TXT file")
    p_in.add_argument("--create-tenant", default=None, help="Create tenant if missing")
    p_in.add_argument("--embedding-provider", default=None, choices=providers)

    p_ask = sub.add_parser("ask", help="Ask a grounded question against a tenant KB")
    p_ask.add_argument("--tenant", required=True, help="Tenant UUID")
    p_ask.add_argument("question", help="Customer question in Thai or English")
    p_ask.add_argument("--conversation", default=None, help="Optional conversation UUID")
    p_ask.add_argument("--embedding-provider", default=None, choices=providers)
    p_ask.add_argument("--llm-provider", default=None, choices=["gemini", "anthropic"])
    p_ask.add_argument("--mock-llm", action="store_true", help="Use offline MockLLMClient")
    p_ask.add_argument("--json", action="store_true", help="Emit JSON output")
    return parser


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    args = _build_parser().parse_args(argv)
    settings = get_settings()
    updates: dict[str, object] = {}
    if getattr(args, "embedding_provider", None):
        updates["embedding_provider"] = args.embedding_provider
    if getattr(args, "llm_provider", None):
        updates["llm_provider"] = args.llm_provider
    if updates:
        settings = settings.model_copy(update=updates)
    configure_logging(settings.log_level)
    if args.command == "ingest":
        return asyncio.run(_run_ingest(args, settings))
    return asyncio.run(_run_ask(args, settings))


if __name__ == "__main__":
    sys.exit(main())
