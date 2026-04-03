from __future__ import annotations

import mimetypes
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileType:
    kind: str
    mime: str


def detect_file_type(path: Path) -> FileType:
    mime, _ = mimetypes.guess_type(str(path))
    mime = mime or "application/octet-stream"
    suffix = path.suffix.lower()
    if suffix in {".csv"}:
        return FileType(kind="csv", mime=mime)
    if suffix in {".xls", ".xlsx"}:
        return FileType(kind="excel", mime=mime)
    if suffix in {".pdf"}:
        return FileType(kind="pdf", mime=mime)
    return FileType(kind="unknown", mime=mime)
