from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
import time


class Mode(str, Enum):
    LIVE = "live"
    READING = "reading"
    VOLUME_CATALOG = "volume_catalog"
    CHAPTER_CATALOG = "chapter_catalog"
    CLEANUP_REVIEW = "cleanup_review"
    MAINTENANCE = "maintenance"
    STATUS = "status"


class Action(str, Enum):
    NONE = "none"
    LIVE = "live"
    READING = "reading"
    CATALOG = "catalog"
    SELECT = "select"
    TOGGLE = "toggle"
    NEXT_PAGE = "next_page"
    PREVIOUS_PAGE = "previous_page"
    GOTO_PAGE = "goto_page"
    SEARCH = "search"
    NEXT_MATCH = "next_match"
    PREVIOUS_MATCH = "previous_match"
    CLEAR_SEARCH = "clear_search"
    NEXT_CHAPTER = "next_chapter"
    PREVIOUS_CHAPTER = "previous_chapter"
    GOTO_CHAPTER = "goto_chapter"
    STATUS = "status"
    CLEANUP = "cleanup"
    QUIT = "quit"


@dataclass(slots=True)
class CheckResult:
    title: str
    action: str
    lines: list[str]
    summary: str
    duration_ms: float = 0.0
    level: str = "ok"


@dataclass(slots=True)
class ActivityEvent:
    task_key: str
    category: str
    summary: str
    detail: str = ""
    level: str = "ok"
    completed_at: float = field(default_factory=time.time)


@dataclass(slots=True)
class CleanupCandidate:
    path: Path
    size: int
    mtime_ns: int


@dataclass(slots=True)
class CleanupItem:
    item_id: str
    label: str
    size: int
    risk: str
    description: str
    selectable: bool = True
    default_selected: bool = False
    root: Path | None = None
    candidates: tuple[CleanupCandidate, ...] = ()


@dataclass(slots=True)
class CleanupPlan:
    items: list[CleanupItem]
    scan_complete: bool
    created_at: float = field(default_factory=time.time)

    @property
    def selected_default_ids(self) -> set[str]:
        return {
            item.item_id
            for item in self.items
            if item.selectable and item.default_selected
        }


@dataclass(slots=True)
class AppState:
    mode: Mode = Mode.LIVE
    running: bool = True
    notice: str | None = None
