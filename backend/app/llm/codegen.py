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
