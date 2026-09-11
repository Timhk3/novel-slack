from __future__ import annotations

import csv
import ctypes
import io
import os
from pathlib import Path
import subprocess
import tempfile

from .base import (
    PlatformAdapter,
    PlatformPaths,
    TrashCleanResult,
    TrashStatus,
)


class WindowsCpuSampler:
    def __init__(self) -> None:
        self.previous: tuple[int, int, int] | None = None

    def sample(self) -> float | None:
        class FILETIME(ctypes.Structure):
            _fields_ = [
                ("dwLowDateTime", ctypes.c_ulong),
                ("dwHighDateTime", ctypes.c_ulong),
            ]

        def value(ft: FILETIME) -> int:
            return (int(ft.dwHighDateTime) << 32) | int(ft.dwLowDateTime)

        idle = FILETIME()
        kernel = FILETIME()
        user = FILETIME()

        try:
            ok = ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle),
                ctypes.byref(kernel),
                ctypes.byref(user),
            )
        except Exception:
            return None

        if not ok:
            return None

        current = (value(idle), value(kernel), value(user))
        previous = self.previous
        self.previous = current

        if previous is None:
            return None

        idle_delta = current[0] - previous[0]
        total = (current[1] - previous[1]) + (current[2] - previous[2])

        if total <= 0:
            return None

        return max(
            0.0,
            min(100.0, (total - idle_delta) / total * 100),
        )


class WindowsPlatformAdapter(PlatformAdapter):
    key = "windows"
    display_name = "Windows"
    trash_label = "Recycle Bin"

    def __init__(self) -> None:
        self.home = Path.home()
        self.local = Path(
            os.environ.get("LOCALAPPDATA", str(self.home))
        )
        self.roaming = Path(
            os.environ.get("APPDATA", str(self.home))
        )
        self.windir = Path(
            os.environ.get("WINDIR", r"C:\Windows")
        )

    def paths(self) -> PlatformPaths:
        diagnostics = (
            ("CrashDumps", self.local / "CrashDumps"),
            (
                "WER reports",
                self.local / "Microsoft" / "Windows" / "WER",
            ),
        )
        return PlatformPaths(
            user_temp=Path(tempfile.gettempdir()),
            system_temp=self.windir / "Temp",
            pip_cache=self.local / "pip" / "Cache",
            npm_cache=self.local / "npm-cache",
            diagnostics=diagnostics,
            trash_root=None,
        )

    def state_dir(self) -> Path:
        return self.roaming / "NovelSlack"

    def app_cache_dir(self) -> Path:
        return self.local / "NovelSlack"

    def create_cpu_sampler(self) -> WindowsCpuSampler:
        return WindowsCpuSampler()

    def memory_status(self) -> tuple[int, int] | None:
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [
                ("dwLength", ctypes.c_ulong),
                ("dwMemoryLoad", ctypes.c_ulong),
                ("ullTotalPhys", ctypes.c_ulonglong),
                ("ullAvailPhys", ctypes.c_ulonglong),
                ("ullTotalPageFile", ctypes.c_ulonglong),
                ("ullAvailPageFile", ctypes.c_ulonglong),
                ("ullTotalVirtual", ctypes.c_ulonglong),
                ("ullAvailVirtual", ctypes.c_ulonglong),
                ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
            ]

        status = MEMORYSTATUSEX()
        status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)

        try:
            ok = ctypes.windll.kernel32.GlobalMemoryStatusEx(
                ctypes.byref(status)
            )
        except Exception:
            return None

        if not ok:
            return None

        return int(status.dwMemoryLoad), int(status.ullAvailPhys)

    def process_count(self) -> int | None:
        TH32CS_SNAPPROCESS = 0x00000002
        MAX_PATH = 260

        class PROCESSENTRY32W(ctypes.Structure):
            _fields_ = [
                ("dwSize", ctypes.c_ulong),
                ("cntUsage", ctypes.c_ulong),
                ("th32ProcessID", ctypes.c_ulong),
                ("th32DefaultHeapID", ctypes.c_void_p),
                ("th32ModuleID", ctypes.c_ulong),
                ("cntThreads", ctypes.c_ulong),
                ("th32ParentProcessID", ctypes.c_ulong),
                ("pcPriClassBase", ctypes.c_long),
                ("dwFlags", ctypes.c_ulong),
                ("szExeFile", ctypes.c_wchar * MAX_PATH),
            ]

        try:
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            snapshot = kernel32.CreateToolhelp32Snapshot(
                TH32CS_SNAPPROCESS,
                0,
            )
            if snapshot == ctypes.c_void_p(-1).value:
                return None

            entry = PROCESSENTRY32W()
            entry.dwSize = ctypes.sizeof(PROCESSENTRY32W)
            count = 0

            if kernel32.Process32FirstW(
                snapshot,
                ctypes.byref(entry),
            ):
                count = 1
                while kernel32.Process32NextW(
                    snapshot,
                    ctypes.byref(entry),
                ):
                    count += 1

            kernel32.CloseHandle(snapshot)
            return count
        except Exception:
            return None

    def trash_status(self) -> TrashStatus | None:
        class SHQUERYRBINFO(ctypes.Structure):
            _fields_ = [
                ("cbSize", ctypes.c_ulong),
                ("i64Size", ctypes.c_longlong),
                ("i64NumItems", ctypes.c_longlong),
            ]

        info = SHQUERYRBINFO()
        info.cbSize = ctypes.sizeof(info)

        try:
            result = ctypes.windll.shell32.SHQueryRecycleBinW(
                None,
                ctypes.byref(info),
            )
        except Exception:
            return None

        if result != 0:
            return None

        return TrashStatus(
            int(info.i64Size),
            int(info.i64NumItems),
        )

    def empty_trash(self) -> TrashCleanResult:
        flags = 0x00000001 | 0x00000002 | 0x00000004

        try:
            result = ctypes.windll.shell32.SHEmptyRecycleBinW(
                None,
                None,
                flags,
            )
        except Exception:
            return TrashCleanResult(0, 0, 1)

        return (
            TrashCleanResult(0, 1, 0)
            if result == 0
            else TrashCleanResult(0, 0, 1)
        )

    def process_memory_summary(
        self,
    ) -> tuple[int, list[tuple[str, float]], int] | None:
        try:
            proc = subprocess.run(
                ["tasklist", "/FO", "CSV", "/NH"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                shell=False,
                creationflags=getattr(
                    subprocess,
                    "CREATE_NO_WINDOW",
                    0,
                ),
            )
        except Exception:
            return None

        if proc.returncode != 0:
            return None

        rows: list[tuple[int, str]] = []

        for row in csv.reader(io.StringIO(proc.stdout)):
            if len(row) < 5:
                continue

            raw = (
                row[4]
                .replace(",", "")
                .replace(" K", "")
                .strip()
            )

            try:
                kb = int(raw)
            except ValueError:
                continue

            rows.append((kb, row[0].strip()))

        if not rows:
            return None

        rows.sort(reverse=True)
        top = [
            (name, kb / 1024)
            for kb, name in rows[:3]
        ]
        high = sum(
            1
            for kb, _ in rows
            if kb >= 500 * 1024
        )
        return len(rows), top, high
