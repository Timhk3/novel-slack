from __future__ import annotations

import gc
import os
from pathlib import Path
import time

from .model import (
    CheckResult,
    CleanupCandidate,
    CleanupPlan,
)
from .platforms import (
    PlatformAdapter,
    get_platform_adapter,
)


def _fmt(value: int) -> str:
    if value >= 1024**3:
        return f"{value / 1024**3:.2f} GiB"
    if value >= 1024**2:
        return f"{value / 1024**2:.2f} MiB"
    if value >= 1024:
        return f"{value / 1024:.1f} KiB"
    return f"{value} B"


def _delete_validated_candidates(
    candidates: tuple[CleanupCandidate, ...],
) -> tuple[int, int, int]:
    reclaimed = 0
    removed = 0
    skipped = 0

    for candidate in candidates:
        path = candidate.path

        try:
            if (
                not path.exists()
                or path.is_symlink()
                or not path.is_file()
            ):
                skipped += 1
                continue

            stat = path.stat()

            if (
                stat.st_size != candidate.size
                or stat.st_mtime_ns != candidate.mtime_ns
            ):
                skipped += 1
                continue

            path.unlink()
            reclaimed += candidate.size
            removed += 1
        except OSError:
            skipped += 1

    parents = sorted(
        {
            candidate.path.parent
            for candidate in candidates
        },
        key=lambda path: len(path.parts),
        reverse=True,
    )

    for parent in parents:
        try:
            parent.rmdir()
        except OSError:
            pass

    return reclaimed, removed, skipped


def _clear_known_cache_root(
    root: Path | None,
) -> tuple[int, int, int]:
    if (
        root is None
        or not root.exists()
        or root.is_symlink()
    ):
        return 0, 0, 0

    reclaimed = 0
    removed = 0
    skipped = 0

    for current, dirs, files in os.walk(
        root,
        topdown=False,
        followlinks=False,
    ):
        current_path = Path(current)

        for filename in files:
            path = current_path / filename

            try:
                if path.is_symlink():
                    skipped += 1
                    continue

                size = path.stat().st_size
                path.unlink()
                reclaimed += size
                removed += 1
            except OSError:
                skipped += 1

        for dirname in dirs:
            path = current_path / dirname

            try:
                if not path.is_symlink():
                    path.rmdir()
            except OSError:
                pass

    return reclaimed, removed, skipped


def execute_cleanup(
    plan: CleanupPlan,
    selected_ids: set[str],
    adapter: PlatformAdapter | None = None,
) -> CheckResult:
    adapter = adapter or get_platform_adapter()
    start = time.perf_counter()

    total_reclaimed = 0
    total_removed = 0
    total_skipped = 0
    lines: list[str] = []

    for item in plan.items:
        if (
            item.item_id not in selected_ids
            or not item.selectable
        ):
            continue

        if item.item_id in {
            "user_temp",
            "workspace_cache",
        }:
            reclaimed, removed, skipped = (
                _delete_validated_candidates(
                    item.candidates
                )
            )

        elif item.item_id in {
            "pip_cache",
            "npm_cache",
        }:
            reclaimed, removed, skipped = (
                _clear_known_cache_root(
                    item.root
                )
            )

        elif item.item_id == "trash":
            result = adapter.empty_trash()
            reclaimed = result.reclaimed
            removed = result.removed
            skipped = result.skipped

            # Windows' native API does not report reclaimed bytes.
            if (
                reclaimed == 0
                and removed > 0
                and item.size > 0
            ):
                reclaimed = item.size

        else:
            continue

        total_reclaimed += reclaimed
        total_removed += removed
        total_skipped += skipped

        lines.append(
            f"{item.label}  "
            f"{_fmt(reclaimed)} · "
            f"{removed} removed · "
            f"{skipped} skipped"
        )

    gc.collect()

    lines.extend(
        [
            f"total  {_fmt(total_reclaimed)}",
            f"removed  {total_removed}",
            f"skipped  {total_skipped}",
        ]
    )

    return CheckResult(
        "Cleanup Complete",
        "validated cleanup plan",
        lines,
        f"{_fmt(total_reclaimed)} reclaimed",
        (
            time.perf_counter()
            - start
        )
        * 1000,
        (
            "ok"
            if total_skipped == 0
            else "warn"
        ),
    )
