# SWIR Native Daily-Use Suite Gate 0.1

## Scope

This gate reconciles the **System Edition essential-utility list** in `SWIR-PRODUCT-BASELINE-1.0.md` with the native applications actually present in `Swir/SWIR_OS`. It is intentionally an integration gate, not a second roadmap and not a completion claim.

The machine-readable inventory is `system/apps/native-daily-suite.json`. `system/apps/verify-native-daily-suite.py` verifies that every baseline capability is represented by trusted native source, is staged into the graphical System Edition image, is reachable through an explicitly verified native entry point, and is explicitly bound to an in-repository runtime-evidence workflow.

Most capabilities are reachable directly from the fixed native SWIR Shell launcher allowlist. Text Editor is intentionally verified through its native desktop registration plus the System Settings **Default Apps → text/code** category because opening a local text/code file through its registered handler is the canonical daily-use path. The verifier fails closed if that desktop registration, staged executable, MIME coverage or Settings binding disappears.

## Covered baseline capabilities

The Product Baseline contains 19 essential-utility rows. `Text Editor / Notes` is one baseline row but is implemented by two distinct first-party native applications, so the machine-readable inventory intentionally tracks **20 explicit implementation capabilities**: Files, Settings, Terminal, Software, Update Center, Hardware & Driver Center, Network Center, Browser, Text Editor, Notes, Player, Photo Studio/Image Viewer, PDF Viewer, Archive Manager, Calculator, Screenshot Tool, Clock/calendar basics, Task Manager/System Monitor, Logs/Diagnostics, and Backup/Restore with recovery entry points.

A single trusted application may satisfy more than one UI surface only when that is the real implementation. For example, `swir-system-monitor.py` provides both process monitoring and its read-only Diagnostics tab, while Archive Manager is a dedicated GTK4 application mode inside the trusted `swir-files` executable.

## Runtime-evidence authority audit

Every explicit implementation capability declares an `evidenceWorkflow` in `system/apps/native-daily-suite.json`. The current inventory resolves to first-party runtime/security workflows: the shared core-apps and Software/Update gates plus dedicated Settings/Default Apps, Hardware, Browser, **Text Editor**, Player, Photo Studio, PDF, Archive, Calculator, Screenshot, Clock, Task Manager, Diagnostics and Backup/Restore authorities.

The dedicated Text Editor authority performs three layers of evidence: pure file-policy self-tests, a real headless Wayland GTK4 mapping that edits and atomically saves an existing local document plus exclusively creates a new owner-only document, and a Debian 13 target-runtime check. It explicitly rejects remote URI input, symlink and hardlink input, oversized documents, stale inode identity during overwrite, and replacing an existing Save As target. The Wayland authority also verifies the bounded per-user locale selection, reviewed localized controls, keyboard-focus/tool-tip accessibility and deterministic English fallback without weakening the file-safety boundary.

The Settings/Default Apps authority now runs the real Settings window from a persisted Polish user preference and verifies the selected catalog, localized window/language-section/save controls, text direction and owner-only settings storage before exercising all six Gio default-app categories. The same workflow still proves that default-handler mutation is per-user and explicit rather than a package or privilege shortcut.

The Hardware Center authority now also verifies the bounded per-user locale selection on the real Wayland surface, reviewed English/Polish/Norwegian Bokmål catalogs, deterministic English fallback, keyboard-focus/tool-tip accessibility and the existing read-only driver/firmware boundary in one gate. Localization does not add mutation controls, arbitrary downloads, Windows kernel-driver fallback or privilege elevation.

The Browser authority verifies the bounded per-user locale selection against reviewed English/Polish/Norwegian Bokmål catalogs, deterministic English fallback, localized Wayland chrome and keyboard-focus/tool-tip accessibility while preserving the existing ephemeral private-session, explicit permission, unsafe-scheme blocking, bounded owner-only history/bookmark and Software Center handoff boundaries. Localization does not add a browser self-updater, direct package mutation or a privileged path.

The Player authority now runs the real GTK4/GStreamer surface from a persisted Polish user preference and verifies the selected English/Polish/Norwegian Bokmål catalog, deterministic English fallback, localized window chrome, text direction and keyboard-focus/tool-tip accessibility while still prerolling a generated local media file. The same runtime evidence keeps the owner-only bounded library/playlists, MPRIS2 media-key integration, Gio notifications, local-file-only input and system-managed codec/update path in force; localization adds no self-updater, remote media loader or privilege path.

The Task Manager and Diagnostics authorities now exercise the shared real GTK4 System Monitor with persisted Polish and Norwegian Bokmål user profiles. They verify reviewed EN/PL/NO catalogs, deterministic English fallback, localized process/diagnostic chrome, text direction, keyboard-focus/tool-tip accessibility and owner-only runtime evidence. The existing same-user PID/start-time identity binding, explicit-confirmation SIGTERM boundary, ancestor protection, fixed absolute read-only diagnostic commands, no-shell execution, bounded timeout/output and no-elevation contract remain unchanged.

The integration verifier fails closed if an evidence authority disappears, moves outside `.github/workflows`, stops being a pull-request gate, loses read-only repository permissions, no longer references the native source it claims to cover, or no longer contains a runtime/self-test execution marker. This prevents a capability from remaining in the umbrella inventory on source/staging evidence alone after its real runtime authority has been removed.

This audit proves **coverage of runtime-evidence authorities**, not that every product-depth requirement is automatically complete. The dedicated workflows remain responsible for the actual behavior and security assertions of their applications.

## What the verifier proves

The gate fails closed when:

- a required implementation capability disappears or is duplicated in the manifest;
- an essential source becomes HTML/PWA/JavaScript instead of native Linux application source;
- a source or companion is missing, symlinked, outside the repository, syntactically invalid, or no longer GTK4 based;
- graphical-image provisioning stops staging a required native executable;
- a shell-routed capability disappears from the fixed SWIR Shell launcher;
- Text Editor loses its native desktop registration, required MIME coverage, staged executable or first-party Default Apps binding;
- a capability loses its declared runtime-evidence workflow or that workflow stops gating pull requests, referencing the native source or running runtime/self-test evidence;
- high-risk implementations lose key safety markers, such as Archive Manager no-follow/exclusive extraction, Screenshot portal mediation, Text Editor no-follow/exclusive-create and inode-identity checks, same-user Task Manager identity binding, or read-only diagnostics command allowlisting;
- Backup/Restore loses the recovery companions used by System Edition;
- Photo Studio loses the Product Baseline implementation markers for rectangular crop, color transforms, bounded text annotation or bounded drawing/annotation.

CI additionally executes the real Archive Manager hostile-input/self-test and the Recovery Mode provisioning self-test. Photo Studio retains its separate dedicated Wayland/Debian 13 workflow, which is the runtime authority for real pixel changes, source immutability and export behavior. Settings has a dedicated Default Apps runtime authority for all six categories — browser, media, image, PDF, text/code and archive — using final-image staged handlers and real per-user Gio association mutations inside an isolated Wayland profile.

Clock has a dedicated runtime authority for local time/calendar/alarm behavior. Alarm definitions survive Clock restarts through bounded owner-only atomic state, and a separately exercised active-session alarm service claims due alarms atomically and maps an alarm window even when the Clock window is closed. The same authority uses a bounded per-user settings profile to verify localized English/Polish/Norwegian Bokmål surfaces, deterministic English fallback, the validated 12/24-hour preference, localized date rendering and keyboard-focus/tool-tip accessibility without weakening the alarm-store boundary. Sleep/wake catch-up and pre-login alarms remain explicitly unclaimed.

## Security boundary

This gate does **not** introduce privilege elevation, arbitrary shell execution, remote payload loading, driver downloads, package-manager bypasses, or destructive disk actions. It only verifies already-reviewed first-party native application and recovery integration.

The gate never replaces the dedicated per-application workflows. Browser, Text Editor, Player, Photo Studio, PDF, Screenshot, Backup/Restore, Task Manager and the remaining native utilities retain their own runtime/security tests.

## Roadmap accounting

Passing this gate does **not** automatically complete `essential native Linux application suite for dependable daily use`.

Photo Studio 0.3 closes the previously documented image-editor depth gap by implementing and separately runtime-verifying user-selectable crop, exposure/brightness/contrast, color controls, filters, bounded text, bounded line drawing/annotation, undo/redo and common-format export. The integration verifier fails closed if those implementation markers disappear.

The runtime-evidence coverage is machine-audited across all explicit implementation capabilities. Native Default Apps has separately verified browser, media, image, PDF, text/code and archive categories with final-image staging. Text Editor has a dedicated local-file runtime authority and safe New/Open/Save/Save As behavior. Clock alarms persist across restarts and the active-session background service is runtime-verified with the Clock window closed.

The locale/accessibility closure now spans the real supported first-party application surfaces rather than inventory claims. Calculator, Notes, Network Center, Text Editor, Clock, Terminal, Screenshot Tool, Software Center, Update Center, Files, Archive Manager, Hardware & Driver Center, PDF Viewer, Backup/Restore, Settings, Browser, Player, Photo Studio, Task Manager and Diagnostics consume the bounded per-user SWIR language preference, expose reviewed English/Polish/Norwegian Bokmål chrome with safe English fallback, and carry runtime evidence for localized Wayland surfaces plus keyboard-focus/tool-tip accessibility where those controls apply. Clock additionally consumes the validated per-user 12/24-hour preference and verifies localized date output for the selected catalog. Network Center remains read-only; Notes keeps its owner-only atomic storage boundary; Text Editor retains its no-follow/exclusive-create/inode-identity overwrite protections; Clock retains its owner-only atomic alarm store and active-session-only service boundary; Terminal preserves its no-interpolation PTY/VTE boundary; Screenshot remains portal-mediated; Software/Update keep the brokered package transaction path; Files/Archive preserve no-follow and hostile-archive extraction defenses; Hardware Center remains read-only with trusted-source inventory only; PDF Viewer remains local-file-only and read-only; Backup/Restore retains bounded owner-only storage and recovery boundaries; Settings remains per-user only with explicit Gio default-handler changes; Browser retains explicit website permissions, unsafe-scheme blocking, ephemeral private sessions and package/update separation while localized; Player retains local-file-only playback, owner-only bounded library/playlists, MPRIS2 integration and system-managed codec updates while localized; Photo Studio keeps local-file-only non-destructive editing and explicit atomic export; Task Manager retains same-user identity-bound SIGTERM only; and Diagnostics remains fixed-command, bounded and read-only.

Photo Studio closes the last identified locale/accessibility surface with reviewed EN/PL/NO chrome, deterministic English fallback, applied text direction, keyboard focus/tool-tip evidence and the existing local-file/non-destructive safety boundary. Exact-head acceptance snapshot `2656cba4884220084a9411e424530bc9e7e45381` passed all ten relevant PR workflows, including System Native Daily Suite plus the dedicated Browser, Player, Photo Studio, Task Manager, Diagnostics, Text Editor, Default Apps, Core Apps and System Edition contract gates. The roadmap completion was recorded only after that green snapshot; together, those dedicated and umbrella checks satisfy the `essential native Linux application suite for dependable daily use` deliverable without implying full System Edition release readiness or physical-hardware qualification.

The canonical checklist and percentage remain exclusively in `SWIR-OS-ARCHITECTURE.md`.
