from __future__ import annotations

import json
from dataclasses import dataclass
import hashlib
import random
from typing import Any, Dict, List

from pydantic import BaseModel, Field


class ColumnInference(BaseModel):
    source_name: str
    inferred_type: str = Field(description="string|number|date|boolean")
    suggested_name: str
    description: str
    confidence: float = Field(ge=0, le=1)


class SchemaInference(BaseModel):
    columns: List[ColumnInference]
    notes: str = ""


@dataclass
class LlmInferenceResult:
    raw_text: str
    parsed: Dict[str, Any]


def build_prompt(preview: Dict[str, Any], purpose: str | None = None) -> str:
    sampled_rows, stats_summary = summarize_preview(preview)
    prompt_preview = dict(preview)
    if sampled_rows is not None:
        prompt_preview["sample_rows"] = sampled_rows
    if stats_summary is not None:
        prompt_preview["summary"] = stats_summary
    purpose_line = (
        f"Business context: {purpose}\n"
        "Use this context to guide column name interpretation and type inference.\n\n"
        if purpose else ""
    )
    return (
        f"{purpose_line}"
        "You are a data analyst. Infer a clean schema for the uploaded dataset.\n"
        "Return ONLY valid JSON. No markdown, no explanations.\n"
        "Schema:\n"
        "{\n"
        '  "columns": [\n'
        "    {\n"
        '      "source_name": "string",\n'
        '      "inferred_type": "string|number|date|boolean",\n'
        '      "suggested_name": "string",\n'
        '      "description": "string",\n'
        '      "confidence": 0.0\n'
        "    }\n"
        "  ],\n"
        '  "notes": "string"\n'
        "}\n\n"
        "Confidence must be a number between 0 and 1.\n\n"
        f"Preview:\n{json.dumps(prompt_preview, ensure_ascii=False)}"
    )


def build_reflexion_prompt(preview: Dict[str, Any], error: str) -> str:
    return (
        "The previous JSON failed validation. Fix it.\n"
        "Return ONLY valid JSON following the schema and constraints.\n\n"
        f"Validation errors:\n{error}\n\n"
        f"Preview:\n{json.dumps(preview, ensure_ascii=False)}"
    )


def coerce_inference_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    if not isinstance(payload, dict):
        return {"columns": [], "notes": ""}
    payload = dict(payload)
    notes = payload.get("notes")
    if isinstance(notes, list):
        payload["notes"] = " ".join(str(item) for item in notes if item is not None).strip()
    elif notes is None:
        payload["notes"] = ""
    columns = payload.get("columns") or []
    if isinstance(columns, list):
        for column in columns:
            if not isinstance(column, dict):
                continue
            confidence = column.get("confidence")
            if isinstance(confidence, str):
                lowered = confidence.strip().lower()
                if lowered == "high":
                    column["confidence"] = 0.9
                elif lowered == "medium":
                    column["confidence"] = 0.6
                elif lowered == "low":
                    column["confidence"] = 0.3
    payload["columns"] = columns
    return payload


def summarize_preview(preview: Dict[str, Any]) -> tuple[List[Dict[str, Any]] | None, Dict[str, Any] | None]:
    columns = preview.get("columns")
    rows = preview.get("sample_rows")
    if not isinstance(columns, list) or not isinstance(rows, list):
        return None, None
    sampled_rows = sample_rows_with_kmeans(rows, max_rows=12)
    stats_summary = build_stats_summary(columns, rows)
    return sampled_rows, stats_summary


def sample_rows_with_kmeans(rows: List[Dict[str, Any]], max_rows: int = 12) -> List[Dict[str, Any]]:
    if len(rows) <= max_rows:
        return rows
    try:
        import numpy as np
        from sklearn.cluster import KMeans

        vectors = np.array([_row_to_vector(row) for row in rows], dtype=float)
        cluster_count = min(max_rows, max(2, len(rows) // 4))
        model = KMeans(n_clusters=cluster_count, random_state=42, n_init="auto")
        model.fit(vectors)
        centers = model.cluster_centers_
        labels = model.labels_
        selected_indices = []
        for cluster_id in range(cluster_count):
            members = np.where(labels == cluster_id)[0]
            if members.size == 0:
                continue
            member_vectors = vectors[members]
            distances = np.linalg.norm(member_vectors - centers[cluster_id], axis=1)
            best_idx = members[int(distances.argmin())]
            selected_indices.append(int(best_idx))
        selected_indices = selected_indices[:max_rows]
        return [rows[idx] for idx in selected_indices]
    except Exception:
        random.seed(42)
        return random.sample(rows, k=max_rows)


def build_stats_summary(columns: List[str], rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"row_count": len(rows), "columns": {}}
    for column in columns:
        values = [row.get(column) for row in rows]
        nulls = sum(1 for value in values if value is None or value == "")
        numeric_values = [value for value in values if isinstance(value, (int, float))]
        string_values = [value for value in values if isinstance(value, str)]
        col_summary: Dict[str, Any] = {
            "null_count": nulls,
            "sample_values": _unique_samples(string_values or numeric_values, limit=3),
        }
        if numeric_values:
            col_summary.update(
                {
                    "min": float(min(numeric_values)),
                    "max": float(max(numeric_values)),
                    "mean": float(sum(numeric_values) / len(numeric_values)),
                }
            )
        summary["columns"][str(column)] = col_summary
    return summary


def _row_to_vector(row: Dict[str, Any]) -> List[float]:
    vector: List[float] = []
    for key in sorted(row.keys()):
        value = row.get(key)
        if isinstance(value, bool):
            vector.append(1.0 if value else 0.0)
        elif isinstance(value, (int, float)):
            vector.append(float(value))
        elif value is None:
            vector.append(0.0)
        else:
            token = str(value)
            digest = hashlib.md5(token.encode("utf-8")).hexdigest()
            vector.append(int(digest[:6], 16) / float(0xFFFFFF))
    return vector


def _unique_samples(values: List[Any], limit: int = 3) -> List[Any]:
    seen = []
    for value in values:
        if value not in seen:
            seen.append(value)
        if len(seen) >= limit:
            break
    return seen


def parse_llm_json(text: str) -> Dict[str, Any]:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            return json.loads(text[start : end + 1])
        raise
