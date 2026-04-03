from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

import pdfplumber
import pytesseract
from pdf2image import convert_from_path


@dataclass(frozen=True)
class PdfPreview:
    page_count: int
    text_excerpt: str
    tables_count: int
    ocr_needed: bool
    table_samples: List[List[List[str]]]


def configure_ocr(settings) -> None:
    if settings.tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd


def parse_pdf(path: Path, max_pages: int = 5) -> PdfPreview:
    extracted_text: List[str] = []
    table_samples: List[List[List[str]]] = []
    page_count = 0

    with pdfplumber.open(path) as pdf:
        page_count = len(pdf.pages)
        for page in pdf.pages[:max_pages]:
            text = page.extract_text() or ""
            if text:
                extracted_text.append(text)

    text_excerpt = "\n".join(extracted_text)[:2000]
    ocr_needed = len(text_excerpt.strip()) == 0

    tables_count = 0
    camelot_tables = _try_camelot_tables(path)
    if camelot_tables:
        tables_count = len(camelot_tables)
        for table in camelot_tables[:3]:
            table_samples.append(table)

    return PdfPreview(
        page_count=page_count,
        text_excerpt=text_excerpt,
        tables_count=tables_count,
        ocr_needed=ocr_needed,
        table_samples=table_samples,
    )


def parse_pdf_with_ocr(path: Path, max_pages: int = 3, poppler_path: str = "") -> PdfPreview:
    preview = parse_pdf(path, max_pages=max_pages)
    if not preview.ocr_needed:
        return preview
    images = convert_from_path(str(path), first_page=1, last_page=max_pages, poppler_path=poppler_path or None)
    ocr_texts: List[str] = []
    for image in images:
        ocr_texts.append(pytesseract.image_to_string(image))
    ocr_excerpt = "\n".join(ocr_texts)[:2000]
    return PdfPreview(
        page_count=preview.page_count,
        text_excerpt=ocr_excerpt,
        tables_count=preview.tables_count,
        ocr_needed=False,
        table_samples=preview.table_samples,
    )


def _try_camelot_tables(path: Path) -> Optional[List[List[List[str]]]]:
    try:
        import camelot
    except Exception:
        return None
    try:
        tables = camelot.read_pdf(str(path), pages="1-3")
        return [table.data for table in tables]
    except Exception:
        return None
