"""
PDF extraction helpers for the multi-file pipeline.

Steps:
  1. detect_pdf_type(path) → 'text' | 'image'
  2. extract_text_pdf(path) → str
  3. extract_image_pdf(path, poppler_path='') → list[str]
  4. build_text_tabularize_prompt(text, purpose) → str
  5. build_vision_tabularize_input(images_b64, purpose) → list
  6. parse_tabular_llm_response(raw) → dict | None
"""
from __future__ import annotations

import base64
import io
import json
import re
from pathlib import Path
from typing import List, Optional


# ─── 1. Detect PDF type ───────────────────────────────────────────────────────

def detect_pdf_type(path: Path | str) -> str:
    """Return 'text' if the PDF has extractable text, 'image' otherwise."""
    import pdfplumber

    total_chars = 0
    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages[:3]:
            text = page.extract_text() or ""
            total_chars += len(text)

    return "text" if total_chars > 100 else "image"


# ─── 2. Extract text from a text-based PDF ────────────────────────────────────

def extract_text_pdf(path: Path | str, max_chars: int = 6000) -> str:
    """
    Use pdfplumber to extract all text and any tables (as pipe-delimited rows).
    Returns up to max_chars characters.
    """
    import pdfplumber

    parts: List[str] = []

    with pdfplumber.open(str(path)) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text() or ""
            if page_text:
                parts.append(page_text)

            tables = page.extract_tables() or []
            for table in tables:
                for row in table:
                    if row:
                        parts.append(" | ".join(str(cell or "") for cell in row))

    raw = "\n".join(parts)
    return raw[:max_chars]


# ─── 3. Extract pages from an image-based PDF ────────────────────────────────

def extract_image_pdf(path: Path | str, poppler_path: str = "") -> List[str]:
    """
    Convert the first 3 pages of a PDF to PNG images via pdf2image.
    Returns a list of base64-encoded PNG strings (one per page).
    """
    from pdf2image import convert_from_path

    kwargs: dict = {"first_page": 1, "last_page": 3}
    if poppler_path:
        kwargs["poppler_path"] = poppler_path

    images = convert_from_path(str(path), **kwargs)

    result: List[str] = []
    for img in images:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        result.append(base64.b64encode(buf.read()).decode("utf-8"))

    return result


# ─── 4. Build text-tabularize prompt ─────────────────────────────────────────

def build_text_tabularize_prompt(text: str, purpose: Optional[str]) -> str:
    purpose_line = f"\nBusiness context: {purpose}" if purpose else ""
    return f"""You are a data extraction expert.{purpose_line}

Below is text extracted from a PDF document. Your task is to identify any tabular data present and convert it into a structured JSON format.

Return ONLY valid JSON with exactly these keys:
- "title": a short descriptive title for the table (string)
- "columns": a list of column header strings
- "rows": a list of rows, where each row is a list of string values matching the columns

If multiple tables exist, merge them or pick the most significant one.
If no tabular data is found, return an empty columns list and empty rows list.

PDF text:
---
{text}
---

JSON output:"""


# ─── 5. Build vision-tabularize multimodal input ─────────────────────────────

def build_vision_tabularize_input(images_b64: List[str], purpose: Optional[str]) -> list:
    """
    Returns a list of content blocks for the responses API multimodal call.
    """
    purpose_line = f"\nBusiness context: {purpose}" if purpose else ""
    prompt_text = (
        f"You are a data extraction expert.{purpose_line}\n\n"
        "The following images are pages from a PDF document. "
        "Extract all tabular data you can find and return it as structured JSON.\n\n"
        "Return ONLY valid JSON with exactly these keys:\n"
        '- "title": a short descriptive title for the table (string)\n'
        '- "columns": a list of column header strings\n'
        '- "rows": a list of rows, where each row is a list of string values matching the columns\n\n'
        "If multiple tables exist, merge them or pick the most significant one.\n"
        "If no tabular data is found, return an empty columns list and empty rows list.\n\n"
        "JSON output:"
    )

    blocks: list = [{"type": "input_text", "text": prompt_text}]
    for b64 in images_b64:
        blocks.append({
            "type": "input_image",
            "image_url": f"data:image/png;base64,{b64}",
        })

    return blocks


# ─── 6. Parse and validate LLM tabular response ───────────────────────────────

def parse_tabular_llm_response(raw: str) -> Optional[dict]:
    """
    Extract JSON from LLM response (may be wrapped in ```json blocks).
    Validates that it has 'columns' (list) and 'rows' (list of lists).
    Returns dict with: columns, sample_rows (first 20), row_count.
    Returns None if parsing fails.
    """
    # Strip markdown code fences
    text = raw.strip()
    fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence_match:
        text = fence_match.group(1).strip()

    # Try to find the outermost JSON object
    brace_match = re.search(r"\{[\s\S]*\}", text)
    if brace_match:
        text = brace_match.group(0)

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(data, dict):
        return None

    columns = data.get("columns")
    rows = data.get("rows")

    if not isinstance(columns, list):
        return None
    if not isinstance(rows, list):
        return None

    # Normalise columns — strip encoding artefacts
    clean_cols = [str(c).encode("utf-8", "replace").decode("utf-8") for c in columns]

    # Ensure rows are dicts keyed by column name (build_prompt expects this)
    clean_rows: List[dict] = []
    for row in rows:
        if isinstance(row, list):
            # Pad/trim to match column count
            padded = list(row) + [""] * max(0, len(clean_cols) - len(row))
            clean_rows.append({col: str(padded[i]) for i, col in enumerate(clean_cols)})
        elif isinstance(row, dict):
            clean_rows.append({col: str(row.get(col, "")) for col in clean_cols})

    return {
        "title": str(data.get("title", "")),
        "columns": clean_cols,
        "sample_rows": clean_rows[:20],
        "row_count": len(clean_rows),
    }
