# SWIR Native Core Apps 0.1

This document describes the first daily-use native Linux applications shipped with the SWIR OS System Edition shell. They are real GTK4 applications, not Web/PWA wrappers, but they intentionally cover only a narrow verified baseline and do **not** complete the full native-application-suite roadmap item.

## SWIR Files

`system/apps/swir-files.py` is an unprivileged GTK4 file manager foundation.

Current verified behavior:

- starts as `dev.swir.Files` on Wayland;
- defaults to the current user's home directory;
- performs read-only directory enumeration through the shared `core_runtime.py` policy;
- does not follow symlinks while classifying directory entries;
- supports Back, Up, Home, Refresh and hidden-file visibility controls;
- navigates readable directories without invoking a shell;
- deliberately does not open arbitrary files until native Default Apps/file-association integration is available;
- performs no privileged operation.

This is not yet a complete File Manager product. Copy/move/delete, removable volumes, previews, search, trash and native Default Apps handoff remain future work.

## SWIR Settings

`system/apps/swir-settings.py` is an unprivileged GTK4 Control Center foundation for per-user preferences.

Current verified behavior:

- starts as `dev.swir.Settings` on Wayland;
- edits an allowlisted language preference, 12/24-hour clock preference and a narrow appearance preference;
- validates the settings schema before write;
- persists settings atomically under `${XDG_CONFIG_HOME:-~/.config}/swir/settings.json`;
- maintains the SWIR settings directory at mode `0700` and the settings file at mode `0600`;
- rejects a symlinked settings file/directory instead of following it;
- does not expose privileged system configuration.

Privileged settings such as users, storage, firmware, system services and package mutation remain behind dedicated brokers/Polkit policies and are not implemented by this user-settings foundation.

## Shared runtime policy

`system/apps/core_runtime.py` keeps non-UI behavior testable independently from GTK. It provides deterministic read-only directory snapshots plus a validated, bounded and atomic user-settings store. `core_runtime.selftest.py` covers normal and hostile/symlink cases.

## Runtime verification

`.github/workflows/system-native-core-apps-contract.yml` runs two layers:

1. standard-library policy self-tests and Python compilation;
2. real GTK4 application startup against a headless Weston Wayland compositor, requiring each app to map a window and emit owner-only runtime evidence.

The graphical System Edition provisioning path installs these scripts into the image only after source and package checks succeed. The SWIR shell uses fixed executable paths and never builds launcher commands from user-controlled shell strings.

## Roadmap accounting

This milestone does **not** mark `essential native Linux application suite for dependable daily use` complete. The product baseline still requires the full coherent suite, including browser, media, image, PDF/archive, software/update, system monitor, diagnostics and backup/recovery integration. Progress changes only when the authoritative `SWIR-OS-ARCHITECTURE.md` checklist is legitimately satisfied.
