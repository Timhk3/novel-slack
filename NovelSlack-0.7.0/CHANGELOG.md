# Changelog

## 0.7.0

- Added explicit Windows, macOS and Linux platform adapters.
- Removed native OS probing and cleanup logic from `activity.py`.
- Removed OS-specific Trash / Recycle Bin cleanup from `maintenance.py`.
- Preserved the existing Windows WinAPI/tasklist backend behind the Windows adapter.
- Added macOS `vm_stat` / `ps` / `~/.Trash` integration.
- Added Linux `/proc` / XDG Trash integration.
- Added per-platform state, cache, TEMP, package-cache and diagnostic locations.
- Added current-UID filtering for automatic POSIX TEMP cleanup.
- Added per-platform polling policies to keep native probes low-load.
- Added platform-adapter injection to the maintenance worker for isolated testing.
- Added adapter/factory/Linux-native/Trash regression tests.

## 0.6.3

- Added hard chapter boundaries to Reader pagination.
- Chapter headings always begin a new Reader page.
- Prevented the next chapter heading from leaking onto the previous chapter's last page.
- Unified next/previous page, chapter jump, G page navigation, and resize alignment on one page grid.
- Added regression tests for chapter starts, chapter ends, previous-page behavior, page numbering, and resize realignment.

## 0.6.2

- Reworked G / Search / T as in-screen Reader prompts.
- Escape now cancels Reader input without leaving the Reader surface.
- Added high-confidence volume-structure validation.
- Added heading-title boundary cleanup without hard title truncation.
- Added support for colon/dash heading separators.
- Bumped text-index cache schema to invalidate stale parser output.

## 0.6.1

- Added terminal resize detection.
- Rebuilds the Rich alternate-screen surface on width/height changes.
- Explicitly clears the alternate screen after surface recreation.
- Added responsive Reader page density based on terminal cell width.
- Added responsive Chapter / Volume Catalog viewport sizing.
- Added responsive Dashboard history row count.
- Prevented narrow maintenance rows from expanding the dashboard vertically.

## 0.6.0

- Unified screen/mode lifecycle behind one transition function.
- Replaced per-mode terminal surfaces with one alternate-screen Rich Live surface.
- Added dirty Dashboard rendering and reduced input/worker polling.
- Added worker exception containment and recovery.
- Added cleanup candidate manifests and scan-result reuse.
- Added Cleanup Review with safe defaults and optional rebuildable-cache cleanup.
- Removed forced working-set trimming from the main UX.
- Added lightweight chapter/volume index caching.
- Added signature-aware exact/chapter/ratio reading resume.
- Added detected Volume → Chapter two-level catalog.
- Added focused transition, cleanup-manifest, cache, and worker tests.
