from __future__ import annotations

import os
from pathlib import Path
import re
import tempfile

from .base import (
    LoadAverageCpuSampler,
    PlatformAdapter,
    PlatformPaths,
    PosixOwnershipMixin,
    TrashCleanResult,
    TrashStatus,
    directory_size_and_count,
    empty_directory_contents,
    run_command,
)


class MacOSPlatformAdapter(
    PosixOwnershipMixin,
    PlatformAdapter,
):
    key = "macos"
    display_name = "macOS"
    trash_label = "Trash"
    memory_sample_interval = 4.0
    process_count_interval = 20.0
    trash_status_interval = 60.0
    process_health_interval = 75.0

    def __init__(self) -> None:
        self.home = Path.home()
        self._total_memory: int | None = None

    def paths(self) -> PlatformPaths:
        diagnostics: list[tuple[str, Path]] = []

        diagnostic_reports = (
            self.home / "Library" / "Logs" / "DiagnosticReports"
        )
        if diagnostic_reports.exists():
            diagnostics.append(
                ("DiagnosticReports", diagnostic_reports)
            )

        return PlatformPaths(
            user_temp=Path(tempfile.gettempdir()),
            system_temp=Path("/private/var/tmp"),
            pip_cache=self.home / "Library" / "Caches" / "pip",
            npm_cache=self.home / ".npm",
            diagnostics=tuple(diagnostics),
            trash_root=self.home / ".Trash",
        )

    def state_dir(self) -> Path:
        return (
            self.home
            / "Library"
            / "Application Support"
            / "NovelSlack"
        )

    def app_cache_dir(self) -> Path:
        return self.home / "Library" / "Caches" / "NovelSlack"

    def create_cpu_sampler(self) -> LoadAverageCpuSampler:
        # Deliberately uses loadavg rather than spawning `top` every 1.5 s.
        return LoadAverageCpuSampler()

    def _total_physical_memory(self) -> int | None:
        if self._total_memory is not None:
            return self._total_memory

        proc = run_command(
            ["sysctl", "-n", "hw.memsize"],
            timeout=3,
        )
        if proc is None or proc.returncode != 0:
            return None

        try:
            self._total_memory = int(proc.stdout.strip())
        except ValueError:
            return None

        return self._total_memory

    def memory_status(self) -> tuple[int, int] | None:
        total = self._total_physical_memory()
        vm_proc = run_command(
            ["vm_stat"],
            timeout=3,
        )

        if (
            total is None
            or vm_proc is None
            or vm_proc.returncode != 0
        ):
            return None

        page_size = 4096
        page_match = re.search(
            r"page size of\s+(\d+)\s+bytes",
            vm_proc.stdout,
        )
        if page_match:
            page_size = int(page_match.group(1))

        pages: dict[str, int] = {}

        for line in vm_proc.stdout.splitlines():
            match = re.match(
                r"([^:]+):\s+([0-9.]+)\.?",
                line.strip(),
            )
            if not match:
                continue

            try:
                pages[match.group(1).strip()] = int(
                    match.group(2).replace(".", "")
                )
            except ValueError:
                continue

        available_pages = sum(
            pages.get(key, 0)
            for key in (
                "Pages free",
                "Pages inactive",
                "Pages speculative",
                "Pages purgeable",
            )
        )
        available = max(
            0,
            min(total, available_pages * page_size),
        )
        load = int(
            round(
                100
                * (1 - available / total)
                if total > 0
                else 0
            )
        )
        return max(0, min(100, load)), available

    def process_count(self) -> int | None:
        proc = run_command(
            ["ps", "-axo", "pid="],
            timeout=5,
        )
        if proc is None or proc.returncode != 0:
            return None

        return sum(
            1
            for line in proc.stdout.splitlines()
            if line.strip().isdigit()
        )

    def process_memory_summary(
        self,
    ) -> tuple[int, list[tuple[str, float]], int] | None:
        proc = run_command(
            ["ps", "-axo", "rss=,comm="],
            timeout=6,
        )
        if proc is None or proc.returncode != 0:
            return None

        rows: list[tuple[int, str]] = []

        for line in proc.stdout.splitlines():
            line = line.strip()
            if not line:
                continue

            parts = line.split(None, 1)
            if not parts:
                continue

            try:
                rss_kib = int(parts[0])
            except ValueError:
                continue

            name = (
                Path(parts[1]).name
                if len(parts) > 1
                else "unknown"
            )
            rows.append((rss_kib, name))

        if not rows:
            return None

        rows.sort(reverse=True)
        top = [
            (name, rss_kib / 1024)
            for rss_kib, name in rows[:3]
        ]
        high = sum(
            1
            for rss_kib, _ in rows
            if rss_kib >= 500 * 1024
        )
        return len(rows), top, high

    def trash_status(self) -> TrashStatus | None:
        return directory_size_and_count(
            self.paths().trash_root
        )

    def empty_trash(self) -> TrashCleanResult:
        return empty_directory_contents(
            self.paths().trash_root
        )
