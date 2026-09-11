# NovelSlack v0.7.0

First public cross-platform release of NovelSlack.

NovelSlack combines a terminal TXT reader with a deliberately low-load local
system-maintenance dashboard. It runs locally and does not require network
access at runtime.

## Reader

- responsive terminal UI
- chapter-bounded pagination
- every detected chapter starts at the top of a new page
- page, search and chapter input stays inside the Reader screen
- TXT search with next/previous match navigation
- chapter and volume catalog
- chapter index caching
- persistent reading position
- safe resume after a TXT file changes
- UTF-8 / UTF-8 BOM / GB18030 text loading

## Maintenance dashboard

- CPU, memory, disk and process overview
- incremental low-I/O storage scans
- grouped maintenance activity instead of repetitive log spam
- dirty rendering to avoid unnecessary terminal redraws
- adaptive scan throttling under system pressure
- explicit Cleanup Review before deletion
- safe candidate revalidation before deletion

## Cleanup policy

Default selected:

- user-owned TEMP files older than 30 days
- regenerable cache files inside the selected workspace

Explicit opt-in:

- pip cache
- npm cache
- Trash / Recycle Bin

Review only:

- system TEMP
- diagnostics / crash reports

## Platforms

### Windows

Uses Windows-native APIs for CPU, physical memory, process enumeration and the
Recycle Bin, while preserving the behavior validated during the Windows
development cycle.

### macOS

Uses macOS-native locations and lightweight system commands including
`vm_stat` and `ps`. Trash is scoped to the current user's `~/.Trash`.

### Linux

Uses `/proc` for CPU, memory and process information and follows XDG locations
for state/cache/Trash where available. Shared TEMP cleanup is restricted to
files owned by the current UID.

## Requirements

- Python 3.10+
- Rich 13.7+

## Install from source

```bash
python -m pip install .
```

Windows PowerShell:

```powershell
python -m pip install .
```

Verify:

```text
novelslack --version
```

## Start reading

```text
novelslack --text "/path/to/book.txt"
```

NovelSlack does not bundle or distribute book content. Use TXT files you are
authorized to access.
