"""Lightweight deterministic Thai frustration/anger detector for human handoff."""

import re
from dataclasses import dataclass

# Single-match high-severity anger, escalation, or dispute phrases (Thai + English).
HIGH_SEVERITY_PHRASES: tuple[str, ...] = (
    "โกง",
    "หลอกลวง",
    "หลอกขาย",
    "มิจฉาชีพ",
    "แจ้งความ",
    "ร้องเรียน",
    "สคบ",
    "ประจาน",
    "ห่วยแตก",
    "แย่มาก",
    "บริการแย่มาก",
    "โมโหมาก",
    "โกรธมาก",
    "ไม่พอใจมาก",
    "เสียความรู้สึกมาก",
    "คืนเงินเดี๋ยวนี้",
    "ไม่รับผิดชอบ",
    "ไร้ความรับผิดชอบ",
    "เอาเปรียบ",
    "โกหก",
    "scam",
    "fraud",
    "worst service",
)

# Medium-severity frustration cues; two cues (or one cue + emphatic punctuation) trigger handoff.
MEDIUM_SEVERITY_PHRASES: tuple[str, ...] = (
    "ห่วย",
    "บริการแย่",
    "แย่จัง",
    "แย่เลย",
    "ไม่พอใจ",
    "โมโห",
    "โกรธ",
    "เสียความรู้สึก",
    "รอนานมาก",
    "ตอบช้ามาก",
    "เสียเวลามาก",
    "ผิดหวังมาก",
    "เลิกซื้อ",
    "เข็ดแล้ว",
    "ของพัง",
)

_EMPHATIC_PUNCT_RE = re.compile(r"([!?])\1{2,}")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class FrustrationResult:
    """Outcome of evaluating whether a customer message shows strong frustration."""

    is_frustrated: bool
    matched_phrase: str | None = None
    score: int = 0


def _normalize_text(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", text.strip()).lower()


def detect_strong_frustration(text: str) -> FrustrationResult:
    """Detect strong customer frustration without invoking an external LLM call.

    High-severity phrases (disputes, scams, legal threats, strong anger) trigger immediately.
    Medium-severity phrases require at least two cues (or one cue plus emphatic punctuation
    like '!!!') to avoid false positives on routine polite support questions.
    """
    normalized = _normalize_text(text)
    if not normalized:
        return FrustrationResult(is_frustrated=False, score=0)

    for phrase in HIGH_SEVERITY_PHRASES:
        if phrase in normalized:
            return FrustrationResult(is_frustrated=True, matched_phrase=phrase, score=2)

    matched_medium: list[str] = [
        phrase for phrase in MEDIUM_SEVERITY_PHRASES if phrase in normalized
    ]
    score = len(matched_medium)
    if matched_medium and _EMPHATIC_PUNCT_RE.search(normalized):
        score += 1

    if score >= 2 and matched_medium:
        return FrustrationResult(
            is_frustrated=True,
            matched_phrase=matched_medium[0],
            score=score,
        )

    return FrustrationResult(
        is_frustrated=False,
        matched_phrase=matched_medium[0] if matched_medium else None,
        score=score,
    )
