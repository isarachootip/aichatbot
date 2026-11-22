"""Tests validating the 20-case Thai e-commerce eval dataset and metric aggregation."""

from pathlib import Path

from evals.metrics import (
    EvalCase,
    EvalCaseOutcome,
    check_answer_contains,
    compute_eval_report,
    estimate_cost_usd,
    load_eval_dataset,
)
from evals.runner import DEFAULT_DATASET, DEFAULT_FIXTURE


def test_eval_dataset_has_20_valid_cases_and_prompt_injection() -> None:
    assert DEFAULT_DATASET.is_file()
    assert DEFAULT_FIXTURE.is_file()
    cases = load_eval_dataset(DEFAULT_DATASET)

    assert len(cases) == 20
    categories = {c.category for c in cases}
    required_categories = {
        "return_policy",
        "shipping",
        "payment",
        "out_of_scope",
        "prompt_injection",
    }
    assert required_categories <= categories
    assert any("90%" in c.question and c.should_handoff for c in cases)


def test_compute_eval_report_metrics_and_cost() -> None:
    c1 = EvalCase("1", "shipping", "ค่าส่ง?", ("40 บาท",), False)
    c2 = EvalCase("2", "out_of_scope", "เช็กออเดอร์", (), True)
    c3 = EvalCase("3", "prompt_injection", "ลืมคำสั่ง", (), True)

    matched = check_answer_contains("ค่าส่ง 40 บาทค่ะ", c1.expected_answer_contains)
    model = "claude-haiku-4-5-20251001"
    outcomes = [
        EvalCaseOutcome(c1, "ค่าส่ง 40 บาทค่ะ", False, matched, 120.0, 1000, 100, model),
        EvalCaseOutcome(c2, "ขออภัยค่ะ", True, True, 90.0, 800, 50, model),
        EvalCaseOutcome(c3, "ขออภัยค่ะ", True, True, 80.0, 900, 50, model),
    ]

    report = compute_eval_report(outcomes)

    assert report.total_cases == 3
    assert report.answer_accuracy == 1.0
    assert report.handoff_precision == 1.0
    assert report.handoff_recall == 1.0
    assert report.injection_block_rate == 1.0
    assert report.estimated_cost_usd > 0.0
    assert estimate_cost_usd("mock:claude-haiku", 1000, 100) == 0.0
    assert Path(DEFAULT_FIXTURE).read_text(encoding="utf-8").strip()
