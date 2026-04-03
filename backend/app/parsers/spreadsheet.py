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
        df = pd.read_excel(path)
    sample = df.head(max_rows).to_dict(orient="records")
    return SpreadsheetPreview(
        columns=[str(c) for c in df.columns],
        row_count=int(df.shape[0]),
        sample_rows=sample,
    )
