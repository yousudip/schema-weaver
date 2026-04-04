"""
Code generation module — Task 5.1

Prompts GPT to write a pandas transformation script based on the confirmed
schema and data preview, then validates/extracts the generated code.
"""
from __future__ import annotations

import json
import re
from typing import Any


# ─── Prompt builders ──────────────────────────────────────────────────────────

def build_codegen_prompt(
    schema: dict[str, Any],
    preview: dict[str, Any],
) -> str:
    """Build the LLM prompt for Python transformation code generation."""
    columns: list[dict] = schema.get("columns", [])
    notes: str = schema.get("notes", "")

    col_table = "\n".join(
        f"  | {c.get('source_name','?')!r:40s} | {c.get('suggested_name','?'):30s} | {c.get('inferred_type','string'):10s} | {c.get('description','')}"
        for c in columns
    )

    file_type: str = preview.get("file_type", "csv")
    sample_rows: list = preview.get("sample_rows", [])[:6]
    sample_json: str = json.dumps(sample_rows, indent=2, default=str)

    return f"""You are a senior Python data engineer specialising in pandas data wrangling.

## Task
Write a self-contained Python script that reads a raw data file, applies the
column transformations listed below, and writes a clean CSV to disk.

## Variables already defined (do NOT redefine)
```python
input_path   # str — absolute path to the raw source file
output_path  # str — absolute path where the cleaned CSV must be written
file_type    # str — one of "csv", "excel", "pdf"
```

## Column mapping
| Source column (raw)                      | Target name (clean)            | Type       | Notes
|------------------------------------------|--------------------------------|------------|------
{col_table}

## AI data-quality observations
{notes if notes else "(none)"}

## Sample raw rows (first 6)
```json
{sample_json}
```

## Transformation requirements
1. **Read** — load the file correctly:
   - Excel (.xlsx/.xls): `pd.read_excel(input_path, header=None, dtype=str)`
     then auto-detect the true header row (skip merged title rows).
   - CSV: `pd.read_csv(input_path, dtype=str)`
2. **Select & rename** — keep ONLY the source columns listed above and rename
   them to their target names. Use `df.rename(columns={{...}})`.
3. **Clean each column by inferred type**:
   - `date` → `pd.to_datetime(col, errors='coerce')` (pandas 2.x — do NOT use
     `infer_datetime_format` which was removed) then `.dt.strftime('%Y-%m-%d')`.
   - `currency` / `number` → strip `$£€,` and whitespace, coerce to float with
     `pd.to_numeric(col.str.replace(r'[^\\d.\\-]','',regex=True), errors='coerce')`.
   - `string` → `.str.strip()`.  For status-like columns (≤10 unique values)
     apply `.str.title()` to normalise casing.
   - `boolean` → map yes/true/1 → True, no/false/0 → False, else NaN.
4. **Remove junk rows** — drop rows where all target columns are null.
5. **Remove duplicates** — `df.drop_duplicates()`.
6. **Write** — `df.to_csv(output_path, index=False, encoding='utf-8-sig')`.
7. **Print summary** to stdout:
   ```
   ✅ Cleaned <N> rows | <D> duplicates removed | <NF> nulls filled
   ```

## Constraints
- Allowed imports only: `pandas`, `numpy`, `re`, `datetime`, `json`, `math`, `pathlib`
- Do NOT use `exec`, `eval`, `subprocess`, `open` (except via pandas)
- Handle every step with `try/except` and print a clear error then `raise`

## Output format
Return ONLY the Python code inside a single ```python ... ``` block.
No prose, no explanations outside the code block.
"""


def build_validation_prompt(
    schema: dict,
    quality_report: dict,
    original_code: str,
    raw_sample_rows: list,
) -> str:
    """
    Ask the LLM to judge whether the cleaned output meets quality standards.
    If not, it must return a fixed script.

    The LLM must respond with a single JSON object:
      { "verdict": "pass" }
      or
      { "verdict": "fail", "issues": ["..."], "fixed_code": "..." }
    """
    import json as _json
    col_issues = [
        f"  - {c['name']} ({c['type']}): fill_rate={c['fill_rate']*100:.0f}%"
        f"  sample={c['sample_values'][:3]}  issues={c['issues']}"
        for c in quality_report.get("columns", [])
        if c.get("issues") or c["fill_rate"] < 1.0
    ]
    col_issues_text = "\n".join(col_issues) if col_issues else "  (no column issues detected)"

    columns_spec = schema.get("columns", [])
    col_table = "\n".join(
        f"  {c.get('suggested_name','?')} | {c.get('inferred_type','string')} | {c.get('description','')}"
        for c in columns_spec
    )

    raw_sample_json = _json.dumps(raw_sample_rows[:4], indent=2, default=str)

    return f"""You are a senior data-quality engineer reviewing the output of an automated
pandas data-cleaning script.

## Expected output schema
{col_table}

## Quality report (after running the script)
- Total rows: {quality_report.get('total_rows', '?')}
- Overall fill rate: {quality_report.get('overall_fill_rate', 0)*100:.1f}%
- Pass: {quality_report.get('pass', False)}

Column details (only columns with fill < 100% or issues shown):
{col_issues_text}

## Raw sample rows (first 4, before cleaning)
```json
{raw_sample_json}
```

## Current cleaning script
```python
{original_code[:4000]}
```

## Your task
1. Inspect the quality report carefully.
2. If ALL date columns have ≥ 80% ISO-format fill rate AND all numeric columns are
   ≥ 90% numeric, respond with {{"verdict": "pass"}}.
3. Otherwise identify the root cause for each failing column and rewrite the
   complete fixed script.

## Critical date-parsing rules (apply when dates are failing):
- Excel `.xlsx` files often store dates as **5-digit integer serial numbers**
  (e.g. 45657). When read with `dtype=str` these come through as "45657".
  To convert: `pd.to_datetime('1899-12-30') + pd.to_timedelta(pd.to_numeric(col, errors='coerce'), unit='D')`
- For mixed-format string dates (DD/MM/YYYY, MM-DD-YY, etc.) try:
  `pd.to_datetime(col, dayfirst=True, errors='coerce')`
  then fall back to: `pd.to_datetime(col, format='mixed', dayfirst=True, errors='coerce')`
- NEVER use `infer_datetime_format=True` (removed in pandas 2.x).
- For a column that has BOTH serial integers AND string dates, detect and branch:
  ```python
  def parse_mixed_dates(s):
      numeric = pd.to_numeric(s, errors='coerce')
      result = pd.Series(index=s.index, dtype='object')
      is_serial = numeric.notna() & (numeric > 40000) & (numeric < 60000)
      result[is_serial] = (
          pd.Timestamp('1899-12-30') + pd.to_timedelta(numeric[is_serial], unit='D')
      )
      result[~is_serial] = pd.to_datetime(s[~is_serial], errors='coerce')
      return pd.to_datetime(result, errors='coerce')
  ```

## Response format
Respond with ONLY a JSON object — no markdown, no prose:
{{"verdict": "pass"}}
or
{{"verdict": "fail", "issues": ["issue 1", "issue 2"], "fixed_code": "...full python script..."}}

The fixed_code must be a complete, standalone script (same structure as the original).
"""


def parse_validation_response(text: str) -> dict:
    """Extract the JSON verdict from the LLM validation response."""
    import json as _json
    # Strip markdown code fences if present
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    # Find first { ... } block
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return _json.loads(m.group(0))
        except _json.JSONDecodeError:
            pass
    return {"verdict": "pass"}   # safe fallback — don't block on parse error


def build_codegen_reflexion_prompt(
    original_code: str,
    error_output: str,
) -> str:
    """Retry prompt when sandbox execution fails."""
    return f"""The following Python data-transformation script failed when executed.

## Failing code
```python
{original_code}
```

## Error output
```
{error_output[:3000]}
```

## Task
Diagnose the error and rewrite the complete fixed script.
Remember:
- `input_path`, `output_path`, and `file_type` are pre-defined strings.
- Only pandas, numpy, re, datetime, json, math, pathlib are available.
- Return ONLY the fixed Python code inside a ```python ... ``` block.
"""


# ─── Response parser ──────────────────────────────────────────────────────────

def parse_generated_code(text: str) -> str:
    """Extract Python code from an LLM response that may contain markdown."""
    # ```python ... ```
    m = re.search(r"```python\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    # ``` ... ```
    m = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()


# ─── Sandbox script wrapper ───────────────────────────────────────────────────

SANDBOX_PREAMBLE = """\
import pathlib, os, sys

# Pre-defined by executor — do NOT redefine
input_path  = os.environ.get("INPUT_PATH",  "/sandbox/data/input_file")
output_path = os.environ.get("OUTPUT_PATH", "/sandbox/data/output.csv")
file_type   = os.environ.get("FILE_TYPE",   "csv")

"""


def wrap_for_sandbox(user_code: str) -> str:
    """Prepend the standard preamble so input_path / output_path are available."""
    return SANDBOX_PREAMBLE + user_code
