from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List

import pandas as pd


@dataclass(frozen=True)
class SpreadsheetPreview:
    columns: List[str]
    row_count: int
    sample_rows: List[dict]


def _detect_header_row(path: Path, max_scan: int = 10) -> int:
    """
    Scan the first `max_scan` rows to find the true header row.

    Strategy: skip rows that look like a document title (a single non-null
    value spread across many columns, or all-null rows) and return the index
    of the first row where ≥60 % of cells are non-null short strings — that
    is almost certainly a column-header row.
    """
    try:
        raw = pd.read_excel(path, header=None, nrows=max_scan, dtype=str)
    except Exception:
        return 0  # fall back to default

    for i, row in raw.iterrows():
        non_null = row.dropna()
        if len(non_null) == 0:
            continue  # blank row — skip
        if len(non_null) == 1:
            continue  # single title cell — skip
        # Check fill-ratio and value length
        fill_ratio = len(non_null) / len(row)
        avg_len = non_null.astype(str).str.len().mean()
        if fill_ratio >= 0.5 and avg_len <= 60:
            return int(str(i))  # type: ignore[arg-type]
    return 0


def parse_spreadsheet(path: Path, max_rows: int = 50) -> SpreadsheetPreview:
    if path.suffix.lower() == ".csv":
        try:
            df = pd.read_csv(
                path, encoding="utf-8", encoding_errors="replace", on_bad_lines="skip"
            )
        except TypeError:
            df = pd.read_csv(path, encoding="utf-8", on_bad_lines="skip")
        except UnicodeDecodeError:
            df = pd.read_csv(path, encoding="latin-1", on_bad_lines="skip")
    else:
        header_row = _detect_header_row(path)
        df = pd.read_excel(path, header=header_row)
        # Drop fully-empty rows that appear before or after real data
        df = df.dropna(how="all").reset_index(drop=True)

    sample = df.head(max_rows).to_dict(orient="records")
    return SpreadsheetPreview(
        columns=[str(c) for c in df.columns],
        row_count=int(df.shape[0]),
        sample_rows=sample,
    )
