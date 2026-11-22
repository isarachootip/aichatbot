"""Unit tests for Thai-aware NLP helpers and PyThaiNLP chunker."""

from itertools import pairwise

from app.rag.chunking import chunk_pages
from app.rag.parsing import ParsedPage
from app.rag.thai_nlp import build_search_tsquery, estimate_tokens, to_tsv_text, tokenize_words


def _build_long_thai_document() -> str:
    sentences = [
        "ร้านสยามสไตล์จัดส่งสินค้าทุกวันจันทร์ถึงเสาร์ตัดรอบเวลาสิบสี่นาฬิกาตรงค่ะ",
        "ค่าจัดส่งมาตรฐานทั่วประเทศเริ่มต้นสี่สิบบาทและจัดส่งฟรีเมื่อสั่งซื้อครบห้าร้อยบาทค่ะ",
        "ลูกค้ารอรับสินค้าภายในหนึ่งถึงสามวันทำการสำหรับกรุงเทพและปริมณฑลค่ะ",
        "สำหรับต่างจังหวัดและพื้นที่ห่างไกลอาจใช้เวลาสองถึงสี่วันทำการค่ะ",
        "นโยบายการคืนสินค้าและเปลี่ยนไซส์สามารถทำได้ภายในเจ็ดวันนับจากวันที่ได้รับพัสดุค่ะ",
        "สินค้าที่ส่งคืนต้องอยู่ในสภาพสมบูรณ์ไม่ผ่านการซักและยังมีป้ายราคาครบถ้วนค่ะ",
        "ช่องทางการชำระเงินรองรับการโอนผ่านพร้อมเพย์บัตรเครดิตและเก็บเงินปลายทางค่ะ",
        "หากสินค้าชำรุดจากโรงงานทางร้านยินดีเปลี่ยนชิ้นใหม่ให้ฟรีพร้อมออกค่าขนส่งให้ทั้งหมดค่ะ",
    ]
    return "\n\n".join(" ".join(sentences) for _ in range(8))


def test_thai_chunking_has_no_mid_word_splits_and_preserves_overlap() -> None:
    text = _build_long_thai_document()
    page = ParsedPage(page=2, text=text)

    chunks = chunk_pages([page], target_tokens=120, overlap_tokens=20)

    assert len(chunks) >= 3
    for idx, chunk in enumerate(chunks):
        assert chunk.page == 2
        assert chunk.chunk_index == idx
        assert chunk.tokens > 0
        assert chunk.tokens <= 150

    # Verify consecutive chunks share whole-word overlap
    for prev, curr in pairwise(chunks):
        prev_words = tokenize_words(prev.content)
        curr_words = tokenize_words(curr.content)
        overlap = set(prev_words[-25:]) & set(curr_words[:25])
        assert len(overlap) >= 5, f"Expected Thai word overlap, got {overlap}"


def test_single_very_long_thai_sentence_never_splits_mid_word() -> None:
    # Continuous Thai string with no spaces at all
    phrase = "นโยบายการรับประกันสินค้าอิเล็กทรอนิกส์และอุปกรณ์เสริมของร้านค้าออนไลน์"
    long_unspaced = phrase * 15
    original_words = tokenize_words(long_unspaced)

    chunks = chunk_pages(
        [ParsedPage(page=1, text=long_unspaced)],
        target_tokens=40,
        overlap_tokens=8,
    )

    assert len(chunks) >= 2
    valid_vocab = set(original_words)
    for chunk in chunks:
        chunk_words = tokenize_words(chunk.content)
        # Every first and last token of every chunk must be an intact word from the original text
        assert chunk_words[0] in valid_vocab
        assert chunk_words[-1] in valid_vocab


def test_tabular_chunking_keeps_every_table_row_intact() -> None:
    rows = tuple(
        f"รหัสสินค้า: SKU-{i:03d} | ชื่อสินค้า: เสื้อเชิ้ตผ้าฝ้ายรุ่นที่ {i} | ราคา: {390 + i * 10} บาท"
        for i in range(1, 26)
    )
    page = ParsedPage(page=1, text="\n".join(rows), rows=rows)

    chunks = chunk_pages([page], target_tokens=90, overlap_tokens=20)

    assert len(chunks) >= 2
    seen_rows: set[str] = set()
    for chunk in chunks:
        for line in chunk.content.splitlines():
            assert line in rows, f"Row was split or corrupted: {line!r}"
            seen_rows.add(line)
    assert seen_rows == set(rows)


def test_thai_nlp_tsv_and_query_tokenization() -> None:
    tsv = to_tsv_text("ค่าจัดส่งเท่าไหร่ ส่งฟรีครบ 500 บาท")
    assert "ค่าจัดส่ง" in tsv or "จัดส่ง" in tsv
    assert "500" in tsv

    tsquery = build_search_tsquery("ค่าจัดส่งเท่าไหร่ครับ?")
    assert "ครับ" not in tsquery
    assert "|" in tsquery or len(tsquery) > 0
    assert estimate_tokens("สวัสดีค่ะ สอบถามค่าส่ง 50 บาท") >= 4
