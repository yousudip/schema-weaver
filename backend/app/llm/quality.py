"""
Data Quality Report — Task 5.2 (Validation Loop)

Computes a per-column quality report from the cleaned output CSV,
comparing against the expected schema. Runs on the host (not in Docker).
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pandas as pd


# ─── Quality report computation ───────────────────────────────────────────────

def compute_quality_report(
    output_csv_path: Path | str,
    schema: dict[str, Any],
) -> dict[str, Any]:
    """
    Read the cleaned output CSV and produce a per-column quality report.

    Returns:
        {
            "total_rows": int,
            "total_columns": int,
            "overall_fill_rate": float,   # 0.0–1.0
            "pass": bool,                 # True if no critical issues
            "columns": [
                {
                    "name": str,
                    "type": str,
                    "present": bool,
                    "total_rows": int,
                    "fill_count": int,
                    "null_count": int,
                    "fill_rate": float,
                    "sample_values": list[str],
                    "unique_count": int,
                    "issues": list[str],   # human-readable problems
                },
                ...
            ]
        }
    """
    try:
        df = pd.read_csv(str(output_csv_path), dtype=str, encoding="utf-8-sig")
    except Exception as exc:
        return {
            "total_rows": 0,
            "total_columns": 0,
            "overall_fill_rate": 0.0,
            "pass": False,
            "columns": [],
            "read_error": str(exc),
        }

    total_rows = len(df)
    columns_spec: list[dict] = schema.get("columns", [])
    col_reports: list[dict] = []

    for col_spec in columns_spec:
        target = col_spec.get("suggested_name", "").strip()
        inferred_type = col_spec.get("inferred_type", "string")
        source_name = col_spec.get("source_name", target)

        if target not in df.columns:
            col_reports.append({
                "name": target,
                "source_name": source_name,
                "type": inferred_type,
                "present": False,
                "total_rows": total_rows,
                "fill_count": 0,
                "null_count": total_rows,
                "fill_rate": 0.0,
                "sample_values": [],
                "unique_count": 0,
                "issues": [f"Column '{target}' is missing from the output CSV"],
            })
            continue

        col = df[target].copy()
        # Treat empty strings as null
        is_null = col.isna() | (col.astype(str).str.strip() == "")
        null_count = int(is_null.sum())
        fill_count = total_rows - null_count
        fill_rate = round(fill_count / total_rows, 4) if total_rows > 0 else 0.0

        non_null_col = col[~is_null]
        sample_values = [str(v) for v in non_null_col.head(5).tolist()]
        unique_count = int(non_null_col.nunique())

        issues: list[str] = []

        # Low fill rate warning
        if fill_rate == 0.0:
            issues.append(
                f"Column is entirely empty — date/format parsing likely failed completely"
            )
        elif fill_rate < 0.5:
            issues.append(
                f"Low fill rate ({fill_rate*100:.0f}%) — possible parsing or format mismatch"
            )

        # Date-specific validation
        if inferred_type == "date" and fill_count > 0:
            iso_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
            iso_count = non_null_col.astype(str).str.strip().apply(
                lambda v: bool(iso_pattern.match(v))
            ).sum()
            iso_rate = iso_count / fill_count
            if iso_rate < 0.8:
                issues.append(
                    f"Only {int(iso_count)}/{fill_count} non-null values match ISO date format "
                    f"YYYY-MM-DD (rate {iso_rate*100:.0f}%) — date conversion may be wrong"
                )
            # Detect Excel serial numbers (5-digit integers stored as string)
            serial_count = non_null_col.astype(str).str.strip().str.match(r"^\d{5}$").sum()
            if serial_count > 0:
                issues.append(
                    f"{int(serial_count)} values look like Excel date serial numbers "
                    f"(e.g. 45657) — use pd.to_timedelta + epoch instead of pd.to_datetime"
                )

        # Currency/number: check nothing became NaN that shouldn't
        if inferred_type in ("currency", "number") and fill_count > 0:
            # Check if values are numeric
            numeric_ok = pd.to_numeric(non_null_col, errors="coerce").notna().sum()
            if numeric_ok / fill_count < 0.9:
                issues.append(
                    f"Only {int(numeric_ok)}/{fill_count} non-null values are valid numbers — "
                    f"currency stripping may be incomplete"
                )

        col_reports.append({
            "name": target,
            "source_name": source_name,
            "type": inferred_type,
            "present": True,
            "total_rows": total_rows,
            "fill_count": fill_count,
            "null_count": null_count,
            "fill_rate": fill_rate,
            "sample_values": sample_values,
            "unique_count": unique_count,
            "issues": issues,
        })

    overall_fill = (
        sum(c["fill_rate"] for c in col_reports) / len(col_reports)
        if col_reports else 0.0
    )

    # Critical: column missing entirely OR has issues AND fill < 50%
    critical_issues = [
        c for c in col_reports
        if not c["present"] or (c.get("issues") and c["fill_rate"] < 0.5)
    ]

    return {
        "total_rows": total_rows,
        "total_columns": len(col_reports),
        "overall_fill_rate": round(overall_fill, 4),
        "pass": len(critical_issues) == 0,
        "columns": col_reports,
    }
