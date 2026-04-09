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
    purpose: str | None = None,
) -> str:
    """Build the LLM prompt for Python transformation code generation."""
    columns: list[dict] = schema.get("columns", [])
    notes: str = schema.get("notes", "")

    col_table = "\n".join(
        f"  | {c.get('source_name','?')!r:40s} | {c.get('suggested_name','?'):30s} | {c.get('inferred_type','string'):10s} | {c.get('description','')}"
        for c in columns
    )

    file_type: str = preview.get("file_type", "csv")
    source_note: str = preview.get("source_note", "")
    sample_rows: list = preview.get("sample_rows", [])[:6]
    sample_json: str = json.dumps(sample_rows, indent=2, default=str)
    purpose_section = f"\n## Business context\n{purpose}\n" if purpose else ""
    source_note_section = f"\n## Source note\n{source_note}\n" if source_note else ""

    return f"""You are a senior Python data engineer specialising in pandas data wrangling.
{purpose_section}{source_note_section}
## Task
Write a self-contained Python script that reads a raw data file, applies the
column transformations listed below, and writes a clean CSV to disk.

## Variables already defined (do NOT redefine)
```python
input_path   # str — absolute path to the raw source file
output_path  # str — absolute path where the cleaned CSV must be written
file_type    # str — one of "csv", "excel"  (PDFs are pre-converted; file_type is NEVER "pdf")
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
   - `date` → Use this exact robust multi-pass helper. Input files often contain a MIX
     of formats in the same column (e.g. "01/22/2025" US-style AND "15/01/2025" EU-style
     AND "January 8 2025" AND "2025-01-10 00:00:00" Excel datetime strings AND Excel
     serial integers like 45657). A single dayfirst setting cannot handle all of them.
     Use this exact function — copy it verbatim:
     ```python
     def parse_dates(col):
         s = col.astype(str).str.strip()
         # 1. Blank / null guard
         is_blank = s.isin(['', 'nan', 'NaT', 'None', 'NaN'])
         result = pd.Series(pd.NaT, index=s.index, dtype='datetime64[ns]')
         # 2. Excel serial integers (5-digit, e.g. 45657)
         numeric = pd.to_numeric(s, errors='coerce')
         is_serial = numeric.notna() & (numeric > 40000) & (numeric < 60000)
         if is_serial.any():
             result[is_serial] = pd.Timestamp('1899-12-30') + pd.to_timedelta(numeric[is_serial], unit='D')
         # 3. Strip trailing time from Excel datetime strings "2025-01-05 00:00:00"
         s = s.str.replace(r'\\s+\\d{{2}}:\\d{{2}}:\\d{{2}}(\\.\\d+)?$', '', regex=True).str.strip()
         # 4. Parse remaining (not serial, not blank) with dayfirst=False (handles MM/DD/YYYY)
         mask = ~is_serial & ~is_blank & result.isna()
         if mask.any():
             parsed_mf = pd.to_datetime(s[mask], format='mixed', dayfirst=False, errors='coerce')
             result[mask] = parsed_mf
         # 5. For still-NaT entries retry with dayfirst=True (handles DD/MM/YYYY like 15/01/2025)
         still_nat = ~is_serial & ~is_blank & result.isna()
         if still_nat.any():
             parsed_df = pd.to_datetime(s[still_nat], format='mixed', dayfirst=True, errors='coerce')
             result[still_nat] = parsed_df
         return result.dt.strftime('%Y-%m-%d').where(result.notna(), other=pd.NA)
     df['col'] = parse_dates(df['col'])
     ```
     Do NOT use `infer_datetime_format` (removed in pandas 2.x).
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
- Do NOT add any `if file_type == "pdf"` checks — `file_type` is always "csv" or "excel"

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
- Excel datetime strings come through as "2025-01-05 00:00:00" — strip the time part first:
  `s = s.str.replace(r'\\s+\\d{{2}}:\\d{{2}}:\\d{{2}}(\\.\\d+)?$', '', regex=True)`
- Excel `.xlsx` files often store dates as **5-digit integer serial numbers** (e.g. 45657).
  Detect with: `numeric.notna() & (numeric > 40000) & (numeric < 60000)`
  Convert with: `pd.Timestamp('1899-12-30') + pd.to_timedelta(numeric, unit='D')`
- For mixed string formats (DD/MM/YYYY, "January 25 2025", MM/DD/YYYY, ISO, etc.) use:
  `pd.to_datetime(col, format='mixed', dayfirst=True, errors='coerce')`
- NEVER use `infer_datetime_format=True` (removed in pandas 2.x).
- The input data often has MIXED date formats in the same column (MM/DD/YYYY AND DD/MM/YYYY
  AND long month names AND Excel serial integers AND datetime strings). A single dayfirst
  setting will fail on half the rows. Always use this multi-pass helper:
  ```python
  def parse_dates(col):
      s = col.astype(str).str.strip()
      is_blank = s.isin(['', 'nan', 'NaT', 'None', 'NaN'])
      result = pd.Series(pd.NaT, index=s.index, dtype='datetime64[ns]')
      numeric = pd.to_numeric(s, errors='coerce')
      is_serial = numeric.notna() & (numeric > 40000) & (numeric < 60000)
      if is_serial.any():
          result[is_serial] = pd.Timestamp('1899-12-30') + pd.to_timedelta(numeric[is_serial], unit='D')
      s = s.str.replace(r'\\s+\\d{{2}}:\\d{{2}}:\\d{{2}}(\\.\\d+)?$', '', regex=True).str.strip()
      mask = ~is_serial & ~is_blank & result.isna()
      if mask.any():
          result[mask] = pd.to_datetime(s[mask], format='mixed', dayfirst=False, errors='coerce')
      still_nat = ~is_serial & ~is_blank & result.isna()
      if still_nat.any():
          result[still_nat] = pd.to_datetime(s[still_nat], format='mixed', dayfirst=True, errors='coerce')
      return result.dt.strftime('%Y-%m-%d').where(result.notna(), other=pd.NA)
  ```

## Response format
If quality is acceptable:
```json
{{"verdict": "pass"}}
```

If quality needs fixing, respond in this exact two-part format:
```json
{{"verdict": "fail", "issues": ["issue 1", "issue 2"]}}
```
```python
# ... complete fixed standalone Python script here ...
```

IMPORTANT: Put the Python script in a separate ```python block, NOT inside the JSON.
The fixed script must be complete and standalone (same structure as the original).

## Hard constraints for the fixed script (violations cause immediate crash):
- FORBIDDEN calls: `open()`, `exec()`, `eval()`, `compile()`, `__import__()`
- FORBIDDEN modules: `subprocess`, `socket`, `os.system`, `sys.exit`
- All file I/O MUST go through pandas (`pd.read_csv`, `pd.read_excel`, `df.to_csv`)
- Allowed imports ONLY: `pandas`, `numpy`, `re`, `datetime`, `json`, `math`, `pathlib`, `os`, `sys`
"""


def parse_validation_response(text: str) -> dict:
    """
    Extract the JSON verdict from the LLM validation response.

    The LLM often embeds a full Python script inside the JSON string, which
    breaks standard json.loads (unescaped newlines/quotes).  We therefore:
      1. Try normal json.loads on the whole block.
      2. If that fails, extract verdict + issues with regex, then look for
         the fixed_code in a ```python ... ``` fence that follows the JSON.
      3. Fallback is "fail" (not "pass") so we never silently accept bad output.
    """
    import json as _json

    original = text.strip()

    # ── 1. Strip outer markdown fences ───────────────────────────────────────
    text = re.sub(r"^```(?:json)?\s*", "", original)
    text = re.sub(r"\s*```$", "", text).strip()

    # ── 2. Happy-path: valid JSON ─────────────────────────────────────────────
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return _json.loads(m.group(0))
        except _json.JSONDecodeError:
            pass

    # ── 3. Degraded parse: extract verdict + issues with regex ────────────────
    verdict_m = re.search(r'"verdict"\s*:\s*"(pass|fail)"', original)
    if not verdict_m:
        # Cannot determine verdict — assume fail so loop retries
        return {"verdict": "fail", "issues": ["[parse error] Could not determine verdict"]}

    verdict = verdict_m.group(1)
    if verdict == "pass":
        return {"verdict": "pass"}

    # Extract issues array (best-effort)
    issues: list[str] = []
    issues_m = re.search(r'"issues"\s*:\s*\[([^\]]*)\]', original, re.DOTALL)
    if issues_m:
        for item in re.findall(r'"((?:[^"\\]|\\.)*)"', issues_m.group(1)):
            issues.append(item)

    # Extract fixed_code from a ```python fence that appears anywhere in the response
    code_m = re.search(r"```python\s*(.*?)```", original, re.DOTALL)
    fixed_code = code_m.group(1).strip() if code_m else ""

    return {"verdict": "fail", "issues": issues, "fixed_code": fixed_code}


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
- Only pandas, numpy, re, datetime, json, math, pathlib, os, sys are available.
- FORBIDDEN: `open()`, `exec()`, `eval()`, `compile()`, `subprocess`, `socket` — these trigger static analysis failure.
- All file I/O must go through pandas (`pd.read_csv`, `pd.read_excel`, `df.to_csv`).
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


# ─── Consolidation column-mapping prompt ─────────────────────────────────────

def build_consolidation_prompt(
    file_schemas: list[dict],  # [{file_id, filename, columns: [str]}]
    purpose: str | None = None,
) -> str:
    """Ask the LLM to produce a unified column mapping across all cleaned files."""
    purpose_line = f"Job purpose: {purpose}\n" if purpose else ""

    files_section = ""
    for i, fs in enumerate(file_schemas, 1):
        cols = ", ".join(fs["columns"])
        files_section += f"File {i} — {fs['filename']} (id: {fs['file_id']}):\n  Columns: {cols}\n\n"

    return f"""{purpose_line}
You are a data integration expert. The following cleaned CSV files belong to the same job and need to be merged into a single unified table.

{files_section}
Your task:
1. Decide on a set of **canonical column names** that cover all meaningful columns across all files.
2. For each file, map its column names to the canonical names (or null if a column has no equivalent).

Rules:
- Use snake_case for all canonical column names.
- If the same data appears under different names across files (e.g. "vendor" vs "supplier_name"), unify them under one canonical name.
- If a column is unique to one file, still include it in the canonical set.
- Keep the order logical (identifiers first, then dates, amounts, then metadata).
- Do NOT invent columns that don't exist in the source files.

Respond with ONLY a valid JSON object in this exact format:
{{
  "canonical_columns": ["col_a", "col_b", ...],
  "file_mappings": {{
    "<file_id_1>": {{"source_col": "canonical_col", ...}},
    "<file_id_2>": {{"source_col": "canonical_col", ...}}
  }},
  "notes": "brief explanation of key decisions"
}}
"""


def parse_consolidation_mapping(text: str) -> dict:
    """Extract the JSON mapping from an LLM consolidation response."""
    # strip markdown fences
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    raw = m.group(1).strip() if m else text.strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # best-effort: find the first { ... }
        m2 = re.search(r"\{.*\}", raw, re.DOTALL)
        if m2:
            return json.loads(m2.group(0))
        raise
