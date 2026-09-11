from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import os
from pathlib import Path
import queue
import shutil
import threading
import time
from typing import Callable, Iterator

from .model import (
    ActivityEvent,
    CleanupCandidate,
    CleanupItem,
    CleanupPlan,
)
from .platforms import (
    PlatformAdapter,
    get_platform_adapter,
)


CACHE_DIR_NAMES = {
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
}


def format_bytes(value: int | None) -> str:
    if value is None:
        return "-"
    value = max(0, int(value))
    if value >= 1024**3:
        return f"{value / (1024**3):.2f} GiB"
    if value >= 1024**2:
        return f"{value / (1024**2):.1f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"


@dataclass(slots=True)
class StreamSnapshot:
    platform_name: str = ""
    trash_label: str = "Trash"
    cpu_load: float | None = None
    memory_load: int | None = None
    memory_available: int | None = None
    disk_free: int | None = None
    disk_delta: int = 0
    process_count: int | None = None
    trash_bytes: int | None = None
    trash_items: int | None = None
    safe_reclaim: int = 0
    reviewable: int = 0
    current_task: str = "initializing"
    current_entries: int = 0
    current_files: int = 0
    current_bytes: int = 0
    current_cycle: int = 1
    current_state: str = "starting"
    revision: int = 0


class DirectoryScanJob:
    def __init__(
        self,
        key: str,
        label: str,
        root: Path,
        *,
        old_days: int | None = None,
        collect_candidates: bool = False,
        candidate_filter: Callable[[os.stat_result], bool] | None = None,
        max_depth: int = 12,
    ) -> None:
        self.key = key
        self.label = label
        self.root = root
        self.old_days = old_days
        self.collect_candidates = collect_candidates
        self.candidate_filter = candidate_filter
        self.max_depth = max_depth
        self.reset()

    def reset(self) -> None:
        self.entries = 0
        self.files = 0
        self.total_bytes = 0
        self.candidate_files = 0
        self.candidate_bytes = 0
        self.candidates: list[CleanupCandidate] = []
        self.complete = False
        self._dirs: deque[tuple[Path, int]] = deque()
        self._iterator: Iterator[os.DirEntry[str]] | None = None
        self._depth = 0

        if self.root.exists() and self.root.is_dir():
            self._dirs.append((self.root, 0))
        else:
            self.complete = True

    def _close(self) -> None:
        iterator = self._iterator
        self._iterator = None

        if iterator is not None:
            close = getattr(iterator, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass

    def step(self, budget: int) -> None:
        if self.complete or budget <= 0:
            return

        before = self.entries
        deadline = time.monotonic() + 0.018
        cutoff = (
            time.time() - self.old_days * 86400
            if self.old_days is not None
            else None
        )

        while (
            self.entries - before < budget
            and time.monotonic() < deadline
        ):
            if self._iterator is None:
                if not self._dirs:
                    self.complete = True
                    return

                directory, depth = self._dirs.popleft()
                self._depth = depth

                try:
                    self._iterator = os.scandir(directory)
                except OSError:
                    self._iterator = None
                    continue

            try:
                entry = next(self._iterator)
            except StopIteration:
                self._close()
                continue
            except OSError:
                self._close()
                continue

            self.entries += 1

            try:
                if entry.is_symlink():
                    continue

                if entry.is_dir(follow_symlinks=False):
                    if self._depth < self.max_depth:
                        self._dirs.append(
                            (Path(entry.path), self._depth + 1)
                        )
                    continue

                if not entry.is_file(follow_symlinks=False):
                    continue

                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue

            self.files += 1
            self.total_bytes += stat.st_size

            is_candidate = (
                cutoff is None
                or stat.st_mtime < cutoff
            )

            if (
                is_candidate
                and self.candidate_filter is not None
                and not self.candidate_filter(stat)
            ):
                is_candidate = False

            if not is_candidate:
                continue

            self.candidate_files += 1
            self.candidate_bytes += stat.st_size

            if self.collect_candidates:
                self.candidates.append(
                    CleanupCandidate(
                        Path(entry.path),
                        int(stat.st_size),
                        int(stat.st_mtime_ns),
                    )
                )

        if self._iterator is None and not self._dirs:
            self.complete = True


class WorkspaceCacheJob:
    def __init__(self, root: Path) -> None:
        self.key = "workspace_cache"
        self.label = "workspace cache"
        self.root = root.resolve()
        self.reset()

    def reset(self) -> None:
        self.entries = 0
        self.files = 0
        self.candidate_bytes = 0
        self.candidates: list[CleanupCandidate] = []
        self.complete = False
        self._dirs: deque[tuple[Path, bool]] = deque(
            [(self.root, False)]
        )
        self._iterator = None
        self._inside_cache = False

    def _close(self) -> None:
        iterator = self._iterator
        self._iterator = None

        if iterator is not None:
            close = getattr(iterator, "close", None)
            if close:
                try:
                    close()
                except Exception:
                    pass

    def step(self, budget: int) -> None:
        if self.complete or budget <= 0:
            return

        before = self.entries
        deadline = time.monotonic() + 0.018

        while (
            self.entries - before < budget
            and time.monotonic() < deadline
        ):
            if self._iterator is None:
                if not self._dirs:
                    self.complete = True
                    return

                directory, inside_cache = self._dirs.popleft()
                self._inside_cache = inside_cache

                try:
                    self._iterator = os.scandir(directory)
                except OSError:
                    self._iterator = None
                    continue

            try:
                entry = next(self._iterator)
            except StopIteration:
                self._close()
                continue
            except OSError:
                self._close()
                continue

            self.entries += 1

            try:
                if entry.is_symlink():
                    continue

                if entry.is_dir(follow_symlinks=False):
                    inside = (
                        self._inside_cache
                        or entry.name in CACHE_DIR_NAMES
                    )
                    self._dirs.append(
                        (Path(entry.path), inside)
                    )
                    continue

                if not entry.is_file(follow_symlinks=False):
                    continue

                if (
                    not self._inside_cache
                    and not entry.name.endswith(".pyc")
                ):
                    continue

                stat = entry.stat(follow_symlinks=False)
            except OSError:
                continue

            self.files += 1
            self.candidate_bytes += stat.st_size
            self.candidates.append(
                CleanupCandidate(
                    Path(entry.path),
                    int(stat.st_size),
                    int(stat.st_mtime_ns),
                )
            )

        if self._iterator is None and not self._dirs:
            self.complete = True


class MaintenanceDashboardWorker:
    LOOP_INTERVAL = 0.28
    SWEEP_INTERVAL = 180.0

    def __init__(
        self,
        workspace: Path,
        adapter: PlatformAdapter | None = None,
    ) -> None:
        self.workspace = workspace.resolve()
        self.adapter = adapter or get_platform_adapter()
        self.platform_paths = self.adapter.paths()

        self.events: queue.Queue[ActivityEvent] = queue.Queue(
            maxsize=32
        )
        self._lock = threading.RLock()
        self._snapshot = StreamSnapshot(
            platform_name=self.adapter.display_name,
            trash_label=getattr(
                self.adapter,
                "trash_label",
                "Trash",
            ),
        )
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._thread: threading.Thread | None = None
        self._cpu = self.adapter.create_cpu_sampler()
        self._last: dict[str, float] = {}
        self._last_signature: dict[str, str] = {}
        self._pressure_samples: list[
            tuple[float, int, int]
        ] = []
        self._pressure_started = time.monotonic()
        self._recovery_count = 0

        self.user_temp = DirectoryScanJob(
            "user_temp",
            "user TEMP",
            self.platform_paths.user_temp,
            old_days=30,
            collect_candidates=True,
            candidate_filter=(
                self.adapter.is_safe_user_temp_candidate
            ),
        )
        self.workspace_cache = WorkspaceCacheJob(
            self.workspace
        )

        self.system_temp = DirectoryScanJob(
            "system_temp",
            "system TEMP",
            (
                self.platform_paths.system_temp
                if self.platform_paths.system_temp is not None
                else Path("__novelslack_unavailable_system_temp__")
            ),
            old_days=30,
        )
        self.pip_cache = DirectoryScanJob(
            "pip_cache",
            "pip cache",
            (
                self.platform_paths.pip_cache
                if self.platform_paths.pip_cache is not None
                else Path("__novelslack_unavailable_pip_cache__")
            ),
        )
        self.npm_cache = DirectoryScanJob(
            "npm_cache",
            "npm cache",
            (
                self.platform_paths.npm_cache
                if self.platform_paths.npm_cache is not None
                else Path("__novelslack_unavailable_npm_cache__")
            ),
        )

        self.diagnostic_jobs = [
            DirectoryScanJob(
                f"diagnostic_{index}",
                label,
                path,
            )
            for index, (label, path)
            in enumerate(self.platform_paths.diagnostics)
        ]

        self.jobs = [
            self.user_temp,
            self.workspace_cache,
            self.system_temp,
            self.pip_cache,
            self.npm_cache,
            *self.diagnostic_jobs,
        ]

        self._job_index = 0
        self._cycle = 1
        self._sweep_reported = False
        self._next_sweep = 0.0

        try:
            anchor = Path(
                self.workspace.anchor
                or str(self.workspace)
            )
            self._disk_baseline = shutil.disk_usage(
                anchor
            ).free
        except OSError:
            self._disk_baseline = 0

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return

        self._stop.clear()
        self._thread = threading.Thread(
            target=self._run,
            name="NovelSlackMaintenanceWorker",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

        if self._thread:
            self._thread.join(timeout=1.5)

    def pause(self) -> None:
        self._pause.set()

    def resume(self) -> None:
        self._pause.clear()

    def invalidate_storage(self) -> None:
        with self._lock:
            for job in self.jobs:
                job.reset()

            self._job_index = 0
            self._cycle += 1
            self._sweep_reported = False
            self._next_sweep = 0

            self._touch_snapshot(
                current_task="storage sweep",
                current_state="rescanning",
                current_cycle=self._cycle,
            )

    def snapshot(self) -> StreamSnapshot:
        with self._lock:
            s = self._snapshot

            return StreamSnapshot(
                platform_name=s.platform_name,
                trash_label=s.trash_label,
                cpu_load=s.cpu_load,
                memory_load=s.memory_load,
                memory_available=s.memory_available,
                disk_free=s.disk_free,
                disk_delta=s.disk_delta,
                process_count=s.process_count,
                trash_bytes=s.trash_bytes,
                trash_items=s.trash_items,
                safe_reclaim=s.safe_reclaim,
                reviewable=s.reviewable,
                current_task=s.current_task,
                current_entries=s.current_entries,
                current_files=s.current_files,
                current_bytes=s.current_bytes,
                current_cycle=s.current_cycle,
                current_state=s.current_state,
                revision=s.revision,
            )

    def drain_events(self) -> list[ActivityEvent]:
        result: list[ActivityEvent] = []

        while True:
            try:
                result.append(
                    self.events.get_nowait()
                )
            except queue.Empty:
                return result

    def cleanup_plan(self) -> CleanupPlan:
        snap = self.snapshot()
        diagnostic_size = sum(
            job.total_bytes
            for job in self.diagnostic_jobs
        )

        items = [
            CleanupItem(
                "user_temp",
                "Old user TEMP (>30d)",
                self.user_temp.candidate_bytes,
                "Safe",
                (
                    "Old files owned by the current user; "
                    "default selected."
                ),
                True,
                True,
                candidates=tuple(
                    self.user_temp.candidates
                ),
            ),
            CleanupItem(
                "workspace_cache",
                "Workspace regenerable cache",
                self.workspace_cache.candidate_bytes,
                "Safe",
                (
                    "__pycache__, .pyc, pytest/mypy/ruff "
                    "caches."
                ),
                True,
                True,
                candidates=tuple(
                    self.workspace_cache.candidates
                ),
            ),
            CleanupItem(
                "pip_cache",
                "pip cache",
                self.pip_cache.total_bytes,
                "Rebuildable",
                "Package download/build cache; optional.",
                bool(
                    self.platform_paths.pip_cache
                    and self.platform_paths.pip_cache.exists()
                ),
                False,
                root=self.platform_paths.pip_cache,
            ),
            CleanupItem(
                "npm_cache",
                "npm cache",
                self.npm_cache.total_bytes,
                "Rebuildable",
                "Node package cache; optional.",
                bool(
                    self.platform_paths.npm_cache
                    and self.platform_paths.npm_cache.exists()
                ),
                False,
                root=self.platform_paths.npm_cache,
            ),
            CleanupItem(
                "trash",
                snap.trash_label,
                snap.trash_bytes or 0,
                "Confirm",
                "Permanent removal; optional.",
                True,
                False,
            ),
            CleanupItem(
                "system_temp",
                "System TEMP",
                self.system_temp.candidate_bytes,
                "Review only",
                (
                    "System-managed; NovelSlack does not "
                    "auto-delete it."
                ),
                False,
                False,
            ),
            CleanupItem(
                "diagnostics",
                "Diagnostics / crash reports",
                diagnostic_size,
                "Review only",
                (
                    "Diagnostic data is retained unless "
                    "managed externally."
                ),
                False,
                False,
            ),
        ]

        return CleanupPlan(
            items=items,
            scan_complete=all(
                job.complete
                for job in self.jobs
            ),
        )

    def _touch_snapshot(self, **changes) -> None:
        with self._lock:
            changed = False

            for key, value in changes.items():
                if getattr(self._snapshot, key) != value:
                    setattr(
                        self._snapshot,
                        key,
                        value,
                    )
                    changed = True

            if changed:
                self._snapshot.revision += 1

    def _due(
        self,
        key: str,
        interval: float,
    ) -> bool:
        now = time.monotonic()

        if (
            now - self._last.get(key, 0.0)
            >= interval
        ):
            self._last[key] = now
            return True

        return False

    def _emit(
        self,
        event: ActivityEvent,
        force: bool = False,
    ) -> None:
        signature = (
            f"{event.summary}|{event.detail}"
        )

        if (
            not force
            and self._last_signature.get(
                event.task_key
            ) == signature
        ):
            return

        self._last_signature[
            event.task_key
        ] = signature

        try:
            self.events.put_nowait(event)
        except queue.Full:
            try:
                self.events.get_nowait()
            except queue.Empty:
                pass

            try:
                self.events.put_nowait(
                    event
                )
            except queue.Full:
                pass

    def _scan_budget(self) -> int:
        snap = self.snapshot()
        cpu = snap.cpu_load or 0
        memory = snap.memory_load or 0

        if cpu >= 90 or memory >= 95:
            return 2
        if cpu >= 75 or memory >= 90:
            return 4
        if cpu >= 60:
            return 8
        return 28

    def _run(self) -> None:
        self._cpu.sample()

        while not self._stop.is_set():
            if self._pause.is_set():
                self._stop.wait(0.12)
                continue

            try:
                self._cycle_once()
                self._recovery_count = 0
            except Exception as exc:
                self._recovery_count += 1
                self._touch_snapshot(
                    current_state=(
                        "recovering · "
                        f"{type(exc).__name__}"
                    )
                )
                self._emit(
                    ActivityEvent(
                        "worker_recovery",
                        "worker recovery",
                        type(exc).__name__,
                        (
                            "background worker recovered "
                            "and continued"
                        ),
                        "warn",
                    ),
                    force=True,
                )
                self._stop.wait(
                    min(
                        2.0,
                        0.4
                        * self._recovery_count,
                    )
                )

            self._stop.wait(
                self.LOOP_INTERVAL
            )

    def _cycle_once(self) -> None:
        self._sample_system()
        self._advance_sweep()
        self._pressure_window()
        self._periodic_analyses()

    def _sample_system(self) -> None:
        if self._due("cpu", self.adapter.cpu_sample_interval):
            value = self._cpu.sample()

            if value is not None:
                self._touch_snapshot(
                    cpu_load=round(
                        value,
                        1,
                    )
                )

        if self._due("memory", self.adapter.memory_sample_interval):
            value = (
                self.adapter.memory_status()
            )

            if value:
                self._touch_snapshot(
                    memory_load=value[0],
                    memory_available=value[1],
                )

        if self._due("disk", 8.0):
            try:
                free = shutil.disk_usage(
                    Path(
                        self.workspace.anchor
                        or str(self.workspace)
                    )
                ).free
            except OSError:
                free = None

            if free is not None:
                delta = (
                    free - self._disk_baseline
                    if self._disk_baseline
                    else 0
                )
                self._touch_snapshot(
                    disk_free=free,
                    disk_delta=delta,
                )

        if self._due("process", self.adapter.process_count_interval):
            count = (
                self.adapter.process_count()
            )

            if count is not None:
                self._touch_snapshot(
                    process_count=count
                )

        if self._due("trash", self.adapter.trash_status_interval):
            value = (
                self.adapter.trash_status()
            )

            if value is not None:
                self._touch_snapshot(
                    trash_bytes=value.size,
                    trash_items=value.items,
                )
                self._update_totals()

        snap = self.snapshot()

        if (
            snap.cpu_load is not None
            and snap.memory_load is not None
        ):
            self._pressure_samples.append(
                (
                    snap.cpu_load,
                    snap.memory_load,
                    snap.memory_available or 0,
                )
            )
            self._pressure_samples = (
                self._pressure_samples[-120:]
            )

    def _update_totals(self) -> None:
        safe = (
            self.user_temp.candidate_bytes
            + self.workspace_cache.candidate_bytes
        )
        review = (
            self.system_temp.candidate_bytes
            + self.pip_cache.total_bytes
            + self.npm_cache.total_bytes
            + sum(
                job.total_bytes
                for job in self.diagnostic_jobs
            )
            + (
                self.snapshot().trash_bytes
                or 0
            )
        )

        self._touch_snapshot(
            safe_reclaim=safe,
            reviewable=review,
        )

    def _advance_sweep(self) -> None:
        now = time.monotonic()

        if all(
            job.complete
            for job in self.jobs
        ):
            if not self._sweep_reported:
                self._update_totals()
                self._emit_storage_summary()
                self._sweep_reported = True
                self._next_sweep = (
                    now
                    + self.SWEEP_INTERVAL
                )
                self._touch_snapshot(
                    current_task="storage sweep",
                    current_state="complete",
                    current_entries=sum(
                        job.entries
                        for job in self.jobs
                    ),
                    current_files=sum(
                        getattr(
                            job,
                            "files",
                            0,
                        )
                        for job in self.jobs
                    ),
                    current_bytes=(
                        self.snapshot().safe_reclaim
                        + self.snapshot().reviewable
                    ),
                )
            elif now >= self._next_sweep:
                self.invalidate_storage()

            return

        budget = self._scan_budget()
        attempts = 0

        while attempts < len(self.jobs):
            job = self.jobs[
                self._job_index
                % len(self.jobs)
            ]
            self._job_index += 1
            attempts += 1

            if job.complete:
                continue

            job.step(budget)
            self._update_totals()

            self._touch_snapshot(
                current_task=job.label,
                current_state="scanning",
                current_entries=job.entries,
                current_files=getattr(
                    job,
                    "files",
                    0,
                ),
                current_bytes=getattr(
                    job,
                    "candidate_bytes",
                    0,
                ),
                current_cycle=self._cycle,
            )
            break

    def _emit_storage_summary(self) -> None:
        snap = self.snapshot()
        diagnostic_size = sum(
            job.total_bytes
            for job in self.diagnostic_jobs
        )
        detail = (
            "user TEMP "
            f"{format_bytes(self.user_temp.candidate_bytes)} | "
            "workspace "
            f"{format_bytes(self.workspace_cache.candidate_bytes)} | "
            "dev cache "
            f"{format_bytes(self.pip_cache.total_bytes + self.npm_cache.total_bytes)} | "
            "system TEMP "
            f"{format_bytes(self.system_temp.candidate_bytes)} | "
            "diagnostics "
            f"{format_bytes(diagnostic_size)} | "
            f"{snap.trash_label.lower()} "
            f"{format_bytes(snap.trash_bytes or 0)}"
        )

        self._emit(
            ActivityEvent(
                (
                    "storage_sweep_"
                    f"{self._cycle}"
                ),
                "storage sweep",
                (
                    "safe "
                    f"{format_bytes(snap.safe_reclaim)} · "
                    "reviewable "
                    f"{format_bytes(snap.reviewable)}"
                ),
                detail,
            ),
            force=True,
        )

    def _pressure_window(self) -> None:
        now = time.monotonic()

        if (
            now - self._pressure_started
            < 30
        ):
            return

        samples = self._pressure_samples
        self._pressure_samples = []
        self._pressure_started = now

        if not samples:
            return

        cpus = [
            sample[0]
            for sample in samples
        ]
        memories = [
            sample[1]
            for sample in samples
        ]
        free = [
            sample[2]
            for sample in samples
            if sample[2] > 0
        ]

        self._emit(
            ActivityEvent(
                "resource_window",
                "resource window",
                (
                    "CPU avg "
                    f"{sum(cpus) / len(cpus):.0f}% · "
                    f"peak {max(cpus):.0f}%"
                ),
                (
                    "memory avg "
                    f"{sum(memories) / len(memories):.0f}% · "
                    f"peak {max(memories):.0f}% · "
                    "min free "
                    f"{format_bytes(min(free) if free else 0)}"
                ),
            )
        )

    def _periodic_analyses(self) -> None:
        if self._due(
            "process_health",
            self.adapter.process_health_interval,
        ):
            result = (
                self.adapter
                .process_memory_summary()
            )

            if result:
                count, top, high = result
                detail = " | ".join(
                    f"{name} {mib:.0f} MiB"
                    for name, mib in top
                )
                self._emit(
                    ActivityEvent(
                        "process_health",
                        "process health",
                        (
                            f"{count} active · "
                            f"{high} ≥500 MiB"
                        ),
                        detail,
                    )
                )

        if self._due(
            "disk_trend",
            90.0,
        ):
            delta = (
                self.snapshot().disk_delta
            )

            if abs(delta) >= 1024**2:
                self._emit(
                    ActivityEvent(
                        "disk_trend",
                        "disk trend",
                        (
                            "+"
                            if delta >= 0
                            else "-"
                        )
                        + format_bytes(
                            abs(delta)
                        ),
                        (
                            "free-space change "
                            "since start"
                        ),
                    )
                )
