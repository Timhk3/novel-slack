from __future__ import annotations

import re
import time

from rich.console import Console, Group
from rich.cells import cell_len
from rich.control import Control
from rich.live import Live
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from .activity import StreamSnapshot, format_bytes
from .model import ActivityEvent, CheckResult, CleanupPlan
from .reader import TextReader


class ConsoleUI:
    """Single alternate-screen surface for every mode."""

    def __init__(self) -> None:
        self.console = Console()
        self.live: Live | None = None
        size = self.console.size
        self._terminal_size = (size.width, size.height)

    def start(self, renderable) -> None:
        if self.live is None:
            self.live = Live(
                renderable,
                console=self.console,
                screen=True,
                auto_refresh=False,
                refresh_per_second=4,
                transient=False,
                vertical_overflow="crop",
            )
            # Enter the alternate screen first, then explicitly clear/home
            # that buffer. This prevents stale rows from an older viewport
            # reappearing after Windows Terminal is resized.
            self.live.start(refresh=False)
            self.console.control(Control.clear(), Control.home())
            self.live.refresh()
        else:
            self.live.update(renderable, refresh=True)

    def update(self, renderable) -> None:
        if self.live is None:
            self.start(renderable)
        else:
            self.live.update(renderable, refresh=True)

    def stop(self) -> None:
        if self.live is not None:
            self.live.stop()
            self.live = None

    @property
    def terminal_width(self) -> int:
        return max(20, int(self.console.size.width))

    @property
    def terminal_height(self) -> int:
        return max(10, int(self.console.size.height))

    def poll_resize(self) -> bool:
        """
        Return True once for each terminal width/height change.

        Live's internal cursor region is tied to the previous terminal height.
        Rebuilding the alternate-screen surface on resize avoids stale rows
        being left above/below the current frame.
        """
        size = self.console.size
        current = (size.width, size.height)
        if current == self._terminal_size:
            return False
        self._terminal_size = current
        return True

    def reset_surface_for_resize(self) -> None:
        """
        Dispose the old Live region before rendering against the new viewport.

        Resize is infrequent, so a hard surface rebuild is preferable to
        retaining stale cursor geometry from the old terminal size.
        """
        if self.live is not None:
            self.live.stop()
            self.live = None

    def recommended_catalog_page_size(self, preferred: int = 18) -> int:
        return max(4, min(int(preferred), self.terminal_height - 8))

    def recommended_reader_page_size(
        self,
        reader: TextReader,
        preferred_lines: int,
        extra_reserved_rows: int = 0,
    ) -> int:
        """
        Compute a logical-line page size that fits the current terminal.

        Chinese/full-width text can consume two cells per character. We use
        Rich's cell_len() so wrapped terminal rows, rather than Python string
        length, determine how many source lines can safely fit.
        """
        preferred = max(2, int(preferred_lines))
        width = self.terminal_width
        height = self.terminal_height

        # Reader panel + footer + breathing room.
        available_rows = max(2, height - 11 - max(0, extra_reserved_rows))
        body_width = max(24, width - 6)

        if reader.total == 0:
            return min(preferred, max(2, available_rows))

        start = min(max(reader.page_start, 0), max(reader.total - 1, 0))
        sample = reader.lines[start:start + preferred]
        if not sample:
            return min(preferred, max(2, available_rows))

        used = 0
        count = 0

        for line in sample:
            cells = max(1, cell_len(line))
            wrapped_rows = max(1, (cells + body_width - 1) // body_width)

            # Leave one row of slack to absorb borders/wrapping differences.
            if count > 0 and used + wrapped_rows > max(3, available_rows - 1):
                break

            used += wrapped_rows
            count += 1

            if count >= preferred:
                break

        return max(2, min(preferred, count or 2))

    def prompt(self, keyboard, prompt: str) -> str:
        self.stop()
        self.console.clear()
        return keyboard.read_line(prompt)

    def dashboard(
        self,
        snapshot: StreamSnapshot,
        activities: list[ActivityEvent],
    ):
        header = Text("NovelSlack · System Maintenance Dashboard", style="bold cyan")

        snap = Table.grid(expand=True, padding=(0, 2))
        for _ in range(4):
            snap.add_column()

        snap.add_row(
            "CPU",
            f"{snapshot.cpu_load:.0f}%" if snapshot.cpu_load is not None else "-",
            "Memory",
            f"{snapshot.memory_load}%" if snapshot.memory_load is not None else "-",
        )
        snap.add_row(
            "Disk free",
            format_bytes(snapshot.disk_free),
            "Process",
            str(snapshot.process_count) if snapshot.process_count is not None else "-",
        )
        snap.add_row(
            snapshot.trash_label,
            format_bytes(snapshot.trash_bytes),
            "Safe reclaim",
            format_bytes(snapshot.safe_reclaim),
        )
        snap.add_row(
            "Reviewable",
            format_bytes(snapshot.reviewable),
            "Disk trend",
            f"{'+' if snapshot.disk_delta >= 0 else '-'}{format_bytes(abs(snapshot.disk_delta))}",
        )

        current = Table.grid(expand=True, padding=(0, 2))
        for _ in range(4):
            current.add_column()

        current.add_row(
            "task", snapshot.current_task,
            "state", snapshot.current_state,
        )
        current.add_row(
            "entries", str(snapshot.current_entries),
            "files", str(snapshot.current_files),
        )
        current.add_row(
            "indexed", format_bytes(snapshot.current_bytes),
            "cycle", str(snapshot.current_cycle),
        )

        history = Table(
            title="MAINTENANCE ACTIVITY · grouped completed analyses",
            box=None,
            expand=True,
            padding=(0, 1),
        )
        history.add_column("time", width=9)
        history.add_column("task", width=16)
        history.add_column("result", ratio=2, no_wrap=True, overflow="ellipsis")
        history.add_column("detail", ratio=3, no_wrap=True, overflow="ellipsis")

        max_history_rows = max(2, min(10, self.terminal_height - 17))

        if activities:
            for event in activities[-max_history_rows:]:
                history.add_row(
                    time.strftime("%H:%M:%S", time.localtime(event.completed_at)),
                    event.category,
                    event.summary,
                    event.detail,
                )
        else:
            history.add_row("-", "initializing", "first analyses pending", "")

        footer = Text(
            "[I] status  [C] cleanup review  [R] reader  [Q] quit",
            style="bright_black",
        )

        return Group(
            header,
            Panel(snap, title="SYSTEM SNAPSHOT · dirty-rendered", border_style="cyan"),
            Panel(current, title="CURRENT MAINTENANCE · live progress", border_style="blue"),
            history,
            footer,
        )

    def reader(
        self,
        reader: TextReader,
        notice: str | None = None,
        prompt_label: str | None = None,
        prompt_buffer: str = "",
    ):
        header = Table.grid(expand=True, padding=(0, 2))
        header.add_column()
        header.add_column()

        name = reader.path.name if reader.path else "No TXT"
        header.add_row("NovelSlack Reader", name)
        header.add_row(
            "page",
            f"{reader.current_page}/{reader.total_pages} · "
            f"lines {reader.page_start + 1}-{reader.page_end}/{reader.total}",
        )

        chapter = reader.current_chapter
        volume = reader.current_volume

        if volume:
            header.add_row("volume", volume.title)
        if chapter:
            header.add_row(
                "chapter",
                f"{chapter.number if chapter.number is not None else '?'} · {chapter.title}",
            )

        if reader.search_state.query:
            header.add_row(
                "search",
                f"{reader.search_state.query} · "
                f"{reader.search_state.selected + 1}/{reader.search_state.count}",
            )

        body: list[Text] = []

        if notice:
            body.append(Text(notice, style="yellow"))

        if reader.path is None:
            body.append(Text("No TXT attached.", style="dim"))
        else:
            visible = reader.visible_match_lines()
            selected = reader.search_state.current_line

            for offset, line in enumerate(reader.current_lines()):
                absolute = reader.page_start + offset
                row = Text("│ ", style="bright_black")

                if absolute in visible and reader.search_state.query:
                    pattern = re.compile(
                        re.escape(reader.search_state.query),
                        re.IGNORECASE,
                    )
                    cursor = 0
                    for match in pattern.finditer(line):
                        row.append(line[cursor:match.start()], style="dim")
                        row.append(
                            line[match.start():match.end()],
                            style=(
                                "bold black on yellow"
                                if absolute == selected
                                else "bold yellow"
                            ),
                        )
                        cursor = match.end()
                    row.append(line[cursor:], style="dim")
                else:
                    row.append(line, style="dim")

                body.append(row)

        prompt = None
        if prompt_label:
            prompt = Text()
            prompt.append(f"{prompt_label} > ", style="bold cyan")
            prompt.append(prompt_buffer)
            prompt.append("█", style="bold")
            prompt.append("   [Enter] submit  [Esc] cancel", style="bright_black")

        footer = Text(style="bright_black")
        footer.append("[A] prev  [D/SPACE] next  [G] page  [/] search  ")
        footer.append("[N/P] matches  [X/ESC] clear\n")
        footer.append("[[] prev chapter  []] next chapter  [T] chapter  ")
        footer.append("[O] catalog  [W] dashboard  [Q] quit")

        parts = [Panel(header, border_style="cyan"), *body]
        # While typing, replace the normal shortcut footer with the input line.
        # This keeps page density and page numbering stable.
        parts.append(prompt if prompt is not None else footer)
        return Group(*parts)

    def volume_catalog(
        self,
        reader: TextReader,
        selected: int,
    ):
        table = Table.grid(expand=False, padding=(0, 1))
        table.add_column(width=2)
        table.add_column(width=7, justify="right", style="cyan")
        table.add_column()

        visible_rows = max(4, self.terminal_height - 8)
        start = max(0, selected - visible_rows // 2)
        end = min(len(reader.volumes), start + visible_rows)
        start = max(0, end - visible_rows)

        for index in range(start, end):
            volume = reader.volumes[index]
            chosen = index == selected
            table.add_row(
                Text("▶" if chosen else " ", style="bold green" if chosen else "dim"),
                str(volume.number if volume.number is not None else index + 1),
                Text(volume.title, style="reverse" if chosen else None),
            )

        footer = Text(
            "[[] previous volume  []] next volume  [Enter] chapters  "
            "[R] reader  [W] dashboard  [Q] quit",
            style="bright_black",
        )

        return Group(
            Panel(
                f"{len(reader.volumes)} detected volumes",
                title="Volume Catalog",
                border_style="cyan",
            ),
            table,
            footer,
        )

    def chapter_catalog(
        self,
        reader: TextReader,
        indexes: list[int],
        selected_position: int,
        page_size: int = 18,
        prompt_label: str | None = None,
        prompt_buffer: str = "",
    ):
        selected_position = max(0, min(selected_position, max(len(indexes) - 1, 0)))
        effective_page_size = self.recommended_catalog_page_size(page_size)
        page = selected_position // effective_page_size
        start = page * effective_page_size
        end = min(start + effective_page_size, len(indexes))

        table = Table.grid(expand=False, padding=(0, 1))
        table.add_column(width=2)
        table.add_column(width=7, justify="right", style="cyan")
        table.add_column()

        for position in range(start, end):
            chapter_index = indexes[position]
            chapter = reader.chapters[chapter_index]
            chosen = position == selected_position

            table.add_row(
                Text("▶" if chosen else " ", style="bold green" if chosen else "dim"),
                str(chapter.number if chapter.number is not None else chapter_index + 1),
                Text(chapter.title, style="reverse" if chosen else None),
            )

        prompt = None
        if prompt_label:
            prompt = Text()
            prompt.append(f"{prompt_label} > ", style="bold cyan")
            prompt.append(prompt_buffer)
            prompt.append("█", style="bold")
            prompt.append("   [Enter] submit  [Esc] cancel", style="bright_black")

        footer = Text(
            "[[] previous  []] next  [Enter] open  [A/D] page  "
            "[O] volumes  [T] type chapter  [R] reader  [W] dashboard",
            style="bright_black",
        )

        parts = [
            Panel(
                f"{len(indexes)} chapters · page {page + 1}/{max(1, (len(indexes)+effective_page_size-1)//effective_page_size)}",
                title="Chapter Catalog",
                border_style="cyan",
            ),
            table,
        ]
        parts.append(prompt if prompt is not None else footer)
        return Group(*parts)

    def cleanup_review(
        self,
        plan: CleanupPlan,
        cursor: int,
        selected_ids: set[str],
    ):
        table = Table(
            title="Cleanup Review",
            box=None,
            expand=True,
            padding=(0, 1),
        )
        table.add_column("", width=2)
        table.add_column("", width=3)
        table.add_column("item", width=28)
        table.add_column("size", width=12)
        table.add_column("risk", width=12)
        table.add_column("scope", no_wrap=True, overflow="ellipsis")

        for index, item in enumerate(plan.items):
            cursor_mark = "▶" if index == cursor else " "
            if not item.selectable:
                check = "-"
            else:
                check = "x" if item.item_id in selected_ids else " "

            table.add_row(
                Text(cursor_mark, style="bold green" if index == cursor else "dim"),
                Text(f"[{check}]"),
                item.label,
                format_bytes(item.size),
                item.risk,
                item.description,
            )

        selected_total = sum(
            item.size
            for item in plan.items
            if item.item_id in selected_ids
        )

        note = (
            f"Selected estimate: {format_bytes(selected_total)} · "
            f"scan {'complete' if plan.scan_complete else 'still in progress / partial'}"
        )

        footer = Text(
            "[[] previous  []] next  [Space] toggle  [Enter] clean selected  "
            "[W] cancel/dashboard",
            style="bright_black",
        )

        return Group(
            Panel(note, title="Cleanup Plan", border_style="cyan"),
            table,
            footer,
        )

    def maintenance_result(self, result: CheckResult):
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bright_black")
        table.add_column()

        for line in result.lines:
            if "  " in line:
                key, value = line.split("  ", 1)
                table.add_row(key.strip(), value.strip())
            else:
                table.add_row("", line)

        table.add_row("result", result.summary)
        table.add_row("duration", f"{result.duration_ms:.1f} ms")

        return Group(
            Panel(table, title=result.title, border_style="green"),
            Text("[W] dashboard  [R] reader  [Q] quit", style="bright_black"),
        )

    def status(self, snapshot: StreamSnapshot):
        table = Table.grid(padding=(0, 2))
        table.add_column(style="bright_black")
        table.add_column()

        table.add_row("CPU", f"{snapshot.cpu_load:.0f}%" if snapshot.cpu_load is not None else "-")
        table.add_row("Memory", f"{snapshot.memory_load}%" if snapshot.memory_load is not None else "-")
        table.add_row("Available RAM", format_bytes(snapshot.memory_available))
        table.add_row("Disk free", format_bytes(snapshot.disk_free))
        table.add_row("Processes", str(snapshot.process_count or "-"))
        table.add_row("Safe reclaim", format_bytes(snapshot.safe_reclaim))
        table.add_row("Reviewable", format_bytes(snapshot.reviewable))

        return Group(
            Panel(table, title="System Status", border_style="cyan"),
            Text("[W] dashboard  [C] cleanup review  [R] reader", style="bright_black"),
        )
