"""Unit tests for multi-format Thai document parsing (PDF, DOCX, XLSX, CSV, TXT)."""

import io

import docx
import pandas as pd
import pymupdf
import pytest

from app.rag.parsing import DocumentParseError, parse_document


def _make_pdf(pages: list[str]) -> bytes:
    """Create a real text-based PDF in memory using PyMuPDF."""
    doc = pymupdf.open()
    for text in pages:
        page = doc.new_page()
        if text:
            page.insert_text((72, 72), text, fontsize=12)
    raw: bytes = doc.tobytes()
    doc.close()
    return raw


def _make_docx(paragraphs: list[str], table_rows: list[list[str]] | None = None) -> bytes:
    """Create a real DOCX document in memory using python-docx."""
    document = docx.Document()
    for para in paragraphs:
        document.add_paragraph(para)
    if table_rows:
        table = document.add_table(rows=len(table_rows), cols=len(table_rows[0]))
        for r_idx, row in enumerate(table_rows):
            for c_idx, cell_val in enumerate(row):
                table.rows[r_idx].cells[c_idx].text = cell_val
    buf = io.BytesIO()
    document.save(buf)
    return buf.getvalue()


def _make_xlsx(sheets: dict[str, list[dict[str, str]]]) -> bytes:
    """Create a real multi-sheet XLSX workbook in memory using pandas + openpyxl."""
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        for sheet_name, rows in sheets.items():
            pd.DataFrame(rows).to_excel(writer, sheet_name=sheet_name, index=False)
    return buf.getvalue()


def test_parse_pdf_preserves_page_numbers() -> None:
    pdf_bytes = _make_pdf(["Page one shipping policy", "", "Page three return policy"])

    pages = parse_document(pdf_bytes, filename="policy.pdf", mime="application/pdf")

    assert len(pages) == 2
    assert pages[0].page == 1
    assert "Page one shipping policy" in pages[0].text
    assert pages[1].page == 3
    assert "Page three return policy" in pages[1].text


def test_parse_scanned_empty_pdf_raises_parse_error() -> None:
    empty_pdf = _make_pdf([""])

    with pytest.raises(DocumentParseError, match="no extractable text"):
        parse_document(empty_pdf, filename="scan.pdf", mime="application/pdf")


def test_parse_docx_extracts_paragraphs_and_tables() -> None:
    raw = _make_docx(
        paragraphs=["นโยบายการจัดส่งสินค้าของร้าน"],
        table_rows=[
            ["ประเภทการจัดส่ง", "ค่าบริการ"],
            ["ส่งด่วน EMS", "50 บาท"],
        ],
    )

    pages = parse_document(
        raw,
        filename="shipping.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    assert len(pages) == 1
    assert pages[0].page == 1
    assert "นโยบายการจัดส่งสินค้าของร้าน" in pages[0].text
    assert "ส่งด่วน EMS" in pages[0].text
    assert "50 บาท" in pages[0].text


def test_parse_xlsx_keeps_rows_intact_and_tracks_sheet_pages() -> None:
    raw = _make_xlsx(
        {
            "Products": [
                {"สินค้า": "เสื้อยืดคอกลม", "ราคา": "290 บาท"},
                {"สินค้า": "กางเกงยีนส์", "ราคา": "890 บาท"},
            ],
            "Shipping": [
                {"ขนส่ง": "Flash Express", "ค่าส่ง": "40 บาท"},
            ],
        }
    )

    pages = parse_document(
        raw,
        filename="catalog.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    assert len(pages) == 2
    assert pages[0].page == 1
    assert len(pages[0].rows) == 2
    assert "เสื้อยืดคอกลม" in pages[0].rows[0]
    assert "290 บาท" in pages[0].rows[0]
    assert pages[1].page == 2
    assert len(pages[1].rows) == 1
    assert "Flash Express" in pages[1].rows[0]


def test_parse_csv_with_thai_utf8_bom() -> None:
    csv_text = "\ufeffสินค้า,ราคา,สต็อก\nหมวกแก๊ป,199 บาท,มีสินค้า\nกระเป๋าผ้า,250 บาท,หมดชั่วคราว\n"

    pages = parse_document(csv_text.encode("utf-8"), filename="items.csv", mime="text/csv")

    assert len(pages) == 1
    assert pages[0].page == 1
    assert len(pages[0].rows) == 2
    assert "สินค้า: หมวกแก๊ป" in pages[0].rows[0]
    assert "ราคา: 199 บาท" in pages[0].rows[0]


def test_parse_txt_thai_text() -> None:
    txt = "ร้านเปิดทำการทุกวัน 09:00 - 20:00 น.\r\nส่งฟรีเมื่อซื้อครบ 500 บาท"

    pages = parse_document(txt.encode("utf-8"), filename="faq.txt", mime="text/plain")

    assert len(pages) == 1
    assert pages[0].page == 1
    assert "09:00 - 20:00" in pages[0].text
    assert "500 บาท" in pages[0].text


def test_parse_unsupported_format_raises_error() -> None:
    with pytest.raises(DocumentParseError, match="Unsupported file format"):
        parse_document(b"fake image bytes", filename="slip.png", mime="image/png")
