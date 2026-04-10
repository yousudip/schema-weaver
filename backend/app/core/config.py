from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

def _project_root() -> Path:
    try:
        return Path(__file__).resolve().parents[3]
    except IndexError:
        return Path.cwd()


@dataclass(frozen=True)
class Settings:
    local_storage_dir: Path
    database_url: str
    openai_endpoint: str
    openai_api_key: str
    openai_deployment_gpt5: str
    openai_deployment_gpt5_mini: str
    openai_deployment_embeddings: str
    sandbox_image: str
    sandbox_cpu: float
    sandbox_memory_mb: int
    tesseract_cmd: str
    poppler_path: str
    cors_origins: list[str]


def get_settings() -> Settings:
    load_dotenv()
    root = _project_root()
    raw_dir = os.getenv("LOCAL_STORAGE_DIR", "storage")
    storage_dir = Path(raw_dir)
    if not storage_dir.is_absolute():
        storage_dir = root / storage_dir
    database_url = os.getenv("DATABASE_URL", "").strip()
    endpoint = os.getenv("OPENAI_ENDPOINT", "").strip()
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    gpt5 = os.getenv("OPENAI_DEPLOYMENT_GPT5", "").strip()
    gpt5_mini = os.getenv("OPENAI_DEPLOYMENT_GPT5_MINI", "").strip()
    embeddings = os.getenv("OPENAI_DEPLOYMENT_EMBEDDINGS", "").strip()
    sandbox_image = os.getenv("SANDBOX_IMAGE", "gdc-sandbox:local").strip()
    sandbox_cpu = float(os.getenv("SANDBOX_CPU", "1"))
    sandbox_memory_mb = int(os.getenv("SANDBOX_MEMORY_MB", "512"))
    tesseract_cmd = os.getenv("TESSERACT_CMD", "").strip()
    poppler_path = os.getenv("POPPLER_PATH", "").strip()
    cors_raw = os.getenv("CORS_ORIGINS", "http://localhost:5173").strip()
    cors_origins = [origin.strip() for origin in cors_raw.split(",") if origin.strip()]

    # Normalize endpoint if a full path was provided.
    if endpoint and "/openai/" in endpoint:
        parsed = urlparse(endpoint)
        endpoint = f"{parsed.scheme}://{parsed.netloc}"

    return Settings(
        local_storage_dir=storage_dir,
        database_url=database_url,
        openai_endpoint=endpoint,
        openai_api_key=api_key,
        openai_deployment_gpt5=gpt5,
        openai_deployment_gpt5_mini=gpt5_mini,
        openai_deployment_embeddings=embeddings,
        sandbox_image=sandbox_image,
        sandbox_cpu=sandbox_cpu,
        sandbox_memory_mb=sandbox_memory_mb,
        tesseract_cmd=tesseract_cmd,
        poppler_path=poppler_path,
        cors_origins=cors_origins,
    )
