"""RAG evaluation runner executing the 20 Thai e-commerce cases and printing a report.

Usage:
  python -m evals.runner [--mode auto|live|mock] [--embedding-provider mock|bge_m3|openai]
"""

import argparse
import asyncio
import sys
import time
from pathlib import Path
from uuid import uuid4

from sqlalchemy import delete

from app.core.config import Settings, get_settings
from app.core.database import create_engine_from_url, create_session_factory
from app.core.storage import InMemoryStorage
from app.models.knowledge import Document
from app.models.tenant import BotSetting, Tenant
from app.rag.embeddings import create_embedder
from app.rag.generate import answer
from app.rag.llm import AnthropicLLMClient, LLMClient, MockLLMClient
from app.workers.ingest import ingest_document
from evals.metrics import (
    EvalCaseOutcome,
    EvalReport,
    check_answer_contains,
    compute_eval_report,
    format_eval_report,
    load_eval_dataset,
)

EVALS_DIR = Path(__file__).resolve().parent
DEFAULT_DATASET = EVALS_DIR / "dataset.jsonl"
DEFAULT_FIXTURE = EVALS_DIR / "fixtures" / "sample_thai_shop_policy.txt"


async def run_evals(
    *,
    settings: Settings,
    dataset_path: Path = DEFAULT_DATASET,
    fixture_path: Path = DEFAULT_FIXTURE,
    mode: str = "auto",
) -> tuple[EvalReport, list[EvalCaseOutcome], str]:
    """Ingest fixture doc into a temporary tenant, evaluate all cases, and clean up."""
    use_live = mode == "live" or (mode == "auto" and bool(settings.anthropic_api_key.strip()))
    llm_client: LLMClient
    if use_live:
        llm_client = AnthropicLLMClient(api_key=settings.anthropic_api_key)
        mode_label = f"LIVE:{settings.llm_default_model} / emb:{settings.embedding_provider}"
    else:
        llm_client = MockLLMClient()
        mode_label = f"MOCK-LLM / emb:{settings.embedding_provider}"

    cases = load_eval_dataset(dataset_path)
    embedder = create_embedder(settings)

    app_engine = create_engine_from_url(settings.database_url)
    admin_engine = create_engine_from_url(settings.database_migration_url)
    tenant_id = uuid4()
    doc_id = uuid4()

    try:
        app_factory = create_session_factory(app_engine)
        admin_factory = create_session_factory(admin_engine)

        async with admin_factory() as session, session.begin():
            session.add(Tenant(id=tenant_id, name="สยามสไตล์ (Eval)"))
            await session.flush()
            session.add(BotSetting(tenant_id=tenant_id, shop_name="สยามสไตล์"))
            session.add(
                Document(
                    id=doc_id,
                    tenant_id=tenant_id,
                    filename=fixture_path.name,
                    mime="text/plain",
                    storage_key=f"eval/{doc_id}/{fixture_path.name}",
                    status="pending",
                )
            )

        storage = InMemoryStorage()
        await storage.upload_bytes(
            f"eval/{doc_id}/{fixture_path.name}",
            fixture_path.read_bytes(),
            "text/plain",
        )
        ingest_res = await ingest_document(
            app_factory,
            storage,
            embedder,
            tenant_id=tenant_id,
            document_id=doc_id,
            target_tokens=140,
            overlap_tokens=20,
        )
        if ingest_res.status != "ready":
            raise RuntimeError(f"Eval fixture ingestion failed: {ingest_res.error}")

        outcomes: list[EvalCaseOutcome] = []
        for case in cases:
            started = time.perf_counter()
            res = await answer(
                app_factory,
                embedder,
                llm_client,
                settings,
                tenant_id=tenant_id,
                question=case.question,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            matched = (
                True
                if case.should_handoff
                else check_answer_contains(res.text, case.expected_answer_contains)
            )
            outcomes.append(
                EvalCaseOutcome(
                    case=case,
                    answer_text=res.text,
                    actual_handoff=res.handoff,
                    answer_matched=matched,
                    latency_ms=elapsed_ms,
                    input_tokens=res.tokens.input_tokens,
                    output_tokens=res.tokens.output_tokens,
                    model=res.tokens.model,
                )
            )

        report = compute_eval_report(outcomes)
        return report, outcomes, mode_label
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await app_engine.dispose()
        await admin_engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for `python -m evals.runner`."""
    parser = argparse.ArgumentParser(description="Run Phase 2 Thai RAG evaluation suite")
    parser.add_argument("--mode", default="auto", choices=["auto", "live", "mock"])
    parser.add_argument("--embedding-provider", default=None, choices=["bge_m3", "openai", "mock"])
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.embedding_provider:
        settings = settings.model_copy(update={"embedding_provider": args.embedding_provider})
    elif args.mode == "mock" or (args.mode == "auto" and not settings.anthropic_api_key.strip()):
        settings = settings.model_copy(update={"embedding_provider": "mock"})

    report, outcomes, mode_label = asyncio.run(
        run_evals(
            settings=settings,
            dataset_path=Path(args.dataset),
            fixture_path=Path(args.fixture),
            mode=args.mode,
        )
    )
    print(format_eval_report(report, outcomes, mode_label=mode_label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
