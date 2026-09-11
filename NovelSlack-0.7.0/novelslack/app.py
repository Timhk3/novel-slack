from __future__ import annotations

from collections import deque
import gc
import queue
import threading
import time
from pathlib import Path

from .activity import MaintenanceDashboardWorker
from .index_cache import TextIndexCache
from .input import Keyboard
from .maintenance import execute_cleanup
from .model import Action, ActivityEvent, AppState, CheckResult, Mode
from .reader import TextReader
from .state_store import StateStore
from .ui import ConsoleUI


class NovelSlackApp:
    INPUT_POLL = 0.035
    DASHBOARD_MIN_REFRESH = 0.50
    CATALOG_PAGE_SIZE = 18

    def __init__(
        self,
        workspace: Path,
        text_path: str | None = None,
        page_size: int = 15,
        store: StateStore | None = None,
        index_cache: TextIndexCache | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.state = AppState()
        self.keyboard = Keyboard()
        self.ui = ConsoleUI()
        self.preferred_page_size = max(6, page_size)
        self.reader = TextReader(page_size=self.preferred_page_size)
        self.store = store or StateStore()
        self.index_cache = index_cache or TextIndexCache()
        self.worker = MaintenanceDashboardWorker(self.workspace)
        self.activities: deque[ActivityEvent] = deque(maxlen=10)

        self.volume_cursor = 0
        self.chapter_indexes: list[int] = []
        self.chapter_cursor = 0
        self.cleanup_plan = None
        self.cleanup_cursor = 0
        self.cleanup_selected: set[str] = set()

        self.inline_prompt_kind: str | None = None
        self.inline_prompt_buffer = ""
        self.inline_prompt_origin: Mode | None = None

        self._maintenance_thread: threading.Thread | None = None
        self._maintenance_result: queue.Queue[CheckResult] = queue.Queue()
        self._dashboard_render_revision = -1
        self._activity_revision = 0
        self._last_activity_render_revision = -1
        self._last_dashboard_render = 0.0
        self._resume_notice: str | None = None

        self.store.set_workspace(self.workspace)
        self.store.set_page_size(self.preferred_page_size)

        if text_path and self.reader.load(text_path, self.index_cache):
            strategy = self.store.resume_reader(self.reader)
            if strategy:
                self._resume_notice = {
                    "exact": "Resumed exact saved position.",
                    "chapter": "Book changed; resumed from the matching chapter.",
                    "ratio": "Book changed; resumed from approximate reading progress.",
                }.get(strategy)
            self._save_reader()

    def run(self) -> None:
        self.keyboard.open()
        self.worker.start()
        self._transition(Mode.LIVE, force=True)

        try:
            while self.state.running:
                if self.inline_prompt_kind:
                    token = self.keyboard.poll_text()
                    if token:
                        self._handle_inline_prompt_token(token)
                else:
                    action = self.keyboard.poll()
                    if action is not Action.NONE:
                        self._handle(action)

                self._poll_maintenance_result()
                self.store.flush(force=False, min_interval=3.0)

                if self.ui.poll_resize():
                    self._handle_terminal_resize()

                if self.state.mode is Mode.LIVE:
                    self._update_dashboard_if_dirty()

                time.sleep(self.INPUT_POLL)

        except KeyboardInterrupt:
            pass
        finally:
            self._save_reader()
            self.store.flush(force=True)
            self.worker.stop()
            self.ui.stop()
            self.keyboard.close()
            gc.collect()

    def _handle_terminal_resize(self) -> None:
        """
        Rebuild the alternate-screen Live surface using the new terminal size.

        Reader page density is recalculated from current width/height so the
        rendered frame remains inside the viewport after a shrink.
        """
        self.ui.reset_surface_for_resize()

        if self.state.mode is Mode.READING:
            self._apply_responsive_reader_page_size()
            self._render_current()
            return

        if self.state.mode is Mode.LIVE:
            self._dashboard_render_revision = -1
            self._last_activity_render_revision = -1
            self._update_dashboard_if_dirty(force=True)
            return

        self._render_current()

    def _apply_responsive_reader_page_size(self) -> None:
        new_size = self.ui.recommended_reader_page_size(
            self.reader,
            self.preferred_page_size,
        )
        if new_size == self.reader.page_size:
            return

        # Preserve the current logical location, then re-align it to the new
        # chapter-bounded pagination grid. Chapter headings remain page starts.
        current_start = self.reader.page_start
        self.reader.page_size = new_size
        if self.reader.total:
            self.reader.jump_to_line(
                min(current_start, self.reader.total - 1)
            )

    def _transition(
        self,
        target: Mode,
        notice: str | None = None,
        force: bool = False,
    ) -> None:
        previous = self.state.mode

        if previous == target and not force:
            self.state.notice = notice
            self._render_current()
            return

        self._exit_mode(previous)
        if previous != target:
            self._clear_inline_prompt()
        self.state.mode = target
        self.state.notice = notice
        self._enter_mode(target)

    def _exit_mode(self, mode: Mode) -> None:
        if mode is Mode.READING:
            self._save_reader()
            gc.collect()

    def _enter_mode(self, mode: Mode) -> None:
        if mode is Mode.LIVE:
            self.worker.resume()
            self._dashboard_render_revision = -1
            self._last_activity_render_revision = -1
            self._update_dashboard_if_dirty(force=True)
        else:
            self.worker.pause()
            if mode is Mode.READING:
                self._apply_responsive_reader_page_size()
            self._render_current()

    def _render_current(self) -> None:
        mode = self.state.mode

        if mode is Mode.READING:
            self._apply_responsive_reader_page_size()
            notice = self.state.notice or self._resume_notice
            self._resume_notice = None
            self.ui.update(
                self.ui.reader(
                    self.reader,
                    notice,
                    self._prompt_label(),
                    self.inline_prompt_buffer,
                )
            )
        elif mode is Mode.VOLUME_CATALOG:
            self.ui.update(self.ui.volume_catalog(self.reader, self.volume_cursor))
        elif mode is Mode.CHAPTER_CATALOG:
            self.ui.update(
                self.ui.chapter_catalog(
                    self.reader,
                    self.chapter_indexes,
                    self.chapter_cursor,
                    self.CATALOG_PAGE_SIZE,
                    self._prompt_label(),
                    self.inline_prompt_buffer,
                )
            )
        elif mode is Mode.CLEANUP_REVIEW and self.cleanup_plan is not None:
            self.ui.update(
                self.ui.cleanup_review(
                    self.cleanup_plan,
                    self.cleanup_cursor,
                    self.cleanup_selected,
                )
            )
        elif mode is Mode.STATUS:
            self.ui.update(self.ui.status(self.worker.snapshot()))
        elif mode is Mode.MAINTENANCE:
            self.ui.update(
                self.ui.maintenance_result(
                    CheckResult(
                        "Maintenance",
                        "running",
                        ["status  running in background"],
                        "working",
                    )
                )
            )

    def _update_dashboard_if_dirty(self, force: bool = False) -> None:
        events = self.worker.drain_events()

        if events:
            self.activities.extend(events)
            self._activity_revision += len(events)

        snapshot = self.worker.snapshot()
        now = time.monotonic()

        dirty = (
            force
            or snapshot.revision != self._dashboard_render_revision
            or self._activity_revision != self._last_activity_render_revision
        )

        if not dirty:
            return

        if not force and now - self._last_dashboard_render < self.DASHBOARD_MIN_REFRESH:
            return

        self.ui.update(self.ui.dashboard(snapshot, list(self.activities)))
        self._dashboard_render_revision = snapshot.revision
        self._last_activity_render_revision = self._activity_revision
        self._last_dashboard_render = now

    def _handle(self, action: Action) -> None:
        if action is Action.QUIT:
            self.state.running = False
            return

        if action is Action.LIVE:
            self._transition(Mode.LIVE)
            return

        if action is Action.READING:
            self._transition(Mode.READING)
            return

        if action is Action.STATUS:
            self._transition(Mode.STATUS)
            return

        if action is Action.CLEANUP:
            self._open_cleanup_review()
            return

        mode = self.state.mode

        if mode is Mode.READING:
            self._handle_reader(action)
        elif mode is Mode.VOLUME_CATALOG:
            self._handle_volume_catalog(action)
        elif mode is Mode.CHAPTER_CATALOG:
            self._handle_chapter_catalog(action)
        elif mode is Mode.CLEANUP_REVIEW:
            self._handle_cleanup_review(action)

    def _handle_reader(self, action: Action) -> None:
        if action is Action.CATALOG:
            self._open_catalog()
            return

        if action in {Action.NEXT_PAGE, Action.TOGGLE}:
            self.reader.clear_search()
            self.reader.next_page()
            self._save_reader()
            self._render_current()
            return

        if action is Action.PREVIOUS_PAGE:
            self.reader.clear_search()
            self.reader.previous_page()
            self._save_reader()
            self._render_current()
            return

        if action is Action.NEXT_CHAPTER:
            self.reader.clear_search()
            if not self.reader.next_chapter():
                self.state.notice = "No later chapter detected."
            self._save_reader()
            self._render_current()
            return

        if action is Action.PREVIOUS_CHAPTER:
            self.reader.clear_search()
            if not self.reader.previous_chapter():
                self.state.notice = "No earlier chapter detected."
            self._save_reader()
            self._render_current()
            return

        if action is Action.NEXT_MATCH:
            if not self.reader.next_match():
                self.state.notice = "No active search."
            self._save_reader()
            self._render_current()
            return

        if action is Action.PREVIOUS_MATCH:
            if not self.reader.previous_match():
                self.state.notice = "No active search."
            self._save_reader()
            self._render_current()
            return

        if action is Action.CLEAR_SEARCH:
            self.reader.clear_search()
            self.state.notice = "Search cleared."
            self._render_current()
            return

        if action is Action.GOTO_PAGE:
            self._activate_inline_prompt("page")
            return

        if action is Action.GOTO_CHAPTER:
            self._activate_inline_prompt("chapter")
            return

        if action is Action.SEARCH:
            self._activate_inline_prompt("search")
            return

    def _prompt_label(self) -> str | None:
        return {
            "page": f"Go to page (1-{self.reader.total_pages})",
            "search": "Search text",
            "chapter": "Go to chapter",
        }.get(self.inline_prompt_kind or "")

    def _activate_inline_prompt(self, kind: str) -> None:
        self.inline_prompt_kind = kind
        self.inline_prompt_buffer = ""
        self.inline_prompt_origin = self.state.mode
        self.state.notice = None
        self._render_current()

    def _clear_inline_prompt(self) -> None:
        self.inline_prompt_kind = None
        self.inline_prompt_buffer = ""
        self.inline_prompt_origin = None

    def _handle_inline_prompt_token(self, token: str) -> None:
        if token == "\x1b":
            self._clear_inline_prompt()
            self.state.notice = None
            self._render_current()
            return

        if token == "__ENTER__":
            kind = self.inline_prompt_kind
            value = self.inline_prompt_buffer.strip()
            origin = self.inline_prompt_origin
            self._clear_inline_prompt()
            self._submit_inline_prompt(kind, value, origin)
            return

        if token in {"\x08", "\x7f"}:
            self.inline_prompt_buffer = self.inline_prompt_buffer[:-1]
            self._render_current()
            return

        if len(token) == 1 and token.isprintable():
            if len(self.inline_prompt_buffer) < 120:
                self.inline_prompt_buffer += token
                self._render_current()

    def _submit_inline_prompt(
        self,
        kind: str | None,
        value: str,
        origin: Mode | None,
    ) -> None:
        if not value:
            self.state.notice = None
            self._render_current()
            return

        if kind == "page":
            try:
                page = int(value)
            except ValueError:
                self.state.notice = f"Invalid page: {value}"
            else:
                self.reader.clear_search()
                if self.reader.jump_to_page(page):
                    self.state.notice = None
                    self._save_reader()
                else:
                    self.state.notice = "Page out of range."
            self._render_current()
            return

        if kind == "search":
            count = self.reader.search(value)
            self.state.notice = (
                f"{count} matches found."
                if count
                else f'No matches for "{value}".'
            )
            self._save_reader()
            self._render_current()
            return

        if kind == "chapter":
            self.reader.clear_search()
            if self.reader.jump_to_chapter_reference(value):
                self.state.notice = None
                self._save_reader()
                if origin is Mode.CHAPTER_CATALOG:
                    self._transition(Mode.READING)
                else:
                    self._render_current()
            else:
                self.state.notice = f"Chapter not found: {value}"
                self._render_current()

    def _save_reader(self) -> None:
        self.store.remember_reader(self.reader)

    def _open_catalog(self) -> None:
        if not self.reader.chapters:
            self._transition(Mode.READING, "No chapter headings detected.")
            return

        if self.reader.volumes:
            current = self.reader.current_volume_index or 1
            self.volume_cursor = max(0, current - 1)
            self._transition(Mode.VOLUME_CATALOG)
        else:
            self.chapter_indexes = list(range(len(self.reader.chapters)))
            current = self.reader.current_chapter_index or 1
            self.chapter_cursor = max(0, current - 1)
            self._transition(Mode.CHAPTER_CATALOG)

    def _handle_volume_catalog(self, action: Action) -> None:
        count = len(self.reader.volumes)

        if action is Action.NEXT_CHAPTER:
            self.volume_cursor = min(count - 1, self.volume_cursor + 1)
            self._render_current()
        elif action is Action.PREVIOUS_CHAPTER:
            self.volume_cursor = max(0, self.volume_cursor - 1)
            self._render_current()
        elif action is Action.SELECT:
            volume = self.reader.volumes[self.volume_cursor]
            self.chapter_indexes = list(volume.chapter_indexes)
            current = (self.reader.current_chapter_index or 1) - 1
            try:
                self.chapter_cursor = self.chapter_indexes.index(current)
            except ValueError:
                self.chapter_cursor = 0
            self._transition(Mode.CHAPTER_CATALOG)

    def _handle_chapter_catalog(self, action: Action) -> None:
        count = len(self.chapter_indexes)

        if action is Action.NEXT_CHAPTER:
            self.chapter_cursor = min(count - 1, self.chapter_cursor + 1)
            self._render_current()
        elif action is Action.PREVIOUS_CHAPTER:
            self.chapter_cursor = max(0, self.chapter_cursor - 1)
            self._render_current()
        elif action is Action.NEXT_PAGE:
            step = self.ui.recommended_catalog_page_size(self.CATALOG_PAGE_SIZE)
            self.chapter_cursor = min(
                count - 1,
                self.chapter_cursor + step,
            )
            self._render_current()
        elif action is Action.PREVIOUS_PAGE:
            step = self.ui.recommended_catalog_page_size(self.CATALOG_PAGE_SIZE)
            self.chapter_cursor = max(
                0,
                self.chapter_cursor - step,
            )
            self._render_current()
        elif action is Action.SELECT:
            chapter_index = self.chapter_indexes[self.chapter_cursor]
            self.reader.jump_to_chapter_index(chapter_index + 1)
            self._save_reader()
            self._transition(Mode.READING)
        elif action is Action.CATALOG and self.reader.volumes:
            self._transition(Mode.VOLUME_CATALOG)
        elif action is Action.GOTO_CHAPTER:
            self._activate_inline_prompt("chapter")

    def _open_cleanup_review(self) -> None:
        self.cleanup_plan = self.worker.cleanup_plan()
        self.cleanup_cursor = 0
        self.cleanup_selected = self.cleanup_plan.selected_default_ids
        self._transition(Mode.CLEANUP_REVIEW)

    def _handle_cleanup_review(self, action: Action) -> None:
        if self.cleanup_plan is None:
            self._transition(Mode.LIVE)
            return

        count = len(self.cleanup_plan.items)

        if action is Action.NEXT_CHAPTER:
            self.cleanup_cursor = min(count - 1, self.cleanup_cursor + 1)
            self._render_current()
        elif action is Action.PREVIOUS_CHAPTER:
            self.cleanup_cursor = max(0, self.cleanup_cursor - 1)
            self._render_current()
        elif action is Action.TOGGLE:
            item = self.cleanup_plan.items[self.cleanup_cursor]
            if item.selectable:
                if item.item_id in self.cleanup_selected:
                    self.cleanup_selected.remove(item.item_id)
                else:
                    self.cleanup_selected.add(item.item_id)
            self._render_current()
        elif action is Action.SELECT:
            if not self.cleanup_selected:
                self.state.notice = "Nothing selected."
                self._render_current()
                return
            self._start_cleanup()

    def _start_cleanup(self) -> None:
        plan = self.cleanup_plan
        selected = set(self.cleanup_selected)

        if plan is None:
            return

        self._transition(Mode.MAINTENANCE)

        def run() -> None:
            try:
                result = execute_cleanup(plan, selected, self.worker.adapter)
            except Exception as exc:
                result = CheckResult(
                    "Cleanup Failed",
                    "exception",
                    [f"error  {type(exc).__name__}: {exc}"],
                    "cleanup failed safely",
                    0,
                    "warn",
                )
            self._maintenance_result.put(result)

        self._maintenance_thread = threading.Thread(
            target=run,
            name="NovelSlackCleanup",
            daemon=True,
        )
        self._maintenance_thread.start()

    def _poll_maintenance_result(self) -> None:
        try:
            result = self._maintenance_result.get_nowait()
        except queue.Empty:
            return

        self.worker.invalidate_storage()
        self.activities.append(
            ActivityEvent(
                "cleanup_result",
                "cleanup",
                result.summary,
                "validated plan execution",
            )
        )
        self._activity_revision += 1

        if self.state.mode is Mode.MAINTENANCE:
            self.ui.update(self.ui.maintenance_result(result))
