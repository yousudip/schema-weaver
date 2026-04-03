from __future__ import annotations

from typing import Any, Dict, Iterable, List

from openai import AzureOpenAI


def build_rich_representation(column: Dict[str, Any]) -> str:
    parts = [
        f"Column Header: {column.get('source_name', '')}",
        f"Suggested Name: {column.get('suggested_name', '')}",
        f"Inferred Type: {column.get('inferred_type', '')}",
        f"Description: {column.get('description', '')}",
    ]
    return " | ".join(part for part in parts if part.strip())


def embed_texts(
    client: AzureOpenAI, model: str, texts: Iterable[str]
) -> List[List[float]]:
    response = client.embeddings.create(model=model, input=list(texts))
    return [item.embedding for item in response.data]
