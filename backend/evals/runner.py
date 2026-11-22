"""RAG evaluation runner executing the 20 Thai e-commerce cases and printing a report.

Usage:
  python -m evals.runner [--mode auto|live|mock] [--embedding-provider gemini|bge_m3|openai|mock]
"""

import argparse
import asyncio
import re
import sys
import time
from pathlib import Path
from uuid import UUID, uuid4

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import Settings, get_settings
from app.core.database import create_engine_from_url, create_session_factory
from app.core.storage import InMemoryStorage
from app.models.knowledge import Document
from app.models.tenant import BotSetting, Tenant
from app.rag.embeddings import Embedder, create_embedder
from app.rag.generate import answer
from app.rag.llm import LLMClient, MockLLMClient, create_llm_client
from app.rag.types import AnswerResult
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
_RETRY_DELAY_RE = re.compile(r"retry in (\d+(?:\.\d+)?)s", re.IGNORECASE)


def _has_live_llm_key(settings: Settings) -> bool:
    if settings.llm_provider == "gemini":
        return bool(settings.gemini_api_key.strip())
    return bool(settings.anthropic_api_key.strip())


async def _answer_with_retry(
    *,
    app_factory: async_sessionmaker[AsyncSession],
    embedder: Embedder,
    llm_client: LLMClient,
    settings: Settings,
    tenant_id: UUID,
    question: str,
    max_attempts: int = 4,
) -> AnswerResult:
    for attempt in range(1, max_attempts + 1):
        try:
            return await answer(
                app_factory,
                embedder,
                llm_client,
                settings,
                tenant_id=tenant_id,
                question=question,
            )
        except Exception as exc:
            err_text = str(exc)
            retryable = any(code in err_text for code in ("429", "503", "RESOURCE_EXHAUSTED"))
            if not retryable or attempt == max_attempts:
                raise
            match = _RETRY_DELAY_RE.search(err_text)
            wait_sec = float(match.group(1)) + 1.0 if match else float(attempt * 5)
            await asyncio.sleep(min(wait_sec, 65.0))
    raise RuntimeError("Unreachable retry loop")


async def run_evals(
    *,
    settings: Settings,
    dataset_path: Path = DEFAULT_DATASET,
    fixture_path: Path = DEFAULT_FIXTURE,
    mode: str = "auto",
    delay_seconds: float = 0.0,
) -> tuple[EvalReport, list[EvalCaseOutcome], str]:
    """Ingest fixture doc into a temporary tenant, evaluate all cases, and clean up."""
    use_live = mode == "live" or (mode == "auto" and _has_live_llm_key(settings))
    llm_client: LLMClient = create_llm_client(settings) if use_live else MockLLMClient()
    mode_label = (
        f"LIVE:{settings.llm_provider}/{settings.llm_default_model} "
        f"/ emb:{settings.embedding_provider}"
        if use_live
        else f"MOCK-LLM / emb:{settings.embedding_provider}"
    )

    cases = load_eval_dataset(dataset_path)
    embedder = create_embedder(settings)
    app_engine = create_engine_from_url(settings.database_url)
    admin_engine = create_engine_from_url(settings.database_migration_url)
    tenant_id, doc_id = uuid4(), uuid4()

    try:
        app_factory = create_session_factory(app_engine)
        admin_factory = create_session_factory(admin_engine)
        async with admin_factory() as session, session.begin():
            session.add(Tenant(id=tenant_id, name="สยามสไตล์ (Eval)"))
            await session.flush()
            session.add(BotSetting(tenant_id=tenant_id, shop_name="สยามสไตล์"))
            key = f"eval/{doc_id}/{fixture_path.name}"
            session.add(
                Document(
                    id=doc_id,
                    tenant_id=tenant_id,
                    filename=fixture_path.name,
                    mime="text/plain",
                    storage_key=key,
                    status="pending",
                )
            )

        storage = InMemoryStorage()
        await storage.upload_bytes(key, fixture_path.read_bytes(), "text/plain")
        ingest_res = await ingest_document(
            app_factory, storage, embedder,
            tenant_id=tenant_id, document_id=doc_id, target_tokens=140, overlap_tokens=20,
        )
        if ingest_res.status != "ready":
            raise RuntimeError(f"Eval fixture ingestion failed: {ingest_res.error}")

        outcomes: list[EvalCaseOutcome] = []
        for idx, case in enumerate(cases):
            if use_live and delay_seconds > 0 and idx > 0:
                await asyncio.sleep(delay_seconds)
            started = time.perf_counter()
            res = await _answer_with_retry(
                app_factory=app_factory, embedder=embedder, llm_client=llm_client,
                settings=settings, tenant_id=tenant_id, question=case.question,
            )
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            matched = case.should_handoff or check_answer_contains(
                res.text, case.expected_answer_contains
            )
            outcomes.append(
                EvalCaseOutcome(
                    case=case, answer_text=res.text, actual_handoff=res.handoff,
                    answer_matched=matched, latency_ms=elapsed_ms,
                    input_tokens=res.tokens.input_tokens, output_tokens=res.tokens.output_tokens,
                    model=res.tokens.model,
                )
            )

        return compute_eval_report(outcomes), outcomes, mode_label
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(delete(Tenant).where(Tenant.id == tenant_id))
        await app_engine.dispose()
        await admin_engine.dispose()


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint for `python -m evals.runner`."""
    parser = argparse.ArgumentParser(description="Run Phase 2 Thai RAG evaluation suite")
    parser.add_argument("--mode", default="auto", choices=["auto", "live", "mock"])
    parser.add_argument(
        "--embedding-provider", default=None, choices=["gemini", "bge_m3", "openai", "mock"]
    )
    parser.add_argument("--llm-provider", default=None, choices=["gemini", "anthropic"])
    parser.add_argument("--delay", type=float, default=1.0, help="Seconds between live calls")
    parser.add_argument("--dataset", default=str(DEFAULT_DATASET))
    parser.add_argument("--fixture", default=str(DEFAULT_FIXTURE))
    args = parser.parse_args(argv)

    settings = get_settings()
    if args.llm_provider:
        settings = settings.model_copy(update={"llm_provider": args.llm_provider})
    if args.embedding_provider:
        settings = settings.model_copy(update={"embedding_provider": args.embedding_provider})
    elif args.mode == "mock" or (args.mode == "auto" and not _has_live_llm_key(settings)):
        settings = settings.model_copy(update={"embedding_provider": "mock"})

    report, outcomes, mode_label = asyncio.run(
        run_evals(
            settings=settings,
            dataset_path=Path(args.dataset),
            fixture_path=Path(args.fixture),
            mode=args.mode,
            delay_seconds=args.delay,
        )
    )
    print(format_eval_report(report, outcomes, mode_label=mode_label))
    return 0


if __name__ == "__main__":
    sys.exit(main())
