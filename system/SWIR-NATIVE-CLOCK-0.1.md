# SWIR Native Clock 0.1

SWIR Clock is a first-party native GTK4 System Edition utility for local time, alarms and calendar basics. It is installed as `/usr/local/bin/swir-clock`, uses application ID `dev.swir.Clock`, and is exposed from the fixed SWIR shell launcher. The same trusted executable also provides the unprivileged active-session alarm scheduler through `--alarm-service` with application ID `dev.swir.ClockAlarmService`.

## Verified scope

The implementation and dedicated CI gate verify a real GTK4 Clock window under Wayland, local timezone-aware clock/date display, GTK calendar basics, and bounded alarm creation with validated 24-hour values. Alarm labels are limited to 80 characters and the application accepts at most 32 alarms.

The visible Clock surface now consumes the bounded per-user SWIR settings store through `core_runtime.py`. English, Polish and Norwegian Bokmål chrome is reviewed in-tree with deterministic English fallback for unsupported language tags. The window, Clock/Alarms/Calendar tabs, timezone label, alarm editor, status text and active-session alarm popup are localized from the same selected catalog. The main window and alarm popup also apply the catalog text direction, while interactive alarm controls expose localized tooltips and retain keyboard focusability.

The Clock respects the validated per-user `clock24h` preference instead of forcing a single display convention. Date rendering is deterministic for the supported catalogs and does not depend on the host process locale. Dedicated Wayland evidence runs with a Polish user profile and 12-hour clock preference, verifies the localized date/window/actions, keyboard-focus/tool-tip surface and the time-format preference, then exercises the localized background alarm popup using that same profile. Pure self-tests additionally cover Norwegian Bokmål and unsupported-language English fallback.

Alarm definitions persist across Clock restarts in a strict versioned per-user state file. The store is bounded to 64 KiB, rejects unsupported/malformed records, refuses symlinked store and lock targets, writes through a same-directory temporary file with mode `0600`, fsyncs the file before atomic `os.replace`, and uses a same-user advisory `flock` around reads/mutations. UI writes preserve a scheduler-updated `lastFiredDate` instead of overwriting it from stale in-memory state.

Due alarms are claimed atomically: `lastFiredDate` is persisted while the exclusive store lock is held and before either notifier path returns the alarm. The foreground Clock and the background scheduler use that same claim function, preventing intentional duplicate delivery when both are alive. If existing state fails validation, the normal UI and service both fail closed rather than replacing malformed state.

The authenticated SWIR graphical-session launcher starts `/usr/local/bin/swir-clock --alarm-service` as the same unprivileged user after the Wayland socket is ready and tears it down with the session. The service stays resident without opening a window until a due alarm is atomically claimed, then maps a native GTK4 alarm window with a localized dismiss action. This makes saved alarms fire while the main Clock window is closed during an active SWIR user session without adding root, `sudo`, `pkexec`, network, package mutation or self-update paths.

The self-test verifies persistence, exact schema/size rejection, one-shot due claiming, preservation of a concurrent fire date, locale fallback and 12/24-hour formatting. The Wayland runtime gate separately maps the localized normal Clock and seeds a due alarm for the background service, then verifies the localized service window, active-session scope and persisted fire date. Debian 13 remains the target runtime using distribution-managed GTK4/Python packages.

## Current limitation

Background scheduling is intentionally scoped to the **active authenticated SWIR graphical session**. It is not a firmware/RTC wake alarm, does not claim delivery while the computer is powered off or suspended, does not run before login, and does not yet integrate with a separate desktop notification-history center. Session shutdown stops the service cleanly.

The supported in-tree Clock catalogs are currently English, Polish and Norwegian Bokmål. Unsupported language tags deliberately fall back to English until a reviewed catalog is added; this limitation is reported by runtime evidence rather than masked.

## Roadmap accounting

This materially improves the Product Baseline `Clock / alarms / calendar basics` depth and closes its current locale/time-format accessibility slice, but does not by itself complete the broad `essential native Linux application suite for dependable daily use` roadmap deliverable. Progress changes only when the authoritative `SWIR-OS-ARCHITECTURE.md` checklist criteria are actually satisfied.
