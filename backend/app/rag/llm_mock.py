"""Offline extractive LLM client for unit tests and API-key-free eval dry runs."""

import re
from collections.abc import Sequence

from app.rag.thai_nlp import build_search_tsquery, tokenize_words
from app.rag.types import StructuredLLMResponse

_INJECTION_PATTERNS = re.compile(
    r"(ลืมคำสั่ง|ignore\s+previous|system\s+prompt|ส่วนลด\s*90%|ให้ฟรี|แฮก|เปลี่ยนบทบาท|คำสั่งระบบ)",
    re.IGNORECASE,
)
_HANDOFF_PATTERNS = re.compile(
    r"(แอดมิน|คุยกับคน|ติดต่อเจ้าหน้าที่|เลขพัสดุของฉัน|เช็กออเดอร์|สั่งซื้อจำนวนมาก|คู่แข่ง|ราคาส่ง\s*500)",
    re.IGNORECASE,
)
_DOC_BLOCK_RE = re.compile(r'<document index="(\d+)"[^>]*>\n(.*?)\n</document>', re.DOTALL)
_CUSTOMER_MSG_RE = re.compile(r"<customer_message>\n(.*?)\n</customer_message>", re.DOTALL)


def _select_best_extractive_reply(
    question: str,
    docs: list[tuple[str, str]],
) -> tuple[str, int]:
    """Pick the most relevant chunk and sentences matching the customer's Thai question."""
    tsq = build_search_tsquery(question)
    q_tokens = {tok.strip() for tok in tsq.split("|") if tok.strip()}
    if not q_tokens:
        q_tokens = {tok.lower() for tok in tokenize_words(question) if len(tok) > 1}
    scored_segments: list[tuple[float, int, str]] = []

    for idx_str, body in docs:
        doc_idx = int(idx_str)
        segments = [seg.strip() for seg in re.split(r"(?:\n+|\s+-\s+)", body) if seg.strip()]
        for seg in segments:
            seg_tokens = {tok.lower() for tok in tokenize_words(seg) if len(tok) > 1}
            overlap = len(q_tokens & seg_tokens)
            # Prefer denser matches over long unrelated sentences containing generic words
            score = overlap + (overlap / max(len(seg_tokens), 1)) + (0.05 / doc_idx)
            scored_segments.append((score, doc_idx, seg))

    if not scored_segments:
        return docs[0][1].strip()[:350], int(docs[0][0])

    scored_segments.sort(key=lambda item: item[0], reverse=True)
    top_idx = scored_segments[0][1]
    selected: list[str] = []
    for _, _, seg in scored_segments:
        if seg not in selected:
            selected.append(seg)
        if len(selected) == 2:
            break
    return " ".join(selected)[:450], top_idx


class MockLLMClient:
    """Offline extractive LLM client for unit tests and API-key-free eval dry runs."""

    async def generate_grounded_reply(
        self,
        *,
        system_prompt: str,
        messages: Sequence[dict[str, str]],
        model: str,
        max_tokens: int = 600,
    ) -> StructuredLLMResponse:
        del system_prompt, max_tokens
        last_content = messages[-1]["content"] if messages else ""
        q_match = _CUSTOMER_MSG_RE.search(last_content)
        question = q_match.group(1).strip() if q_match else last_content

        if _INJECTION_PATTERNS.search(question):
            return StructuredLLMResponse(
                answer_text="",
                handoff=True,
                handoff_reason="prompt_injection_detected",
                cited_chunk_indices=[],
                input_tokens=len(last_content) // 3,
                output_tokens=20,
                model=f"mock:{model}",
            )
        if _HANDOFF_PATTERNS.search(question):
            return StructuredLLMResponse(
                answer_text="",
                handoff=True,
                handoff_reason="out_of_scope_or_human_requested",
                cited_chunk_indices=[],
                input_tokens=len(last_content) // 3,
                output_tokens=20,
                model=f"mock:{model}",
            )

        docs = _DOC_BLOCK_RE.findall(last_content)
        if not docs:
            return StructuredLLMResponse(
                answer_text="",
                handoff=True,
                handoff_reason="no_context",
                cited_chunk_indices=[],
                input_tokens=len(last_content) // 3,
                output_tokens=20,
                model=f"mock:{model}",
            )

        excerpt, best_idx = _select_best_extractive_reply(question, docs)
        return StructuredLLMResponse(
            answer_text=f"ข้อมูลจากทางร้านค่ะ: {excerpt}",
            handoff=False,
            handoff_reason=None,
            cited_chunk_indices=[best_idx],
            input_tokens=len(last_content) // 3,
            output_tokens=len(excerpt) // 3,
            model=f"mock:{model}",
        )
