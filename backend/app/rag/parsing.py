"""Document parser extracting text, page numbers, and tabular rows."""

import io
import re
from dataclasses import dataclass
from pathlib import Path

import docx
import pandas as pd
import pymupdf
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


class DocumentParseError(ValueError):
    """Raised when a document cannot be parsed or yields no usable text."""


@dataclass(frozen=True)
class ParsedPage:
    """Extracted text content for a single logical page or spreadsheet sheet."""

    page: int
    text: str
    rows: tuple[str, ...] = ()


_MIME_TO_EXT: dict[str, str] = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "application/vnd.ms-excel": ".xlsx",
    "text/csv": ".csv",
    "application/csv": ".csv",
    "text/plain": ".txt",
}


def _normalize_text(raw: str) -> str:
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _decode_bytes(data: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp874", "tis-620"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise DocumentParseError("Unable to decode text file as UTF-8 or Thai CP874")


def _parse_pdf(data: bytes) -> list[ParsedPage]:
    pages: list[ParsedPage] = []
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise DocumentParseError(f"Invalid PDF file: {exc}") from exc

    try:
        for idx in range(len(doc)):
            raw_text = str(doc[idx].get_text("text") or "")
            cleaned = _normalize_text(raw_text)
            if cleaned:
                pages.append(ParsedPage(page=idx + 1, text=cleaned))
    finally:
        doc.close()

    if not pages:
        raise DocumentParseError(
            "PDF contains no extractable text (scanned/image-only PDFs are not supported in MVP)"
        )
    return pages


def _has_page_break(paragraph: Paragraph) -> bool:
    attr = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}type"
    return any(
        elem.tag.endswith("}br") and elem.get(attr) == "page"
        for elem in paragraph._p.iter()
    )


def _parse_docx(data: bytes) -> list[ParsedPage]:
    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentParseError(f"Invalid DOCX file: {exc}") from exc

    pages: list[ParsedPage] = []
    lines: list[str] = []
    page_num = 1
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            para = Paragraph(child, document)
            if _has_page_break(para):
                combined = _normalize_text("\n".join(lines))
                if combined:
                    pages.append(ParsedPage(page=page_num, text=combined))
                lines, page_num = [], page_num + 1
            if para.text.strip():
                lines.append(para.text.strip())
        elif isinstance(child, CT_Tbl):
            for row in Table(child, document).rows:
                cells = [cell.text.strip().replace("\n", " ") for cell in row.cells]
                if any(cells):
                    lines.append(" | ".join(cells))

    tail = _normalize_text("\n".join(lines))
    if tail:
        pages.append(ParsedPage(page=page_num, text=tail))
    if not pages:
        raise DocumentParseError("DOCX contains no extractable text")
    return pages


def _dataframe_to_rows(df: pd.DataFrame, *, prefix: str = "") -> tuple[str, ...]:
    cleaned_df = df.dropna(how="all")
    columns = [str(col).strip() for col in cleaned_df.columns]
    rows: list[str] = []
    for record in cleaned_df.to_dict(orient="records"):
        parts: list[str] = []
        for col, raw_val in zip(columns, record.values(), strict=False):
            if pd.isna(raw_val):
                continue
            val = str(raw_val).strip()
            if val:
                parts.append(f"{col}: {val}")
        if parts:
            line = " | ".join(parts)
            rows.append(f"{prefix}{line}" if prefix else line)
    return tuple(rows)


def _parse_xlsx(data: bytes) -> list[ParsedPage]:
    try:
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, dtype=str)
    except Exception as exc:
        raise DocumentParseError(f"Invalid XLSX file: {exc}") from exc

    pages: list[ParsedPage] = []
    for idx, (sheet_name, df) in enumerate(sheets.items(), start=1):
        rows = _dataframe_to_rows(df, prefix=f"[{sheet_name}] ")
        if rows:
            pages.append(ParsedPage(page=idx, text="\n".join(rows), rows=rows))

    if not pages:
        raise DocumentParseError("XLSX workbook contains no rows")
    return pages


def _parse_csv(data: bytes) -> list[ParsedPage]:
    decoded = _decode_bytes(data)
    try:
        df = pd.read_csv(io.StringIO(decoded), dtype=str)
    except Exception as exc:
        raise DocumentParseError(f"Invalid CSV file: {exc}") from exc

    rows = _dataframe_to_rows(df)
    if not rows:
        raise DocumentParseError("CSV file contains no rows")
    return [ParsedPage(page=1, text="\n".join(rows), rows=rows)]


def _parse_txt(data: bytes) -> list[ParsedPage]:
    cleaned = _normalize_text(_decode_bytes(data))
    if not cleaned:
        raise DocumentParseError("TXT file is empty")
    return [ParsedPage(page=1, text=cleaned)]


def _resolve_extension(filename: str, mime: str | None) -> str:
    ext = Path(filename).suffix.lower()
    if ext in {".pdf", ".docx", ".xlsx", ".csv", ".txt"}:
        return ext
    if mime:
        mapped = _MIME_TO_EXT.get(mime.split(";")[0].strip().lower())
        if mapped:
            return mapped
    raise DocumentParseError(f"Unsupported file format: filename={filename!r}, mime={mime!r}")


def parse_document(data: bytes, *, filename: str, mime: str | None = None) -> list[ParsedPage]:
    """Extract logical pages (text + 1-based page numbers) from supported formats."""
    dispatch = {
        ".pdf": _parse_pdf,
        ".docx": _parse_docx,
        ".xlsx": _parse_xlsx,
        ".csv": _parse_csv,
        ".txt": _parse_txt,
    }
    return dispatch[_resolve_extension(filename, mime)](data)
