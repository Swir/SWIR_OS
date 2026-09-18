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

## SWIR Hardware & Driver Center

`system/apps/swir-hardware-center.py` is an unprivileged GTK4 hardware-diagnostics surface backed by the existing trusted Hardware Service, Hardware Catalog and Driver Center resolver.

Current verified behavior:

- starts as `dev.swir.HardwareCenter` on Wayland;
- obtains a bounded read-only `swir.driver-center-report/0.1` through the fixed `/usr/bin/node` runtime and the root-owned staged `driver-center-report.mjs` entry point;
- shows Linux distribution/kernel facts, PCI/USB inventory, driver binding state, catalog matches and bounded recommended review operations;
- exposes fwupd/LVFS availability as diagnostic capability state without pretending that firmware support exists for every device;
- rejects reports that are not explicitly read-only, enable automatic mutation, contain Driver Center policy violations or exceed parser safety bounds;
- performs report collection away from the GTK main loop so hardware enumeration does not freeze the window;
- exposes no install/apply/module-load/firmware-flash control and performs no direct privileged operation;
- preserves the Linux-first source policy: kernel in-tree drivers, `linux-firmware`, signed distribution repositories, fwupd/LVFS where supported and allowlisted official vendor repositories only;
- never turns unknown hardware into an arbitrary binary download and never treats Windows kernel drivers as a generic Linux hardware path.

The existing journaled Driver Center mutation coordinator remains a separate privileged backend boundary. This UI milestone intentionally provides real native diagnostics first; brokered package/firmware apply UX must be connected only after exact-operation confirmation, authorization, journal and recovery semantics remain intact.

## SWIR Software Center

`system/apps/swir-software-center.py` is an unprivileged GTK4 package-discovery and brokered-install surface backed by `package_status_runtime.py`, `package_mutation_flow.py` and the authenticated package transaction broker.

Current verified behavior:

- starts as `dev.swir.SoftwareCenter` on Wayland;
- shows a bounded snapshot of packages installed through dpkg;
- performs bounded literal searches against the local APT cache;
- keeps metadata queries away from the GTK main loop;
- offers Install only when the SWIR package broker is available;
- requests an exact dependency-aware broker preview, displays the plan/digest and requires explicit user confirmation before authorization;
- uses a single-use confirmation intent so replay/double-click commit attempts fail closed;
- delegates peer/session-bound Polkit authorization and journaled mutation to the root-owned broker instead of invoking APT, `pkexec`, `sudo` or a shell from GTK;
- fails closed if the broker recomputes a different plan.

This is still not a completed app store. Package details, categories, screenshots, remove/update UX, Flatpak/AppImage UX and transaction-history presentation remain future work.

## SWIR Update Center

`system/apps/swir-update-center.py` is an unprivileged GTK4 update-planning surface backed by the same read-only package runtime and authenticated transaction path.

Current verified behavior:

- starts as `dev.swir.UpdateCenter` on Wayland;
- asks the fixed `/usr/bin/apt-get` executable for a `--simulate --no-download` dist-upgrade using `Debug::NoLocking=true` for discovery only;
- parses and displays a bounded list of locally known candidate upgrades;
- performs no repository refresh from the GTK process;
- can submit only broker-supported package mutations through the same preview → explicit confirmation → peer-bound Polkit → journaled commit boundary;
- does not execute privileged APT, `pkexec`, `sudo` or arbitrary shell commands from the UI;
- keeps bulk/dist-upgrade mutation disabled until that path has its own separately verified broker contract.

Secure repository refresh, complete bulk update UX, progress/reboot coordination and recovery/rollback presentation remain future work even though the underlying package/recovery architecture already owns journaled mutation and reconciliation semantics.

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

`system/apps/hardware_center_runtime.py` is a bounded adapter to the existing JavaScript Driver Center report. Production uses only `/usr/bin/node` plus the staged root-owned `/usr/local/lib/swir/hardware/driver-center-report.mjs`; the Python GTK process validates the report schema and fail-closed policy before displaying it. A test-only report path override is accepted only while `SWIR_APP_E2E=1` and must resolve to an absolute non-symlink regular file.

## Runtime verification

`.github/workflows/system-native-core-apps-contract.yml` verifies the established native suite. `.github/workflows/system-native-software-update-centers.yml` and `.github/workflows/system-package-ui-mutation-contract.yml` verify package discovery plus the brokered Software/Update mutation boundary. `.github/workflows/system-native-hardware-center.yml` verifies Hardware Center parsing/safety invariants and maps the real GTK4 window on headless Weston while loading the trusted Driver Center report.

The Wayland gates require real windows and bounded runtime evidence. The graphical System Edition provisioning path installs the applications and their exact trusted runtime dependencies into the image only after source/package checks succeed. Hardware Center provisioning stages the Driver Center report modules, Hardware Catalog and trusted-source policy as root-owned read-only runtime data; it does not stage a direct privileged hardware-mutation shortcut into the GTK application.

## Roadmap accounting

This milestone does **not** mark `essential native Linux application suite for dependable daily use` complete. The product baseline still requires the full coherent suite, including a native Browser, media/image/document/archive applications, calculator/screenshot/clock basics, deeper diagnostics and backup/recovery integration. Progress changes only when the authoritative `SWIR-OS-ARCHITECTURE.md` checklist is legitimately satisfied.
