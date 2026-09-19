# SWIR Native Clock 0.1

SWIR Clock is a first-party native GTK4 System Edition utility for local time, alarms and calendar basics. It is installed as `/usr/local/bin/swir-clock`, uses application ID `dev.swir.Clock`, and is exposed from the fixed SWIR shell launcher. The same trusted executable also provides the unprivileged active-session alarm scheduler through `--alarm-service` with application ID `dev.swir.ClockAlarmService`.

## Verified scope

The implementation and dedicated CI gate verify a real GTK4 Clock window under Wayland, local timezone-aware clock/date display, GTK calendar basics, and bounded alarm creation with validated 24-hour values. Alarm labels are limited to 80 characters and the application accepts at most 32 alarms.

Alarm definitions persist across Clock restarts in a strict versioned per-user state file. The store is bounded to 64 KiB, rejects unsupported/malformed records, refuses symlinked store and lock targets, writes through a same-directory temporary file with mode `0600`, fsyncs the file before atomic `os.replace`, and uses a same-user advisory `flock` around reads/mutations. UI writes preserve a scheduler-updated `lastFiredDate` instead of overwriting it from stale in-memory state.

Due alarms are now claimed atomically: `lastFiredDate` is persisted while the exclusive store lock is held and before either notifier path returns the alarm. The foreground Clock and the background scheduler use that same claim function, preventing intentional duplicate delivery when both are alive. If existing state fails validation, the normal UI and service both fail closed rather than replacing malformed state.

The authenticated SWIR graphical-session launcher starts `/usr/local/bin/swir-clock --alarm-service` as the same unprivileged user after the Wayland socket is ready and tears it down with the session. The service stays resident without opening a window until a due alarm is atomically claimed, then maps a native GTK4 alarm window with a Dismiss action. This makes saved alarms fire while the main Clock window is closed during an active SWIR user session without adding root, `sudo`, `pkexec`, network, package mutation or self-update paths.

The self-test verifies persistence, exact schema/size rejection, one-shot due claiming and preservation of a concurrent fire date. The Wayland runtime gate separately maps the normal Clock and seeds a due alarm for the background service, then verifies the service window, active-session scope and persisted fire date. Debian 13 remains the target runtime using distribution-managed GTK4/Python packages.

## Current limitation

Background scheduling is intentionally scoped to the **active authenticated SWIR graphical session**. It is not a firmware/RTC wake alarm, does not claim delivery while the computer is powered off or suspended, does not run before login, and does not yet integrate with a separate desktop notification-history center. Session shutdown stops the service cleanly.

## Roadmap accounting

This materially improves the Product Baseline `Clock / alarms / calendar basics` depth and removes the "Clock window must remain open" gap, but does not by itself complete the broad `essential native Linux application suite for dependable daily use` roadmap deliverable. Progress changes only when the authoritative `SWIR-OS-ARCHITECTURE.md` checklist criteria are actually satisfied.
