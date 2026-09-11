from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from pathlib import Path
import re

from .index_cache import TextIndexCache, content_signature


_CN_DIGITS = {
    "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}
_CN_UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}

_CHAPTER_RE = re.compile(
    r"^\s*第(?P<number>[0-9零〇一二三四五六七八九十百千万两]+)"
    r"(?P<kind>[章回])(?P<rest>[^\r\n]{0,70})\s*$"
)
_EN_CHAPTER_RE = re.compile(
    r"^\s*chapter\s+(?P<number>[0-9]+)\b(?P<rest>[^\r\n]{0,70})\s*$",
    re.IGNORECASE,
)
_VOLUME_RE = re.compile(
    r"^\s*第(?P<number>[0-9零〇一二三四五六七八九十百千万两]+)"
    r"(?P<kind>[卷部篇])(?P<rest>[^\r\n]{0,70})\s*$"
)
_EN_VOLUME_RE = re.compile(
    r"^\s*(?:book|part|volume)\s+(?P<number>[0-9]+)\b(?P<rest>[^\r\n]{0,70})\s*$",
    re.IGNORECASE,
)


_HEADING_STOP_RE = re.compile(r"[，。！？；：!?;:]")
_QUOTE_PAIRS = {
    "“": "”",
    "\"": "\"",
    "‘": "’",
    "'": "'",
}


def _clean_heading_title(raw: str, prefix_end: int) -> str:
    """
    Keep the real heading text but stop when the line turns into prose.

    Parenthetical suffixes such as （求月票） remain intact. Prose-like
    punctuation (，。！？；：) ends the title.
    """
    prefix = raw[:prefix_end].strip()
    rest = raw[prefix_end:].strip()
    rest = rest.lstrip("：:-—· ").strip()
    if not rest:
        return prefix

    # Preserve a short quoted title immediately after the prefix.
    if rest[0] in _QUOTE_PAIRS:
        closer = _QUOTE_PAIRS[rest[0]]
        close_at = rest.find(closer, 1)
        if 0 < close_at <= 32:
            quoted = rest[:close_at + 1]
            suffix = rest[close_at + 1:].lstrip()
            if not suffix or _HEADING_STOP_RE.match(suffix):
                return f"{prefix} {quoted}".strip()

    stop = _HEADING_STOP_RE.search(rest)
    if stop:
        rest = rest[:stop.start()].rstrip()

    # Do not hard-truncate chapter titles. The punctuation boundary above is
    # the title/prose delimiter; genuine long titles should remain complete.
    return f"{prefix} {rest}".strip()


def _looks_like_standalone_heading(raw: str, prefix_end: int) -> bool:
    rest = raw[prefix_end:].strip()
    rest = rest.lstrip("：:-—· ").strip()

    if len(raw.strip()) > 58:
        return False

    if not rest:
        return True

    # A sentence after the heading prefix is not a structural heading.
    if _HEADING_STOP_RE.search(rest):
        return False

    # Common prose connectors make false positives such as
    # "第六部的一个问题在于..." fail immediately.
    if rest.startswith(("的", "叫做", "是", "中", "里", "里面", "之后", "之前")):
        return False

    return len(rest) <= 28


def parse_chinese_number(value: str) -> int | None:
    value = value.strip()
    if not value:
        return None
    if value.isdigit():
        return int(value)
    if any(ch not in _CN_DIGITS and ch not in _CN_UNITS for ch in value):
        return None

    total = 0
    section = 0
    number = 0

    for ch in value:
        if ch in _CN_DIGITS:
            number = _CN_DIGITS[ch]
            continue

        unit = _CN_UNITS[ch]
        if unit == 10000:
            section += number
            total += section * unit
            section = 0
            number = 0
        else:
            if number == 0:
                number = 1
            section += number * unit
            number = 0

    return total + section + number


def parse_chapter_reference(value: str) -> int | None:
    raw = value.strip()
    if not raw:
        return None
    if raw.isdigit():
        return int(raw)

    match = re.fullmatch(
        r"第?([0-9零〇一二三四五六七八九十百千万两]+)(?:章|回)?",
        raw,
    )
    if match:
        return parse_chinese_number(match.group(1))

    match = re.fullmatch(r"chapter\s+([0-9]+)", raw, re.IGNORECASE)
    if match:
        return int(match.group(1))

    return parse_chinese_number(raw)


@dataclass(slots=True)
class ChapterEntry:
    title: str
    line_index: int
    number: int | None = None
    volume_index: int | None = None


@dataclass(slots=True)
class VolumeEntry:
    title: str
    line_index: int
    number: int | None = None
    chapter_indexes: tuple[int, ...] = ()


@dataclass
class SearchState:
    query: str = ""
    matches: list[int] = field(default_factory=list)
    selected: int = -1

    @property
    def active(self) -> bool:
        return bool(self.query and self.matches)

    @property
    def count(self) -> int:
        return len(self.matches)

    @property
    def current_line(self) -> int | None:
        if not self.active or self.selected < 0:
            return None
        return self.matches[self.selected]


@dataclass
class TextReader:
    page_size: int = 15
    path: Path | None = None
    lines: list[str] = field(default_factory=list)
    page_start: int = 0
    search_state: SearchState = field(default_factory=SearchState)
    chapters: list[ChapterEntry] = field(default_factory=list)
    volumes: list[VolumeEntry] = field(default_factory=list)
    toc_entries: list[ChapterEntry] = field(default_factory=list)
    catalog_source: str = "body index"
    signature: str | None = None
    index_cache_hit: bool = False
    _page_starts_cache: list[int] = field(default_factory=list, init=False, repr=False)
    _page_starts_cache_key: tuple | None = field(default=None, init=False, repr=False)

    def load(self, path: str | Path, cache: TextIndexCache | None = None) -> bool:
        source = Path(path).expanduser()
        if not source.exists() or not source.is_file():
            return False

        raw = source.read_bytes()
        decoded = None
        encoding_used = "utf-8"

        for encoding in ("utf-8-sig", "utf-8", "gb18030"):
            try:
                decoded = raw.decode(encoding)
                encoding_used = encoding
                break
            except UnicodeDecodeError:
                continue

        if decoded is None:
            decoded = raw.decode("utf-8", errors="replace")
            encoding_used = "utf-8-replace"

        self.path = source.resolve()
        self.lines = decoded.splitlines()
        self.page_start = 0
        self.clear_search()
        self.signature = content_signature(self.path, raw)
        self.index_cache_hit = False
        self._page_starts_cache = []
        self._page_starts_cache_key = None

        record = cache.get(self.path, self.signature) if cache else None
        if record and self._restore_index(record):
            self.index_cache_hit = True
            return True

        self._build_indexes()

        if cache:
            cache.put(
                self.path,
                {
                    "signature": self.signature,
                    "encoding": encoding_used,
                    "line_count": self.total,
                    "catalog_source": self.catalog_source,
                    "chapters": [
                        {
                            "title": c.title,
                            "line_index": c.line_index,
                            "number": c.number,
                            "volume_index": c.volume_index,
                        }
                        for c in self.chapters
                    ],
                    "volumes": [
                        {
                            "title": v.title,
                            "line_index": v.line_index,
                            "number": v.number,
                            "chapter_indexes": list(v.chapter_indexes),
                        }
                        for v in self.volumes
                    ],
                    "toc": [
                        {
                            "title": c.title,
                            "line_index": c.line_index,
                            "number": c.number,
                        }
                        for c in self.toc_entries
                    ],
                },
            )

        return True

    def _restore_index(self, record: dict) -> bool:
        try:
            if int(record.get("line_count", -1)) != self.total:
                return False

            self.catalog_source = str(record.get("catalog_source", "body index"))
            self.chapters = [
                ChapterEntry(
                    title=str(item["title"]),
                    line_index=int(item["line_index"]),
                    number=item.get("number"),
                    volume_index=item.get("volume_index"),
                )
                for item in record.get("chapters", [])
            ]
            self.volumes = [
                VolumeEntry(
                    title=str(item["title"]),
                    line_index=int(item["line_index"]),
                    number=item.get("number"),
                    chapter_indexes=tuple(int(x) for x in item.get("chapter_indexes", [])),
                )
                for item in record.get("volumes", [])
            ]
            self.toc_entries = [
                ChapterEntry(
                    title=str(item["title"]),
                    line_index=int(item["line_index"]),
                    number=item.get("number"),
                )
                for item in record.get("toc", [])
            ]
            return bool(self.chapters or self.total == 0)
        except (KeyError, TypeError, ValueError):
            return False

    def _chapter_candidates(self) -> list[ChapterEntry]:
        result: list[ChapterEntry] = []

        for index, line in enumerate(self.lines):
            stripped = line.strip()
            if not stripped or len(stripped) > 90:
                continue

            match = _CHAPTER_RE.match(stripped)
            if match:
                prefix_end = match.start("rest")
                title = _clean_heading_title(stripped, prefix_end)
                # Chapter detection remains permissive because real chapter
                # headings in TXT books often include parentheses / notes.
                if len(title) <= 72:
                    result.append(
                        ChapterEntry(
                            title,
                            index,
                            parse_chinese_number(match.group("number")),
                        )
                    )
                continue

            match = _EN_CHAPTER_RE.match(stripped)
            if match:
                prefix_end = match.start("rest")
                title = _clean_heading_title(stripped, prefix_end)
                result.append(
                    ChapterEntry(title, index, int(match.group("number")))
                )

        return result

    def _volume_candidates(self) -> list[VolumeEntry]:
        result: list[VolumeEntry] = []

        for index, line in enumerate(self.lines):
            stripped = line.strip()
            if not stripped or len(stripped) > 72:
                continue

            match = _VOLUME_RE.match(stripped)
            if match:
                prefix_end = match.start("rest")
                if not _looks_like_standalone_heading(stripped, prefix_end):
                    continue
                result.append(
                    VolumeEntry(
                        _clean_heading_title(stripped, prefix_end),
                        index,
                        parse_chinese_number(match.group("number")),
                    )
                )
                continue

            match = _EN_VOLUME_RE.match(stripped)
            if match:
                prefix_end = match.start("rest")
                if not _looks_like_standalone_heading(stripped, prefix_end):
                    continue
                result.append(
                    VolumeEntry(
                        _clean_heading_title(stripped, prefix_end),
                        index,
                        int(match.group("number")),
                    )
                )

        return result

    def _high_confidence_volumes(
        self,
        raw_volumes: list[VolumeEntry],
    ) -> list[VolumeEntry]:
        """
        Reject prose / author-note false positives.

        A real volume structure should have unique, increasing numbers and each
        retained volume should own a meaningful run of body chapters.
        """
        if len(raw_volumes) < 2:
            return []

        numbers = [v.number for v in raw_volumes]
        if any(number is None for number in numbers):
            return []

        numeric = [int(number) for number in numbers if number is not None]

        # Duplicate or backward numbering is a strong false-positive signal.
        if len(set(numeric)) != len(numeric):
            return []
        if any(b <= a for a, b in zip(numeric, numeric[1:])):
            return []

        # Missing too many sequence numbers means these are likely prose notes.
        gaps = sum(max(0, b - a - 1) for a, b in zip(numeric, numeric[1:]))
        if gaps > max(1, len(numeric) // 3):
            return []

        return raw_volumes

    def _build_indexes(self) -> None:
        raw = self._chapter_candidates()
        self.toc_entries = []
        self.catalog_source = "body index"

        if len(raw) >= 5:
            groups: list[list[ChapterEntry]] = []
            current = [raw[0]]

            for entry in raw[1:]:
                if entry.line_index - current[-1].line_index <= 3:
                    current.append(entry)
                else:
                    if len(current) >= 5:
                        groups.append(current)
                    current = [entry]

            if len(current) >= 5:
                groups.append(current)

            early_limit = min(max(5000, int(self.total * 0.12)), self.total)
            groups = [g for g in groups if g[0].line_index <= early_limit]

            if groups:
                toc = max(groups, key=len)
                self.toc_entries = toc
                toc_lines = {entry.line_index for entry in toc}
                raw = [entry for entry in raw if entry.line_index not in toc_lines]
                self.catalog_source = "detected TXT contents"

        if len(raw) >= 3:
            cleaned: list[ChapterEntry] = []
            for i, entry in enumerate(raw):
                prev_gap = entry.line_index - raw[i - 1].line_index if i else 10**9
                next_gap = (
                    raw[i + 1].line_index - entry.line_index
                    if i + 1 < len(raw)
                    else 10**9
                )
                if prev_gap > 3 and next_gap > 3:
                    cleaned.append(entry)
            if len(cleaned) >= max(3, len(raw) // 4):
                raw = cleaned

        self.chapters = raw
        raw_volumes = self._high_confidence_volumes(self._volume_candidates())

        if self.toc_entries and raw_volumes:
            toc_end = max(entry.line_index for entry in self.toc_entries)
            raw_volumes = [
                volume
                for volume in raw_volumes
                if volume.line_index > toc_end + 3
            ]

        volume_chapters: list[list[int]] = [[] for _ in raw_volumes]

        for chapter_index, chapter in enumerate(self.chapters):
            volume_index = None
            for index, volume in enumerate(raw_volumes):
                next_line = (
                    raw_volumes[index + 1].line_index
                    if index + 1 < len(raw_volumes)
                    else self.total + 1
                )
                if volume.line_index <= chapter.line_index < next_line:
                    volume_index = index
                    break

            chapter.volume_index = volume_index
            if volume_index is not None:
                volume_chapters[volume_index].append(chapter_index)

        kept: list[tuple[VolumeEntry, list[int]]] = [
            (raw_volumes[i], volume_chapters[i])
            for i in range(len(raw_volumes))
            if len(volume_chapters[i]) >= 2
        ]

        # If most candidate volumes do not actually own chapter runs, the
        # structure is unreliable; fall back to flat Chapter Catalog.
        if raw_volumes and len(kept) < max(2, len(raw_volumes) * 2 // 3):
            kept = []

        self.volumes = [
            VolumeEntry(
                title=volume.title,
                line_index=volume.line_index,
                number=volume.number,
                chapter_indexes=tuple(indexes),
            )
            for volume, indexes in kept
        ]

        if self.volumes:
            for chapter in self.chapters:
                chapter.volume_index = None
            for new_index, volume in enumerate(self.volumes):
                for chapter_index in volume.chapter_indexes:
                    if 0 <= chapter_index < len(self.chapters):
                        self.chapters[chapter_index].volume_index = new_index

    @property
    def total(self) -> int:
        return len(self.lines)

    def _page_starts(self) -> list[int]:
        """
        Build actual Reader pages with hard chapter boundaries.

        A chapter heading is always the first logical line of its page. A page
        at the end of one chapter never includes the next chapter heading.
        """
        key = (
            self.page_size,
            self.total,
            self.signature,
            len(self.chapters),
        )
        if self._page_starts_cache_key == key and self._page_starts_cache:
            return self._page_starts_cache

        if self.total <= 0:
            starts: list[int] = []
        elif not self.chapters:
            starts = list(range(0, self.total, self.page_size))
        else:
            starts = []

            first_chapter = self.chapters[0].line_index
            if first_chapter > 0:
                starts.extend(range(0, first_chapter, self.page_size))

            for index, chapter in enumerate(self.chapters):
                segment_start = chapter.line_index
                segment_end = (
                    self.chapters[index + 1].line_index
                    if index + 1 < len(self.chapters)
                    else self.total
                )
                if segment_end <= segment_start:
                    continue
                starts.extend(
                    range(segment_start, segment_end, self.page_size)
                )

            if not starts:
                starts = [0]

        self._page_starts_cache = starts
        self._page_starts_cache_key = key
        return starts

    @property
    def total_pages(self) -> int:
        return len(self._page_starts())

    @property
    def current_page(self) -> int:
        starts = self._page_starts()
        if not starts:
            return 0
        index = bisect_right(starts, self.page_start) - 1
        return max(0, index) + 1

    @property
    def page_end(self) -> int:
        starts = self._page_starts()
        if not starts:
            return 0

        next_index = bisect_right(starts, self.page_start)
        if next_index < len(starts):
            return min(starts[next_index], self.total)
        return self.total

    def _chapter_index_for_line(self, line_index: int) -> int | None:
        if not self.chapters:
            return None

        positions = [chapter.line_index for chapter in self.chapters]
        index = bisect_right(positions, line_index) - 1
        if index < 0:
            return None
        return index

    @property
    def current_chapter_index(self) -> int | None:
        index = self._chapter_index_for_line(self.page_start)
        return index + 1 if index is not None else None

    @property
    def current_chapter(self) -> ChapterEntry | None:
        index = self.current_chapter_index
        return self.chapters[index - 1] if index else None

    @property
    def current_volume_index(self) -> int | None:
        chapter = self.current_chapter
        return (
            chapter.volume_index + 1
            if chapter and chapter.volume_index is not None
            else None
        )

    @property
    def current_volume(self) -> VolumeEntry | None:
        index = self.current_volume_index
        return self.volumes[index - 1] if index else None

    def current_lines(self) -> list[str]:
        return self.lines[self.page_start:self.page_end]

    def next_page(self) -> None:
        starts = self._page_starts()
        if not starts:
            return

        current = bisect_right(starts, self.page_start) - 1
        if current + 1 < len(starts):
            self.page_start = starts[current + 1]
        else:
            self.page_start = starts[0]

    def previous_page(self) -> None:
        starts = self._page_starts()
        if not starts:
            return

        current = bisect_right(starts, self.page_start) - 1
        if current > 0:
            self.page_start = starts[current - 1]
        else:
            self.page_start = starts[-1]

    def jump_to_page(self, page: int) -> bool:
        starts = self._page_starts()
        if page < 1 or page > len(starts):
            return False
        self.page_start = starts[page - 1]
        return True

    def jump_to_line(self, line_index: int) -> bool:
        if line_index < 0 or line_index >= self.total:
            return False

        starts = self._page_starts()
        if not starts:
            return False

        index = bisect_right(starts, line_index) - 1
        self.page_start = starts[max(0, index)]
        return True

    def jump_to_chapter_index(self, index: int) -> bool:
        if index < 1 or index > len(self.chapters):
            return False

        # Chapter headings are explicit page starts by construction.
        self.page_start = self.chapters[index - 1].line_index
        return True

    def jump_to_chapter_reference(self, reference: str | int) -> bool:
        number = (
            reference
            if isinstance(reference, int)
            else parse_chapter_reference(reference)
        )
        if number is None:
            return False

        matching_indexes = [
            index
            for index, chapter in enumerate(self.chapters)
            if chapter.number == number
        ]

        if matching_indexes:
            current_line = self.page_start
            target_index = min(
                matching_indexes,
                key=lambda index: abs(
                    self.chapters[index].line_index - current_line
                ),
            )
            return self.jump_to_chapter_index(target_index + 1)

        return self.jump_to_chapter_index(number)

    def next_chapter(self) -> bool:
        index = self.current_chapter_index
        return bool(
            index
            and index < len(self.chapters)
            and self.jump_to_chapter_index(index + 1)
        )

    def previous_chapter(self) -> bool:
        index = self.current_chapter_index
        return bool(
            index
            and index > 1
            and self.jump_to_chapter_index(index - 1)
        )

    def clear_search(self) -> None:
        self.search_state = SearchState()

    def search(self, query: str) -> int:
        query = query.strip()
        if not query:
            self.clear_search()
            return 0

        needle = query.casefold()
        matches = [
            index
            for index, line in enumerate(self.lines)
            if needle in line.casefold()
        ]
        self.search_state = SearchState(query, matches, -1)

        if not matches:
            return 0

        selected = 0
        for idx, line_index in enumerate(matches):
            if line_index >= self.page_start:
                selected = idx
                break

        self.search_state.selected = selected
        self.jump_to_line(matches[selected])
        return len(matches)

    def next_match(self) -> bool:
        if not self.search_state.active:
            return False
        self.search_state.selected = (self.search_state.selected + 1) % len(self.search_state.matches)
        return self.jump_to_line(self.search_state.matches[self.search_state.selected])

    def previous_match(self) -> bool:
        if not self.search_state.active:
            return False
        self.search_state.selected = (self.search_state.selected - 1) % len(self.search_state.matches)
        return self.jump_to_line(self.search_state.matches[self.search_state.selected])

    def visible_match_lines(self) -> set[int]:
        if not self.search_state.active:
            return set()
        return {
            line_index
            for line_index in self.search_state.matches
            if self.page_start <= line_index < self.page_end
        }
