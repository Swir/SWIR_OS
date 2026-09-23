# SWIR Native Diagnostics 0.1

Status: implemented System Edition read-only diagnostics foundation inside the native **SWIR System Monitor**, including reviewed runtime locale/accessibility evidence.

## Purpose

The Diagnostics tab gives the signed-in user a bounded, read-only view of basic platform identity, failed systemd units and recent warning/error records from the current boot. It is a troubleshooting surface, not a privileged repair console.

## Runtime contract

- Native GTK4 UI inside `system/apps/swir-system-monitor.py`.
- Platform identity comes from `/etc/os-release`, `/proc/version` and `/proc/uptime`.
- Failed-unit query is fixed to `/usr/bin/systemctl --failed --no-legend --plain`.
- Boot warning/error query is fixed to `/usr/bin/journalctl -b -p warning --no-pager -n 50 -o short-monotonic`.
- Commands run with `shell=False`, closed stdin, a 3-second timeout, a minimal controlled environment and no user-controlled argv interpolation.
- Captured command output is bounded to 64 KiB and journal display is additionally capped at 50 non-empty lines.
- Missing systemd/journald or an unavailable command produces an explicit unavailable/error state instead of enabling a fallback shell command.
- The **Diagnostics tab** has no direct privilege or mutation path. It cannot stop/start services, edit configuration or clear logs.
- Process termination is intentionally a separate Processes-tab contract documented in `SWIR-NATIVE-TASK-MANAGER-0.1.md`; it is limited to confirmed same-user `SIGTERM` and does not make Diagnostics mutable.

## Locale, accessibility and privacy

The real Diagnostics surface reads the bounded owner-only SWIR language preference and uses reviewed English, Polish and Norwegian Bokmål catalogs with deterministic English fallback. Diagnostics headings, refresh state, summaries and safety text are localized without changing the fixed command allowlist. The refresh action is keyboard-focusable and exposes a localized tooltip.

Runtime E2E evidence schema `swir.native-system-monitor-runtime-evidence/0.2` records only availability/status, bounded counters, command paths, safety limits and locale/accessibility assertions. Evidence is restricted to `XDG_RUNTIME_DIR`, written mode `0600`, and must never copy journal text, failed-unit rows, kernel strings or other diagnostic payload into CI evidence.

## Verification

`.github/workflows/system-native-diagnostics.yml` compiles the application, checks the fixed-command and no-elevation diagnostics policy, persists a Norwegian Bokmål SWIR user profile, maps the real GTK4 window on headless Wayland, then validates selected catalog, localized surface, focus/tooltips, evidence permissions and the bounded diagnostic evidence. The native Task Manager workflow separately verifies process-control safety, while the native-core-app workflow continues to cover the process/resource view.

## Scope boundary

This foundation intentionally does **not** close the umbrella roadmap item for a complete dependable daily-use native application suite. Future privileged repair actions, if introduced, must use explicit privileged brokers with user authorization and a separate auditable contract rather than extending this read-only Diagnostics tab with direct elevation.
