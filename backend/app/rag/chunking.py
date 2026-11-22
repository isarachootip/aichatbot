"""Thai-aware document chunker (~500 tokens, ~50 overlap, zero mid-word splits)."""

from collections.abc import Sequence
from dataclasses import dataclass

from app.rag.parsing import ParsedPage
from app.rag.thai_nlp import (
    estimate_tokens,
    segment_sentences,
    tokenize_words_with_spaces,
)


@dataclass(frozen=True)
class TextChunk:
    """Single indexed text chunk with source page number and token count."""

    content: str
    page: int
    chunk_index: int
    tokens: int


def _trailing_word_overlap(text: str, overlap_tokens: int) -> str:
    """Extract up to `overlap_tokens` trailing whole PyThaiNLP words without splitting mid-word."""
    if overlap_tokens <= 0 or not text:
        return ""
    tokens = tokenize_words_with_spaces(text)
    collected: list[str] = []
    word_count = 0
    for tok in reversed(tokens):
        collected.append(tok)
        if tok.strip():
            word_count += 1
            if word_count >= overlap_tokens:
                break
    collected.reverse()
    return "".join(collected).strip()


def _split_long_unit(unit: str, target_tokens: int, overlap_tokens: int) -> list[str]:
    """Split an oversized single sentence strictly on PyThaiNLP word boundaries."""
    tokens = tokenize_words_with_spaces(unit)
    pieces: list[str] = []
    current: list[str] = []
    current_count = 0

    for tok in tokens:
        is_word = bool(tok.strip())
        if is_word and current_count >= target_tokens and current:
            piece = "".join(current).strip()
            if piece:
                pieces.append(piece)
            overlap_str = _trailing_word_overlap(piece, min(overlap_tokens, target_tokens - 1))
            current = tokenize_words_with_spaces(overlap_str) if overlap_str else []
            current_count = sum(1 for item in current if item.strip())

        current.append(tok)
        if is_word:
            current_count += 1

    tail = "".join(current).strip()
    if tail:
        pieces.append(tail)
    return pieces


def _tail_units_for_overlap(units: list[str], overlap_tokens: int) -> list[str]:
    """Collect trailing sentences/units up to `overlap_tokens` for chunk overlap."""
    if overlap_tokens <= 0 or not units:
        return []

    kept: list[str] = []
    total = 0
    for unit in reversed(units):
        unit_tokens = estimate_tokens(unit)
        if total + unit_tokens <= overlap_tokens:
            kept.append(unit)
            total += unit_tokens
        else:
            if not kept:
                partial = _trailing_word_overlap(unit, overlap_tokens)
                if partial:
                    kept.append(partial)
            break
    kept.reverse()
    return kept


def _chunk_prose_page(text: str, target_tokens: int, overlap_tokens: int) -> list[str]:
    raw_sentences = segment_sentences(text)
    units: list[str] = []
    for sentence in raw_sentences:
        if estimate_tokens(sentence) > target_tokens:
            units.extend(_split_long_unit(sentence, target_tokens, overlap_tokens))
        else:
            units.append(sentence)

    chunks: list[str] = []
    current_units: list[str] = []
    current_tokens = 0

    for unit in units:
        unit_tokens = estimate_tokens(unit)
        if current_units and current_tokens + unit_tokens > target_tokens:
            chunks.append(" ".join(current_units).strip())
            overlap_units = _tail_units_for_overlap(current_units, overlap_tokens)
            current_units = list(overlap_units)
            current_tokens = sum(estimate_tokens(item) for item in current_units)

        current_units.append(unit)
        current_tokens += unit_tokens

    if current_units:
        chunks.append(" ".join(current_units).strip())
    return [chunk for chunk in chunks if chunk]


def _chunk_tabular_rows(
    rows: tuple[str, ...],
    target_tokens: int,
    overlap_tokens: int,
) -> list[str]:
    """Pack complete XLSX/CSV table rows without ever splitting inside a row."""
    chunks: list[str] = []
    current_rows: list[str] = []
    current_tokens = 0

    for row in rows:
        row_tokens = estimate_tokens(row)
        if current_rows and current_tokens + row_tokens > target_tokens:
            chunks.append("\n".join(current_rows))
            overlap_rows: list[str] = []
            overlap_sum = 0
            for prev_row in reversed(current_rows):
                prev_tokens = estimate_tokens(prev_row)
                fits_overlap = overlap_sum + prev_tokens <= overlap_tokens
                fits_next = overlap_sum + row_tokens < target_tokens
                if fits_overlap and fits_next:
                    overlap_rows.append(prev_row)
                    overlap_sum += prev_tokens
                else:
                    break
            overlap_rows.reverse()
            current_rows = overlap_rows
            current_tokens = overlap_sum

        current_rows.append(row)
        current_tokens += row_tokens

    if current_rows:
        chunks.append("\n".join(current_rows))
    return chunks


def chunk_pages(
    pages: Sequence[ParsedPage],
    *,
    target_tokens: int = 500,
    overlap_tokens: int = 50,
) -> list[TextChunk]:
    """Chunk parsed pages into Thai-aware segments keeping page numbers and atomic rows."""
    if target_tokens <= 0:
        raise ValueError("target_tokens must be positive")
    if overlap_tokens < 0 or overlap_tokens >= target_tokens:
        raise ValueError("overlap_tokens must be >= 0 and < target_tokens")

    result: list[TextChunk] = []
    chunk_index = 0
    for page in pages:
        raw_chunks = (
            _chunk_tabular_rows(page.rows, target_tokens, overlap_tokens)
            if page.rows
            else _chunk_prose_page(page.text, target_tokens, overlap_tokens)
        )
        for content in raw_chunks:
            result.append(
                TextChunk(
                    content=content,
                    page=page.page,
                    chunk_index=chunk_index,
                    tokens=estimate_tokens(content),
                )
            )
            chunk_index += 1
    return result
