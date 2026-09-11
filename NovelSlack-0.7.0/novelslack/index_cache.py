from __future__ import annotations

import hashlib
import os
import json
from pathlib import Path
from typing import Any

from .platforms import get_platform_adapter

INDEX_SCHEMA_VERSION = 2


def default_cache_path() -> Path:
    return get_platform_adapter().app_cache_dir() / "index-cache.json"


def content_signature(path: Path, raw: bytes | None = None) -> str:
    source = path.expanduser().resolve()
    stat = source.stat()

    if raw is None:
        with source.open("rb") as handle:
            head = handle.read(64 * 1024)
            if stat.st_size > 64 * 1024:
                handle.seek(max(0, stat.st_size - 64 * 1024))
                tail = handle.read(64 * 1024)
            else:
                tail = b""
    else:
        head = raw[:64 * 1024]
        tail = raw[-64 * 1024:] if len(raw) > 64 * 1024 else b""

    digest = hashlib.sha256()
    digest.update(str(stat.st_size).encode())
    digest.update(b"|")
    digest.update(str(stat.st_mtime_ns).encode())
    digest.update(b"|")
    digest.update(head)
    digest.update(b"|")
    digest.update(tail)
    return digest.hexdigest()


class TextIndexCache:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_cache_path()
        self.data: dict[str, Any] = {"version": INDEX_SCHEMA_VERSION, "books": {}}
        self._load()

    def _load(self) -> None:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return
        if (
            isinstance(loaded, dict)
            and loaded.get("version") == INDEX_SCHEMA_VERSION
            and isinstance(loaded.get("books"), dict)
        ):
            self.data = loaded

    def _key(self, path: Path) -> str:
        return os.path.normcase(str(path.expanduser().resolve()))

    def get(self, path: Path, signature: str) -> dict[str, Any] | None:
        record = self.data.get("books", {}).get(self._key(path))
        if not isinstance(record, dict) or record.get("signature") != signature:
            return None
        return record

    def put(self, path: Path, record: dict[str, Any]) -> None:
        self.data.setdefault("books", {})[self._key(path)] = record
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp.replace(self.path)
        except OSError:
            pass
