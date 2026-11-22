"""Evaluation dataset schema, pricing estimator, and metric aggregation."""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

# USD per 1M tokens (input, output) for cost reporting
MODEL_PRICING_USD_PER_M: dict[str, tuple[float, float]] = {
    "claude-haiku-4-5-20251001": (1.00, 5.00),
    "claude-sonnet-4-5-20250929": (3.00, 15.00),
}


@dataclass(frozen=True)
class EvalCase:
    """Single JSONL evaluation test case."""

    id: str
    category: str
    question: str
    expected_answer_contains: tuple[str, ...]
    should_handoff: bool


@dataclass(frozen=True)
class EvalCaseOutcome:
    """Per-case execution record for accuracy, handoff, latency, and cost metrics."""

    case: EvalCase
    answer_text: str
    actual_handoff: bool
    answer_matched: bool
    latency_ms: float
    input_tokens: int
    output_tokens: int
    model: str


@dataclass(frozen=True)
class EvalReport:
    """Aggregated RAG evaluation summary."""

    total_cases: int
    answerable_cases: int
    answer_accuracy: float
    handoff_precision: float
    handoff_recall: float
    handoff_f1: float
    injection_block_rate: float
    avg_latency_ms: float
    p95_latency_ms: float
    total_input_tokens: int
    total_output_tokens: int
    estimated_cost_usd: float


def load_eval_dataset(path: Path) -> list[EvalCase]:
    """Load and validate evaluation cases from a JSONL file."""
    cases: list[EvalCase] = []
    for line_no, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        obj = json.loads(stripped)
        if not isinstance(obj, dict):
            raise ValueError(f"Line {line_no} in {path} must be a JSON object")
        expected = tuple(str(x) for x in obj.get("expected_answer_contains", []))
        cases.append(
            EvalCase(
                id=str(obj.get("id", f"case-{line_no}")),
                category=str(obj.get("category", "general")),
                question=str(obj["question"]),
                expected_answer_contains=expected,
                should_handoff=bool(obj["should_handoff"]),
            )
        )
    return cases


def check_answer_contains(answer_text: str, expected_substrings: Sequence[str]) -> bool:
    """Return True if all required substrings appear in `answer_text` (case-insensitive)."""
    lowered = answer_text.lower()
    return all(token.lower() in lowered for token in expected_substrings)


def estimate_cost_usd(model: str, input_tokens: int, output_tokens: int) -> float:
    """Estimate USD cost for a single call; mock models cost $0."""
    if model.startswith("mock:"):
        return 0.0
    in_price, out_price = MODEL_PRICING_USD_PER_M.get(model, (1.00, 5.00))
    return (input_tokens * in_price + output_tokens * out_price) / 1_000_000.0


def compute_eval_report(outcomes: Sequence[EvalCaseOutcome]) -> EvalReport:
    """Aggregate accuracy, handoff precision/recall/F1, latency, and cost."""
    total = len(outcomes)
    if total == 0:
        raise ValueError("Cannot compute eval report on empty outcomes")

    answerable = [o for o in outcomes if not o.case.should_handoff]
    answer_hits = sum(1 for o in answerable if (not o.actual_handoff and o.answer_matched))
    accuracy = answer_hits / len(answerable) if answerable else 1.0

    tp = sum(1 for o in outcomes if o.case.should_handoff and o.actual_handoff)
    fp = sum(1 for o in outcomes if (not o.case.should_handoff) and o.actual_handoff)
    fn = sum(1 for o in outcomes if o.case.should_handoff and (not o.actual_handoff))

    precision = tp / (tp + fp) if (tp + fp) > 0 else 1.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 1.0
    f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) > 0 else 0.0

    injections = [o for o in outcomes if o.case.category == "prompt_injection"]
    inj_blocked = sum(1 for o in injections if o.actual_handoff)
    injection_rate = inj_blocked / len(injections) if injections else 1.0

    latencies = sorted(o.latency_ms for o in outcomes)
    avg_lat = sum(latencies) / total
    p95_idx = min(total - 1, round(0.95 * (total - 1)))
    p95_lat = latencies[p95_idx]

    total_in = sum(o.input_tokens for o in outcomes)
    total_out = sum(o.output_tokens for o in outcomes)
    total_cost = sum(estimate_cost_usd(o.model, o.input_tokens, o.output_tokens) for o in outcomes)

    return EvalReport(
        total_cases=total,
        answerable_cases=len(answerable),
        answer_accuracy=accuracy,
        handoff_precision=precision,
        handoff_recall=recall,
        handoff_f1=f1,
        injection_block_rate=injection_rate,
        avg_latency_ms=avg_lat,
        p95_latency_ms=p95_lat,
        total_input_tokens=total_in,
        total_output_tokens=total_out,
        estimated_cost_usd=total_cost,
    )


def format_eval_report(
    report: EvalReport,
    outcomes: Sequence[EvalCaseOutcome],
    *,
    mode_label: str,
) -> str:
    """Format an EvalReport and per-case results as a console table."""
    lines = [
        "=" * 74,
        f"Thai AI Chat Agent — Phase 2 RAG Evaluation Report ({mode_label})",
        "=" * 74,
        f"Total cases            : {report.total_cases} ({report.answerable_cases} answerable)",
        f"Answer accuracy        : {report.answer_accuracy * 100:6.2f}%",
        f"Handoff precision      : {report.handoff_precision * 100:6.2f}%",
        f"Handoff recall         : {report.handoff_recall * 100:6.2f}%",
        f"Handoff F1             : {report.handoff_f1 * 100:6.2f}%",
        f"Prompt-injection block : {report.injection_block_rate * 100:6.2f}%",
        f"Avg latency            : {report.avg_latency_ms:7.1f} ms "
        f"(p95: {report.p95_latency_ms:.1f} ms)",
        f"Total tokens           : in={report.total_input_tokens:,} "
        f"out={report.total_output_tokens:,}",
        f"Estimated LLM cost     : ${report.estimated_cost_usd:.6f}",
        "-" * 74,
        "ID       | Category          | ExpHO | ActHO | Match | Latency  | Status",
        "-" * 74,
    ]
    for item in outcomes:
        passed = item.actual_handoff == item.case.should_handoff and (
            item.case.should_handoff or item.answer_matched
        )
        status = "PASS" if passed else "FAIL"
        lines.append(
            f"{item.case.id:<8} | {item.case.category:<17} | "
            f"{item.case.should_handoff!s:<5} | {item.actual_handoff!s:<5} | "
            f"{item.answer_matched!s:<5} | {item.latency_ms:6.1f}ms | {status}"
        )
    lines.append("=" * 74)
    return "\n".join(lines)
