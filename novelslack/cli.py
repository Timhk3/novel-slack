from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console

from . import __version__
from .app import NovelSlackApp
from .state_store import StateStore


GUIDE = r"""
NovelSlack
==========

Terminal novel reader + low-load system maintenance dashboard.

QUICK START
  novelslack
  novelslack --text "<book.txt>"

CORE KEYS
  W          Dashboard
  R          Reader
  C          Cleanup Review
  I          System Status
  Q          Quit

READER
  A          Previous page
  D / Space  Next page
  G          Go to page
  / or F     Search
  N / P      Next / previous match
  X / Esc    Clear search
  [ / ]      Previous / next chapter
  T          Go to chapter
  O          Volume / chapter catalog

CATALOG
  [ / ]      Move selection
  Enter      Open selected volume/chapter
  A / D      Previous / next chapter-list page
  O          Back to volume list when available

CLEANUP REVIEW
  [ / ]      Move selection
  Space      Toggle selectable item
  Enter      Execute selected cleanup
  W          Cancel / dashboard

CLEANUP SAFETY
  Default selected:
    - user TEMP files older than 30 days
    - regenerable workspace cache

  Optional, explicit selection:
    - pip cache
    - npm cache
    - Trash / Recycle Bin

  Scan-only:
    - Windows TEMP
    - Crash / WER reports

RESOURCE POLICY
  - one low-load maintenance worker
  - dirty dashboard render, max once every 0.5s
  - input polling about every 35ms
  - incremental disk scanning
  - automatic throttling under CPU/memory pressure
  - Reader/catalog/cleanup review pause background scanning
  - no network activity
"""


class Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        self.print_usage(sys.stderr)
        print(f"\nError: {message}\n", file=sys.stderr)
        print("Run 'novelslack help' for the full guide.", file=sys.stderr)
        raise SystemExit(2)


def build_parser() -> argparse.ArgumentParser:
    parser = Parser(
        prog="novelslack",
        add_help=False,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=GUIDE,
    )
    parser.add_argument("-h", "--help", "-help", action="help")
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"NovelSlack {__version__}",
    )
    parser.add_argument("--workspace", default=None, metavar="PATH")
    parser.add_argument("-t", "--text", default=None, metavar="FILE")
    parser.add_argument("-l", "--lines", type=int, default=None, metavar="NUMBER")
    return parser


def _directory(value: str | None) -> Path | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return path if path.is_dir() else None


def _file(value: str | None) -> str | None:
    if not value:
        return None
    path = Path(value).expanduser()
    return str(path) if path.is_file() else None


def main() -> None:
    argv = sys.argv[1:]

    if argv and argv[0].lower() in {"help", "guide"}:
        print(GUIDE.strip())
        return

    args = build_parser().parse_args(argv)
    store = StateStore()

    workspace = _directory(args.workspace)
    if args.workspace and workspace is None:
        Console().print("[red]Workspace does not exist.[/]")
        raise SystemExit(2)
    workspace = workspace or _directory(store.last_workspace) or Path.cwd()

    text_path = _file(args.text)
    if args.text and text_path is None:
        Console().print("[red]Text file does not exist.[/]")
        raise SystemExit(2)
    text_path = text_path or _file(store.last_book)

    page_size = args.lines if args.lines is not None else store.page_size
    if page_size < 1:
        Console().print("[red]--lines must be at least 1.[/]")
        raise SystemExit(2)

    NovelSlackApp(
        workspace=workspace,
        text_path=text_path,
        page_size=page_size,
        store=store,
    ).run()
