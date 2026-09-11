# Privacy

NovelSlack is local-only.

It does not upload books, telemetry, machine state, cleanup results, reading
history, process lists, or cache inventories. Runtime network access is not
required.

Local state may contain:

- last book path
- last workspace path
- reading position
- lightweight chapter/volume index cache
- local file signatures used to validate resume/index state

The maintenance dashboard may display:

- CPU and memory pressure
- free disk space
- process count
- largest process names during low-frequency process-health summaries
- local TEMP/cache/Trash or Recycle Bin size estimates

Review screenshots or copied terminal output before publishing them because
runtime process names and local machine information can appear on screen.

Cleanup is explicit.

Default selected:

- user TEMP files older than 30 days that were scanned and revalidated
- regenerable cache files inside the selected workspace

On macOS/Linux, safe user-TEMP candidates must be owned by the current UID.

Optional, explicit selection:

- pip cache
- npm cache
- Trash / Recycle Bin

Review only:

- system TEMP
- diagnostics / crash reports
