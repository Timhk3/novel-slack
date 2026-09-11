from __future__ import annotations

import os
import sys
import time

from .model import Action

if os.name == "nt":
    import msvcrt
else:
    import fcntl
    import termios
    import tty


KEYMAP = {
    "W": Action.LIVE,
    "R": Action.READING,
    "O": Action.CATALOG,
    "C": Action.CLEANUP,
    "I": Action.STATUS,
    "__ENTER__": Action.SELECT,
    " ": Action.TOGGLE,
    "D": Action.NEXT_PAGE,
    "A": Action.PREVIOUS_PAGE,
    "G": Action.GOTO_PAGE,
    "/": Action.SEARCH,
    "F": Action.SEARCH,
    "N": Action.NEXT_MATCH,
    "P": Action.PREVIOUS_MATCH,
    "X": Action.CLEAR_SEARCH,
    "\x1b": Action.CLEAR_SEARCH,
    "]": Action.NEXT_CHAPTER,
    "[": Action.PREVIOUS_CHAPTER,
    "T": Action.GOTO_CHAPTER,
    "Q": Action.QUIT,
}


class Keyboard:
    def __init__(self) -> None:
        self._old_settings = None
        self._last_seen: dict[str, float] = {}
        self._cooldown = {
            "W": 0.10, "R": 0.15, "O": 0.15, "C": 0.30, "I": 0.20,
            "__ENTER__": 0.15, " ": 0.15, "D": 0.15, "A": 0.15,
            "G": 0.20, "/": 0.20, "F": 0.20, "N": 0.15, "P": 0.15,
            "X": 0.15, "\x1b": 0.15, "]": 0.12, "[": 0.12,
            "T": 0.20, "Q": 0.20,
        }

    def open(self) -> None:
        if os.name == "nt":
            return
        try:
            self._old_settings = termios.tcgetattr(sys.stdin)
            tty.setcbreak(sys.stdin.fileno())
        except (termios.error, OSError):
            self._old_settings = None

    def close(self) -> None:
        if os.name == "nt" or self._old_settings is None:
            return
        try:
            termios.tcsetattr(sys.stdin, termios.TCSADRAIN, self._old_settings)
        except (termios.error, OSError):
            pass

    def poll(self) -> Action:
        key = self._read_key()
        if not key:
            return Action.NONE
        lookup = (
            key.upper()
            if key not in {"[", "]", "/", " ", "\x1b"} and not key.startswith("__")
            else key
        )
        action = KEYMAP.get(lookup, Action.NONE)
        if action is Action.NONE:
            return action
        now = time.monotonic()
        if now - self._last_seen.get(lookup, 0.0) < self._cooldown.get(lookup, 0.15):
            return Action.NONE
        self._last_seen[lookup] = now
        return action

    def poll_text(self) -> str | None:
        """Return raw text/control input without action mapping or debounce."""
        return self._read_key()

    def drain(self) -> None:
        if os.name != "nt":
            return
        try:
            while msvcrt.kbhit():
                msvcrt.getwch()
        except Exception:
            pass

    def read_line(self, prompt: str) -> str:
        self.drain()
        self._last_seen.clear()
        if os.name == "nt":
            try:
                value = input(prompt)
            finally:
                self._flush_windows_input()
            return value
        self.close()
        try:
            return input(prompt)
        finally:
            self.open()
            self._last_seen.clear()

    def _flush_windows_input(self) -> None:
        if os.name != "nt":
            return
        try:
            import ctypes
            kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
            handle = kernel32.GetStdHandle(-10)
            if handle:
                kernel32.FlushConsoleInputBuffer(handle)
        except Exception:
            pass

    def _read_key(self) -> str | None:
        if os.name == "nt":
            if not msvcrt.kbhit():
                return None
            char = msvcrt.getwch()
            if char in ("\x00", "\xe0"):
                if msvcrt.kbhit():
                    msvcrt.getwch()
                return None
            if char == "\r":
                return "__ENTER__"
            return char

        try:
            fd = sys.stdin.fileno()
            flags = fcntl.fcntl(fd, fcntl.F_GETFL)
            fcntl.fcntl(fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)
            try:
                char = sys.stdin.read(1) or None
            finally:
                fcntl.fcntl(fd, fcntl.F_SETFL, flags)
        except Exception:
            return None

        if char in ("\r", "\n"):
            return "__ENTER__"
        return char
