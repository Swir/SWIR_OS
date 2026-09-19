# SWIR Native Clock 0.1

SWIR Clock is a first-party native GTK4 System Edition utility for local time, alarms and calendar basics. It is installed as `/usr/local/bin/swir-clock`, uses application ID `dev.swir.Clock`, and is exposed from the fixed SWIR shell launcher.

## Verified scope

The implementation and dedicated CI gate verify a real GTK4 window under Wayland, local timezone-aware clock/date display, GTK calendar basics, and bounded alarm creation with validated 24-hour values. Alarm labels are limited to 80 characters and the application accepts at most 32 alarms.

Alarm definitions now persist across Clock restarts in a strict versioned per-user state file. The store is bounded to 64 KiB, rejects unsupported/malformed records, refuses a symlinked target, writes through a same-directory temporary file with mode `0600`, fsyncs the file before atomic `os.replace`, and preserves `lastFiredDate` so reopening Clock during the same minute/day does not intentionally re-fire a saved alarm. If existing state fails validation, Clock loads no alarms and refuses to overwrite that invalid file through the normal UI.

The self-test performs an actual persistence round trip plus unsupported-schema and oversized-store rejection. The Wayland runtime evidence repeats the persistence round trip after a real GTK4 window maps. The application has no network access, privileged command path, package mutation path or self-updater. The target runtime is Debian 13 with distribution-managed GTK4/Python packages.

## Current limitation

Alarm **definitions persist**, but alarm evaluation remains process-local. Saved alarms resume when SWIR Clock is opened again; they are not claimed to fire while Clock is closed. A session-level background scheduler and broader notification integration remain separate work.

## Roadmap accounting

This improves the Product Baseline `Clock / alarms / calendar basics` depth and removes the restart-loss gap, but does not by itself complete the broad `essential native Linux application suite for dependable daily use` roadmap deliverable. Progress changes only when the authoritative `SWIR-OS-ARCHITECTURE.md` checklist criteria are actually satisfied.
