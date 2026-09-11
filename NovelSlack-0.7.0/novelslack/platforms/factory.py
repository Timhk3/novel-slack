from __future__ import annotations

from functools import lru_cache
import os
import sys

from .base import PlatformAdapter
from .linux import LinuxPlatformAdapter
from .macos import MacOSPlatformAdapter
from .windows import WindowsPlatformAdapter


def create_platform_adapter(
    platform_name: str | None = None,
) -> PlatformAdapter:
    requested = (
        platform_name.strip().lower()
        if platform_name
        else None
    )

    if requested in {"windows", "win32", "win"}:
        return WindowsPlatformAdapter()

    if requested in {"macos", "darwin", "mac", "osx"}:
        return MacOSPlatformAdapter()

    if requested in {"linux", "linux2"}:
        return LinuxPlatformAdapter()

    if requested:
        raise RuntimeError(
            f"Unsupported NovelSlack platform: {platform_name}"
        )

    if os.name == "nt" or sys.platform.startswith("win"):
        return WindowsPlatformAdapter()

    if sys.platform == "darwin":
        return MacOSPlatformAdapter()

    if sys.platform.startswith("linux"):
        return LinuxPlatformAdapter()

    raise RuntimeError(
        f"NovelSlack supports Windows, macOS and Linux; "
        f"current platform is {sys.platform!r}."
    )


@lru_cache(maxsize=1)
def get_platform_adapter() -> PlatformAdapter:
    return create_platform_adapter()
