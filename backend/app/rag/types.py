"""Shared strongly-typed domain structures for the RAG pipeline."""

from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.models.tenant import BotSetting

DEFAULT_TONE = "สุภาพ เป็นกันเอง (ค่ะ)"
DEFAULT_GREETING = "สวัสดีค่ะ มีอะไรให้ช่วยดูแลสอบถามได้เลยนะคะ"
DEFAULT_FALLBACK = "ขออภัยค่ะ ข้อมูลส่วนนี้ขออนุญาตให้แอดมินตรวจสอบและติดต่อกลับนะคะ"
DEFAULT_HANDOFF_KEYWORDS: tuple[str, ...] = ("แอดมิน", "คุยกับคน", "ติดต่อเจ้าหน้าที่")


@dataclass(frozen=True)
class SourceCitation:
    """Audit-grade citation snapshot stored in messages.sources."""

    document_id: UUID
    filename: str
    page: int

    def to_json_dict(self) -> dict[str, object]:
        """Serialize to JSONB-compatible dictionary for messages.sources."""
        return {
            "document_id": str(self.document_id),
            "filename": self.filename,
            "page": self.page,
        }


@dataclass(frozen=True)
class RetrievedChunk:
    """Single hybrid-retrieved knowledge chunk ranked by RRF."""

    chunk_id: UUID
    document_id: UUID
    filename: str
    page: int
    chunk_index: int
    content: str
    rrf_score: float
    vector_rank: int | None = None
    keyword_rank: int | None = None


@dataclass(frozen=True)
class ConversationTurn:
    """Historical conversation message loaded from messages table."""

    role: Literal["customer", "bot", "agent"]
    content: str


@dataclass(frozen=True)
class TokenUsage:
    """LLM token consumption for a single RAG answer."""

    input_tokens: int
    output_tokens: int
    model: str


@dataclass(frozen=True)
class BotPromptConfig:
    """Normalized tenant bot settings consumed by prompt and answer builders."""

    shop_name: str
    tone: str = DEFAULT_TONE
    greeting: str = DEFAULT_GREETING
    handoff_keywords: tuple[str, ...] = DEFAULT_HANDOFF_KEYWORDS
    extra_instructions: str = ""
    fallback_message: str = DEFAULT_FALLBACK
    show_citations_to_customer: bool = False

    @classmethod
    def from_orm(
        cls,
        setting: BotSetting | None,
        *,
        fallback_shop_name: str = "ร้านค้า",
    ) -> "BotPromptConfig":
        """Build prompt config from a BotSetting ORM row or safe shop defaults."""
        if setting is None:
            return cls(shop_name=fallback_shop_name)
        return cls(
            shop_name=setting.shop_name,
            tone=setting.tone,
            greeting=setting.greeting,
            handoff_keywords=tuple(setting.handoff_keywords),
            extra_instructions=setting.extra_instructions,
            fallback_message=setting.fallback_message,
            show_citations_to_customer=setting.show_citations_to_customer,
        )


@dataclass(frozen=True)
class StructuredLLMResponse:
    """Validated structured response parsed from Claude tool use."""

    answer_text: str
    handoff: bool
    handoff_reason: str | None
    cited_chunk_indices: list[int]
    input_tokens: int
    output_tokens: int
    model: str


@dataclass(frozen=True)
class AnswerResult:
    """Structured output returned by rag.generate.answer()."""

    text: str
    sources: list[SourceCitation]
    handoff: bool
    handoff_reason: str | None
    tokens: TokenUsage
