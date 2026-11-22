"""Thai-aware NLP helpers powered by PyThaiNLP for chunking and keyword search."""

import re
from functools import lru_cache

from pythainlp.corpus import thai_stopwords
from pythainlp.tokenize import sent_tokenize, word_tokenize

_EXTRA_QUERY_STOPWORDS: frozenset[str] = frozenset(
    {
        "ค่ะ",
        "ครับ",
        "คะ",
        "นะ",
        "นะคะ",
        "นะครับ",
        "จ้า",
        "จ๊ะ",
        "ไหม",
        "มั้ย",
        "หน่อย",
        "ด้วย",
        "หรอ",
        "เหรอ",
    }
)
_TOKEN_CLEAN_RE = re.compile(r"[^\w\u0E00-\u0E7F]+", re.UNICODE)


@lru_cache(maxsize=1)
def _query_stopwords() -> frozenset[str]:
    return frozenset(thai_stopwords()) | _EXTRA_QUERY_STOPWORDS


def segment_sentences(text: str) -> list[str]:
    """Split Thai/English prose into sentences while preserving paragraph boundaries."""
    sentences: list[str] = []
    for paragraph in text.splitlines():
        stripped = paragraph.strip()
        if not stripped:
            continue
        raw_parts = sent_tokenize(stripped)
        for part in raw_parts:
            text_part = part if isinstance(part, str) else "".join(part)
            cleaned = text_part.strip()
            if cleaned:
                sentences.append(cleaned)
    return sentences


def tokenize_words(text: str) -> list[str]:
    """Segment text into non-whitespace Thai/English word tokens via PyThaiNLP newmm."""
    tokens: list[str] = word_tokenize(text, engine="newmm", keep_whitespace=False)
    return [tok for tok in tokens if tok.strip()]


def tokenize_words_with_spaces(text: str) -> list[str]:
    """Segment text into word tokens while retaining whitespace pieces for lossless joins."""
    tokens: list[str] = word_tokenize(text, engine="newmm", keep_whitespace=True)
    return tokens


def estimate_tokens(text: str) -> int:
    """Estimate token count using PyThaiNLP word segmentation."""
    return len(tokenize_words(text))


def _sanitize_lexeme(token: str) -> str:
    return _TOKEN_CLEAN_RE.sub("", token.lower()).strip()


def to_tsv_text(text: str) -> str:
    """Produce space-delimited Thai word lexemes for PostgreSQL to_tsvector('simple', ...)."""
    lexemes = [_sanitize_lexeme(tok) for tok in tokenize_words(text)]
    return " ".join(lex for lex in lexemes if lex)


def build_search_tsquery(query: str) -> str:
    """Build a safe OR-combined PostgreSQL tsquery string from a Thai customer question."""
    stopwords = _query_stopwords()
    raw_lexemes = [_sanitize_lexeme(tok) for tok in tokenize_words(query)]
    non_empty = [lex for lex in raw_lexemes if lex]
    if not non_empty:
        return ""

    filtered = [lex for lex in non_empty if lex not in stopwords and len(lex) > 1]
    chosen = filtered if filtered else non_empty
    deduped = list(dict.fromkeys(chosen))
    return " | ".join(deduped[:24])
