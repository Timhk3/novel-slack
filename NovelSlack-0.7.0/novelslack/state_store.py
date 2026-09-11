from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from .reader import TextReader
from .platforms import get_platform_adapter


def default_state_path() -> Path:
    return get_platform_adapter().state_dir() / "state.json"


def _key(path: str | Path) -> str:
    return os.path.normcase(str(Path(path).expanduser().resolve()))


class StateStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path else default_state_path()
        self.data: dict[str, Any] = {
            "version": 2,
            "last_book": None,
            "last_workspace": None,
            "page_size": 15,
            "books": {},
        }
        self.dirty = False
        self.last_flush = 0.0
        self._load()

    def _load(self) -> None:
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError):
            return
        if isinstance(loaded, dict):
            self.data.update(loaded)
        if not isinstance(self.data.get("books"), dict):
            self.data["books"] = {}

    @property
    def last_book(self) -> str | None:
        value = self.data.get("last_book")
        return value if isinstance(value, str) and value else None

    @property
    def last_workspace(self) -> str | None:
        value = self.data.get("last_workspace")
        return value if isinstance(value, str) and value else None

    @property
    def page_size(self) -> int:
        value = self.data.get("page_size", 15)
        return value if isinstance(value, int) and value > 0 else 15

    def set_workspace(self, path: Path) -> None:
        value = str(path.resolve())
        if self.data.get("last_workspace") != value:
            self.data["last_workspace"] = value
            self.dirty = True

    def set_page_size(self, page_size: int) -> None:
        page_size = max(1, int(page_size))
        if self.data.get("page_size") != page_size:
            self.data["page_size"] = page_size
            self.dirty = True

    def remember_reader(self, reader: TextReader) -> None:
        if reader.path is None:
            return

        chapter = reader.current_chapter
        volume = reader.current_volume
        record = {
            "path": str(reader.path),
            "line_index": reader.page_start,
            "total_lines": reader.total,
            "progress": (
                reader.page_start / max(reader.total - 1, 1)
                if reader.total
                else 0
            ),
            "signature": reader.signature,
            "chapter_number": chapter.number if chapter else None,
            "chapter_title": chapter.title if chapter else None,
            "volume_number": volume.number if volume else None,
        }

        self.data.setdefault("books", {})[_key(reader.path)] = record
        self.data["last_book"] = str(reader.path)
        self.dirty = True

    def resume_reader(self, reader: TextReader) -> str | None:
        if reader.path is None or reader.total == 0:
            return None

        record = self.data.get("books", {}).get(_key(reader.path))
        if not isinstance(record, dict):
            return None

        line_index = int(record.get("line_index", 0) or 0)

        if record.get("signature") and record.get("signature") == reader.signature:
            reader.jump_to_line(min(line_index, reader.total - 1))
            return "exact"

        chapter_number = record.get("chapter_number")
        if isinstance(chapter_number, int):
            candidates = [
                chapter
                for chapter in reader.chapters
                if chapter.number == chapter_number
            ]
            if candidates:
                progress = float(record.get("progress", 0) or 0)
                approximate_line = int(progress * max(reader.total - 1, 1))
                target = min(
                    candidates,
                    key=lambda chapter: abs(chapter.line_index - approximate_line),
                )
                reader.jump_to_line(target.line_index)
                return "chapter"

        progress = float(record.get("progress", 0) or 0)
        target = int(max(0.0, min(1.0, progress)) * max(reader.total - 1, 0))
        reader.jump_to_line(target)
        return "ratio"

    def flush(self, force: bool = False, min_interval: float = 3.0) -> bool:
        if not self.dirty:
            return False

        now = time.monotonic()
        if not force and now - self.last_flush < min_interval:
            return False

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.path.with_suffix(".tmp")
            temp.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            temp.replace(self.path)
        except OSError:
            return False

        self.last_flush = now
        self.dirty = False
        return True
