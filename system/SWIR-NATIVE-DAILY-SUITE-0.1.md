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

Clock has a dedicated runtime authority for local time/calendar/alarm behavior. Alarm definitions survive Clock restarts through bounded owner-only atomic state, and a separately exercised active-session alarm service claims due alarms atomically and maps an alarm window even when the Clock window is closed. The same authority now uses a bounded per-user settings profile to verify localized English/Polish/Norwegian Bokmål surfaces, deterministic English fallback, the validated 12/24-hour preference, localized date rendering and keyboard-focus/tool-tip accessibility without weakening the alarm-store boundary. Sleep/wake catch-up and pre-login alarms remain explicitly unclaimed.

## Security boundary

This gate does **not** introduce privilege elevation, arbitrary shell execution, remote payload loading, driver downloads, package-manager bypasses, or destructive disk actions. It only verifies already-reviewed first-party native application and recovery integration.

The gate never replaces the dedicated per-application workflows. Browser, Text Editor, Player, Photo Studio, PDF, Screenshot, Backup/Restore, Task Manager and the remaining native utilities retain their own runtime/security tests.

## Roadmap accounting

Passing this gate does **not** automatically complete `essential native Linux application suite for dependable daily use`.

Photo Studio 0.3 closes the previously documented image-editor depth gap by implementing and separately runtime-verifying user-selectable crop, exposure/brightness/contrast, color controls, filters, bounded text, bounded line drawing/annotation, undo/redo and common-format export. The integration verifier fails closed if those implementation markers disappear.

The runtime-evidence coverage is machine-audited across all explicit implementation capabilities. Native Default Apps has separately verified browser, media, image, PDF, text/code and archive categories with final-image staging. Text Editor now has a dedicated local-file runtime authority and safe New/Open/Save/Save As behavior. Clock alarms persist across restarts and the active-session background service is runtime-verified with the Clock window closed.

The locale/accessibility closure is advancing through real application surfaces rather than inventory claims. Calculator, Notes, Network Center, Text Editor and Clock consume the bounded per-user SWIR language preference, expose reviewed English/Polish/Norwegian Bokmål chrome with safe English fallback, and carry runtime evidence for localized Wayland surfaces plus keyboard-focus/tool-tip accessibility where those controls apply. Clock additionally consumes the validated per-user 12/24-hour preference and verifies localized date output for the selected catalog. Network Center remains read-only, Notes keeps its owner-only atomic storage boundary, Text Editor retains its no-follow/exclusive-create/inode-identity overwrite protections, and Clock retains its owner-only atomic alarm store and active-session-only service boundary while localized.

The remaining umbrella completion gate is **suite-wide locale/accessibility depth and final daily-use integration verification across the supported first-party applications**. The verified Calculator/Notes/Network/Text Editor/Clock slices reduce that gap but do not complete it; a green inventory/evidence gate must not hide the remaining product-depth work or inflate roadmap progress.

The canonical checklist and percentage remain exclusively in `SWIR-OS-ARCHITECTURE.md`.
