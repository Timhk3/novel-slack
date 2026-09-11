# NovelSlack Architecture — 0.7.0

## Product boundary

NovelSlack has two capabilities:

1. **Reader** — TXT reading, search, chapter-bounded paging,
   volume/chapter navigation, persistent resume and cached indexes.
2. **System Maintenance** — low-load host monitoring, incremental storage
   indexing, cleanup review and explicit cleanup.

The Reader/UI layer is platform-independent. Native system behavior is isolated
behind one of three platform adapters.

## Platform adapter layer

```text
novelslack/
├── platforms/
│   ├── base.py
│   ├── factory.py
│   ├── windows.py
│   ├── macos.py
│   └── linux.py
├── activity.py
├── maintenance.py
├── reader.py
├── input.py
├── ui.py
└── app.py
```

`activity.py` and `maintenance.py` do not branch on Windows/macOS/Linux.
They only call the adapter contract.

### Adapter contract

Each adapter supplies:

```text
create_cpu_sampler()
memory_status()
process_count()
process_memory_summary()

paths()
state_dir()
app_cache_dir()

trash_status()
empty_trash()

is_safe_user_temp_candidate()
```

The adapter also owns low-load polling intervals for native probes.

## Windows adapter

Native sources are preserved from the Windows implementation that preceded the
refactor:

- CPU: `GetSystemTimes`
- memory: `GlobalMemoryStatusEx`
- process count: Toolhelp process snapshot
- process-memory ranking: `tasklist`
- Recycle Bin status: `SHQueryRecycleBinW`
- Recycle Bin cleanup: `SHEmptyRecycleBinW`
- state: `%APPDATA%\NovelSlack`
- app cache: `%LOCALAPPDATA%\NovelSlack`
- user TEMP: current user's TEMP
- system TEMP: `%WINDIR%\Temp`
- pip/npm: Windows user cache locations
- diagnostics: CrashDumps + WER

## macOS adapter

Low-overhead native sources:

- CPU: normalized `getloadavg()` estimate
- memory: `vm_stat`, with physical-memory total cached from `sysctl hw.memsize`
- process count / memory ranking: `ps`
- Trash: `~/.Trash`
- state: `~/Library/Application Support/NovelSlack`
- app cache: `~/Library/Caches/NovelSlack`
- user TEMP: Python/macOS user temp
- system TEMP: `/private/var/tmp`
- pip cache: `~/Library/Caches/pip`
- npm cache: `~/.npm`
- diagnostics: `~/Library/Logs/DiagnosticReports`

macOS subprocess-backed probes use slower polling intervals to avoid turning
monitoring into system load.

## Linux adapter

Native sources avoid third-party dependencies:

- CPU: `/proc/stat`
- memory: `/proc/meminfo`
- process count / memory ranking: `/proc`
- Trash: FreeDesktop user Trash under `$XDG_DATA_HOME/Trash`
- state: `$XDG_STATE_HOME/NovelSlack`
- app cache: `$XDG_CACHE_HOME/NovelSlack`
- user TEMP: Python temp directory
- system TEMP: `/var/tmp`
- pip cache: `$XDG_CACHE_HOME/pip`
- npm cache: `~/.npm`
- diagnostics: `/var/crash` and user coredump directory when present

For shared POSIX temp directories, automatic TEMP cleanup only accepts files
owned by the current UID.

## Unified state machine

```text
LIVE
├── READING
│   ├── VOLUME_CATALOG
│   └── CHAPTER_CATALOG
├── STATUS
└── CLEANUP_REVIEW
    └── MAINTENANCE
```

All mode changes pass through `NovelSlackApp._transition()`.

## Cleanup safety

Default-selected cleanup remains deliberately narrow:

- old user TEMP files that were indexed and revalidated
- regenerable cache files inside the selected workspace

Explicit opt-in:

- pip cache
- npm cache
- Trash / Recycle Bin

Review only:

- system TEMP
- diagnostics / crash reports

The cleanup engine revalidates candidate path, size and modification time before
deleting indexed TEMP/workspace candidates.

## Low-load policy

- one maintenance worker
- incremental filesystem slices
- dirty UI rendering
- scan budget shrinks under CPU/memory pressure
- Reader/catalog modes pause background scanning
- macOS subprocess-backed probes run at reduced frequency
- POSIX Trash scans run at reduced frequency
- no network telemetry
- no process killing
- no working-set or standby-list purging
