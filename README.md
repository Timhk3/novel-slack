# NovelSlack 0.7.0

A cross-platform terminal TXT novel reader paired with a low-load system
maintenance dashboard.

Supported targets:

- Windows 10 / 11
- macOS
- Linux, with Ubuntu / Debian-style environments as the primary validation target

## Cross-platform backend

0.7.0 moves all native system behavior behind three adapters:

```text
novelslack/platforms/
├── windows.py
├── macos.py
├── linux.py
├── base.py
└── factory.py
```

The Reader, chapter parser, UI, state machine, cleanup review and maintenance
workflow no longer contain platform-specific branches.

### Windows

- CPU: WinAPI `GetSystemTimes`
- memory: `GlobalMemoryStatusEx`
- processes: Toolhelp + `tasklist`
- Recycle Bin: Windows Shell API
- Windows TEMP / CrashDumps / WER
- existing Windows state/cache locations are preserved

### macOS

- CPU: low-overhead normalized load average
- memory: `vm_stat` + cached `sysctl hw.memsize`
- process ranking: `ps`
- Trash: `~/.Trash`
- TEMP/cache/DiagnosticReports use macOS-native user locations

### Linux

- CPU: `/proc/stat`
- memory: `/proc/meminfo`
- processes: `/proc`
- Trash: FreeDesktop `$XDG_DATA_HOME/Trash`
- state/cache follow XDG locations
- shared temp cleanup is restricted to files owned by the current UID

## Cleanup Review

Press `C`:

```text
Cleanup Review

[x] Old user TEMP (>30d)          Safe
[x] Workspace regenerable cache  Safe
[ ] pip cache                     Rebuildable
[ ] npm cache                     Rebuildable
[ ] Trash / Recycle Bin           Confirm
[-] System TEMP                   Review only
[-] Diagnostics / crash reports  Review only
```

Use:

```text
[ / ]     move
Space     toggle
Enter     clean selected
W         cancel / dashboard
```

Default-selected cleanup remains intentionally conservative.

## Reader

The 0.6 Reader behavior is retained:

- chapter-bounded pagination
- each chapter begins at the first text row of a page
- search stays inside the Reader surface
- G/T input stays inside the Reader surface
- responsive terminal resizing
- chapter/volume catalog
- chapter index cache
- reading-position resume

## Install

### Windows

```powershell
cd D:\NovelSlack
python -m pip install --upgrade .
novelslack --version
```

Start a TXT:

```powershell
novelslack --text "D:\path\to\book.txt"
```

### macOS / Linux

From the project directory:

```bash
python3 -m pip install --upgrade .
novelslack --version
```

Start a TXT:

```bash
novelslack --text ~/Downloads/book.txt
```

If the system Python does not permit user package installation, use a virtual
environment and run the same install command inside it.

## Help

```text
novelslack help
```

## Architecture

See `ARCHITECTURE.md` for the platform-adapter contract and cleanup boundaries.


## Book content

NovelSlack does not include, download, or distribute novels or other book
content. The Reader opens local TXT files supplied by the user. Use content
you are authorized to access.

## CI

The repository includes a GitHub Actions test matrix for:

- Windows
- macOS
- Ubuntu Linux

The workflow installs the package, verifies the CLI, and runs the unit-test
suite on each operating system.
