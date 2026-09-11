from __future__ import annotations

import os
from pathlib import Path
import tempfile

from .base import (
    PlatformAdapter,
    PlatformPaths,
    PosixOwnershipMixin,
    TrashCleanResult,
    TrashStatus,
    directory_size_and_count,
    empty_directory_contents,
)


class LinuxCpuSampler:
    def __init__(self) -> None:
        self.previous: tuple[int, int] | None = None

    def sample(self) -> float | None:
        try:
            first = Path("/proc/stat").read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()[0]
        except (OSError, IndexError):
            return None

        fields = first.split()
        if not fields or fields[0] != "cpu":
            return None

        try:
            values = [int(value) for value in fields[1:]]
        except ValueError:
            return None

        if len(values) < 4:
            return None

        total = sum(values)
        idle = values[3] + (values[4] if len(values) > 4 else 0)
        current = (total, idle)
        previous = self.previous
        self.previous = current

        if previous is None:
            return None

        total_delta = current[0] - previous[0]
        idle_delta = current[1] - previous[1]

        if total_delta <= 0:
            return None

        return max(
            0.0,
            min(
                100.0,
                100 * (total_delta - idle_delta) / total_delta,
            ),
        )


class LinuxPlatformAdapter(
    PosixOwnershipMixin,
    PlatformAdapter,
):
    key = "linux"
    display_name = "Linux"
    trash_label = "Trash"
    trash_status_interval = 60.0

    def __init__(self) -> None:
        self.home = Path.home()
        self.xdg_cache = Path(
            os.environ.get(
                "XDG_CACHE_HOME",
                str(self.home / ".cache"),
            )
        )
        self.xdg_state = Path(
            os.environ.get(
                "XDG_STATE_HOME",
                str(self.home / ".local" / "state"),
            )
        )
        self.xdg_data = Path(
            os.environ.get(
                "XDG_DATA_HOME",
                str(self.home / ".local" / "share"),
            )
        )

    def paths(self) -> PlatformPaths:
        diagnostics: list[tuple[str, Path]] = []

        for label, path in (
            ("crash reports", Path("/var/crash")),
            (
                "user coredumps",
                self.xdg_state / "systemd" / "coredump",
            ),
        ):
            if path.exists():
                diagnostics.append((label, path))

        return PlatformPaths(
            user_temp=Path(tempfile.gettempdir()),
            system_temp=Path("/var/tmp"),
            pip_cache=self.xdg_cache / "pip",
            npm_cache=self.home / ".npm",
            diagnostics=tuple(diagnostics),
            trash_root=self.xdg_data / "Trash" / "files",
        )

    def state_dir(self) -> Path:
        return self.xdg_state / "NovelSlack"

    def app_cache_dir(self) -> Path:
        return self.xdg_cache / "NovelSlack"

    def create_cpu_sampler(self) -> LinuxCpuSampler:
        return LinuxCpuSampler()

    def memory_status(self) -> tuple[int, int] | None:
        try:
            lines = Path("/proc/meminfo").read_text(
                encoding="utf-8",
                errors="replace",
            ).splitlines()
        except OSError:
            return None

        values: dict[str, int] = {}

        for line in lines:
            if ":" not in line:
                continue

            key, raw = line.split(":", 1)
            parts = raw.strip().split()
            if not parts:
                continue

            try:
                value = int(parts[0]) * 1024
            except ValueError:
                continue

            values[key] = value

        total = values.get("MemTotal")
        available = values.get("MemAvailable")

        if total is None:
            return None

        if available is None:
            available = (
                values.get("MemFree", 0)
                + values.get("Buffers", 0)
                + values.get("Cached", 0)
            )

        available = max(0, min(total, available))
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
        try:
            return sum(
                1
                for child in Path("/proc").iterdir()
                if child.name.isdigit()
            )
        except OSError:
            return None

    def process_memory_summary(
        self,
    ) -> tuple[int, list[tuple[str, float]], int] | None:
        rows: list[tuple[int, str]] = []

        try:
            pids = [
                child
                for child in Path("/proc").iterdir()
                if child.name.isdigit()
            ]
        except OSError:
            return None

        for pid in pids:
            try:
                status = (pid / "status").read_text(
                    encoding="utf-8",
                    errors="replace",
                )
            except OSError:
                continue

            name = pid.name
            rss_kib = 0

            for line in status.splitlines():
                if line.startswith("Name:"):
                    name = line.split(":", 1)[1].strip() or name
                elif line.startswith("VmRSS:"):
                    parts = line.split()
                    if len(parts) >= 2:
                        try:
                            rss_kib = int(parts[1])
                        except ValueError:
                            rss_kib = 0

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
        paths = self.paths()
        files_result = empty_directory_contents(
            paths.trash_root
        )

        # Freedesktop Trash keeps metadata in a sibling `info/` directory.
        info_root = (
            self.xdg_data
            / "Trash"
            / "info"
        )
        info_result = empty_directory_contents(info_root)

        return TrashCleanResult(
            reclaimed=files_result.reclaimed,
            removed=files_result.removed + info_result.removed,
            skipped=files_result.skipped + info_result.skipped,
        )
