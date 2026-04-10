from __future__ import annotations

from openai import AzureOpenAI

from backend.app.core.config import Settings


def create_azure_openai_client(settings: Settings) -> AzureOpenAI:
    if not settings.openai_endpoint or not settings.openai_api_key:
        raise RuntimeError("OpenAI configuration is missing.")
    return AzureOpenAI(
        azure_endpoint=settings.openai_endpoint,
        api_key=settings.openai_api_key,
        api_version="2025-04-01-preview",
    )
