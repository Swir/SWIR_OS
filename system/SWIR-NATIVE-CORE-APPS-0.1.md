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

## SWIR Terminal

`system/apps/swir-terminal.py` is a first-party GTK4 terminal using Debian's GTK4 VTE runtime.

Current verified behavior:

- starts as `dev.swir.Terminal` on Wayland;
- attaches a real VTE pseudo-terminal instead of emulating a terminal in a text box;
- resolves the current account's configured executable login shell with `/bin/bash` and `/bin/sh` as fixed fallbacks;
- starts the shell in the user's home directory;
- keeps a bounded 10,000-line scrollback;
- does not interpolate user text into a shell command from the launcher;
- exposes no built-in `sudo`, `pkexec`, root-login or privilege shortcut;
- receives VTE only from the signed Debian package repositories used by the image build.

The shell itself naturally executes commands entered by the logged-in user. This milestone does not grant the terminal any privilege beyond that user's normal Linux account and does not bypass the existing Polkit/broker boundaries.

## SWIR Notes

`system/apps/swir-notes.py` is an unprivileged first-party GTK4 notes editor.

Current verified behavior:

- starts as `dev.swir.Notes` on Wayland;
- loads and saves one user note without depending on a browser runtime;
- stores the note below `${XDG_DATA_HOME:-~/.local/share}/swir/notes.txt`;
- keeps the SWIR data directory at mode `0700` and the note at mode `0600`;
- rejects a symlinked SWIR data directory or notes file instead of following it;
- bounds note payloads to 1 MiB;
- writes atomically through a same-directory temporary file, `fsync` and `os.replace`;
- performs no privileged operation.

This is a dependable native Notes foundation, not yet a general-purpose text editor. Multiple documents, rich formatting, file associations, search and collaborative features remain outside this milestone.

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

## SWIR Network Center

`system/apps/swir-network-center.py` is an unprivileged GTK4 NetworkManager status surface.

Current verified behavior:

- starts as `dev.swir.NetworkCenter` on Wayland;
- invokes only the fixed `/usr/bin/nmcli` binary with fixed read-only query argument vectors and `shell=False`;
- bounds each query to four seconds and bounds the visible device list to 100 rows;
- displays NetworkManager's overall state plus device name, type, state and active connection when the system service is reachable;
- reports a bounded error instead of pretending connectivity when NetworkManager is unavailable;
- exposes a refresh action but no connect/disconnect, credential, radio, route, DNS or privileged mutation controls.

Connection mutation remains future work behind explicit NetworkManager/Polkit policy and must not be confused with this read-only observability milestone.

## SWIR Software Center

`system/apps/swir-software-center.py` is an unprivileged GTK4 package-discovery and installed-package surface backed by `package_status_runtime.py`.

Current verified behavior:

- starts as `dev.swir.SoftwareCenter` on Wayland;
- shows a bounded snapshot of packages installed through dpkg;
- performs bounded literal searches against the local APT cache;
- invokes only allowlisted absolute package-tool paths, never a shell command;
- runs metadata queries away from the GTK main loop so slow package metadata does not freeze the window;
- exposes no install, remove, repository-edit or privilege-escalation control;
- explicitly leaves mutation to the existing journaled SWIR package transaction service and Polkit boundary.

This is the native Software Center foundation, not a completed app store. Package details, categories, screenshots, transaction confirmation/progress, Flatpak/AppImage UX and transaction-history presentation remain future work. Adding mutation here requires a brokered request contract; directly invoking privileged APT from the GTK process is not acceptable.

## SWIR Update Center

`system/apps/swir-update-center.py` is an unprivileged GTK4 update-planning surface backed by the same read-only package runtime.

Current verified behavior:

- starts as `dev.swir.UpdateCenter` on Wayland;
- asks the fixed `/usr/bin/apt-get` executable for a `--simulate --no-download` dist-upgrade using `Debug::NoLocking=true`;
- parses and displays a bounded list of locally known candidate upgrades;
- performs no repository refresh and initiates no network access;
- performs no package mutation and exposes no Apply button;
- makes the separation between read-only planning and SWIR's privileged journaled transaction path explicit in the UI.

This is not yet a complete updater. Secure repository refresh, authenticated transaction submission, progress/reboot coordination, recovery and rollback UX remain owned by the existing package/recovery architecture and must be connected without weakening those controls.

## SWIR System Monitor

`system/apps/swir-system-monitor.py` is an unprivileged GTK4 resource/process viewer.

Current verified behavior:

- starts as `dev.swir.SystemMonitor` on Wayland;
- reads Linux memory totals from `/proc/meminfo`;
- reads uptime from `/proc/uptime` and load averages from the kernel interface exposed by Python;
- enumerates visible processes through read-only `/proc/<pid>` metadata;
- displays PID, process name and resident memory;
- bounds the visible process list to 200 rows and tolerates processes disappearing while the snapshot is collected;
- exposes no process-kill, service mutation or privileged control path.

Process termination, service control, cgroup inspection and privileged diagnostics remain future brokered capabilities and are intentionally not implied by this read-only monitor.

## Shared runtime policy

`system/apps/core_runtime.py` keeps common non-UI behavior testable independently from GTK. It provides deterministic read-only directory snapshots plus a validated, bounded and atomic user-settings store. `core_runtime.selftest.py` covers normal and hostile/symlink cases.

`system/apps/package_status_runtime.py` is a separate, deliberately read-only package metadata boundary. It allowlists `/usr/bin/apt-cache`, `/usr/bin/apt-get` and `/usr/bin/dpkg-query`, caps execution time and captured output, escapes Software Center search terms before passing them to `apt-cache`, bounds visible rows, and permits only APT simulation for update planning. `package_status_runtime.selftest.py` verifies input bounds and deterministic parsing without modifying the host package database.

## Runtime verification

`.github/workflows/system-native-core-apps-contract.yml` verifies the established native suite. `.github/workflows/system-native-software-update-centers.yml` adds dedicated policy/parser checks plus real GTK4 startup of Software Center and Update Center on a headless Weston Wayland compositor.

The Wayland gates require real windows and bounded runtime evidence. The package UI gate additionally verifies that mutation controls and repository refresh are absent, package rows are bounded, required read-only package tools are present and the shell/provisioning paths include both applications. The graphical System Edition provisioning path installs the apps and shared package-status runtime into the image only after trusted-source/package checks succeed.

## Roadmap accounting

This milestone does **not** mark `essential native Linux application suite for dependable daily use` complete. The product baseline still requires the full coherent suite, including a mutation-capable but brokered Software/Store and Update Center experience, Hardware/Driver Center UI, native Browser, media/image/document/archive applications, diagnostics and backup/recovery integration. Progress changes only when the authoritative `SWIR-OS-ARCHITECTURE.md` checklist is legitimately satisfied.
