from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import subprocess
from typing import Protocol


@dataclass(frozen=True, slots=True)
class PlatformPaths:
    user_temp: Path
    system_temp: Path | None
    pip_cache: Path | None
    npm_cache: Path | None
    diagnostics: tuple[tuple[str, Path], ...]
    trash_root: Path | None


@dataclass(frozen=True, slots=True)
class TrashStatus:
    size: int = 0
    items: int = 0


@dataclass(frozen=True, slots=True)
class TrashCleanResult:
    reclaimed: int = 0
    removed: int = 0
    skipped: int = 0


class CpuSampler(Protocol):
    def sample(self) -> float | None:
        ...


class PlatformAdapter(ABC):
    """Operating-system boundary for NovelSlack maintenance features."""

    key: str
    display_name: str
    trash_label: str = "Trash"

    cpu_sample_interval: float = 1.5
    memory_sample_interval: float = 1.5
    process_count_interval: float = 10.0
    trash_status_interval: float = 20.0
    process_health_interval: float = 60.0

    @abstractmethod
    def paths(self) -> PlatformPaths:
        raise NotImplementedError

    @abstractmethod
    def state_dir(self) -> Path:
        raise NotImplementedError

    @abstractmethod
    def app_cache_dir(self) -> Path:
        raise NotImplementedError

    @abstractmethod
    def create_cpu_sampler(self) -> CpuSampler:
        raise NotImplementedError

    @abstractmethod
    def memory_status(self) -> tuple[int, int] | None:
        """Return (memory_load_percent, available_physical_bytes)."""
        raise NotImplementedError

    @abstractmethod
    def process_count(self) -> int | None:
        raise NotImplementedError

    @abstractmethod
    def process_memory_summary(
        self,
    ) -> tuple[int, list[tuple[str, float]], int] | None:
        """Return process count, top 3 (name, MiB), and count >=500 MiB."""
        raise NotImplementedError

    @abstractmethod
    def trash_status(self) -> TrashStatus | None:
        raise NotImplementedError

    @abstractmethod
    def empty_trash(self) -> TrashCleanResult:
        raise NotImplementedError

    def is_safe_user_temp_candidate(self, stat: os.stat_result) -> bool:
        return True


class LoadAverageCpuSampler:
    """Low-overhead fallback for POSIX systems where exact counters are absent."""

    def sample(self) -> float | None:
        try:
            cpus = max(os.cpu_count() or 1, 1)
            return max(0.0, min(100.0, os.getloadavg()[0] / cpus * 100))
        except (AttributeError, OSError):
            return None


def run_command(
    args: list[str],
    *,
    timeout: float = 5.0,
) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None


def directory_size_and_count(root: Path | None) -> TrashStatus:
    if root is None or not root.exists() or root.is_symlink():
        return TrashStatus()

    total = 0
    count = 0

    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [
            name
            for name in dirs
            if not (current_path / name).is_symlink()
        ]

        for name in files:
            path = current_path / name
            try:
                if path.is_symlink():
                    continue
                total += path.stat().st_size
                count += 1
            except OSError:
                continue

    return TrashStatus(total, count)


def empty_directory_contents(root: Path | None) -> TrashCleanResult:
    if root is None or not root.exists() or root.is_symlink():
        return TrashCleanResult()

    before = directory_size_and_count(root)
    removed = 0
    skipped = 0

    try:
        children = list(root.iterdir())
    except OSError:
        return TrashCleanResult(0, 0, 1)

    for child in children:
        try:
            if child.is_symlink():
                child.unlink()
                removed += 1
            elif child.is_dir():
                shutil.rmtree(child)
                removed += 1
            else:
                child.unlink()
                removed += 1
        except OSError:
            skipped += 1

    after = directory_size_and_count(root)
    reclaimed = max(0, before.size - after.size)
    return TrashCleanResult(reclaimed, removed, skipped)


class PosixOwnershipMixin:
    def is_safe_user_temp_candidate(self, stat: os.stat_result) -> bool:
        try:
            return stat.st_uid == os.getuid()
        except (AttributeError, OSError):
            return False
