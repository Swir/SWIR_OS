# SWIR Native Daily-Use Suite Gate 0.1

## Scope

This gate reconciles the **System Edition essential-utility list** in `SWIR-PRODUCT-BASELINE-1.0.md` with the native applications actually present in `Swir/SWIR_OS`. It is intentionally an integration gate, not a second roadmap and not a completion claim.

The machine-readable inventory is `system/apps/native-daily-suite.json`. `system/apps/verify-native-daily-suite.py` verifies that every baseline capability is represented by trusted native source, is staged into the graphical System Edition image, is reachable through the fixed native SWIR Shell launcher allowlist, and is explicitly mapped to an in-repository runtime-evidence workflow.

## Covered baseline capabilities

The manifest covers the 19 explicit Product Baseline essential-utility capabilities: Files, Settings, Terminal, Software, Update Center, Hardware & Driver Center, Network Center, Browser, Notes, Player, Photo Studio/Image Viewer, PDF Viewer, Archive Manager, Calculator, Screenshot Tool, Clock/calendar basics, Task Manager/System Monitor, Logs/Diagnostics, and Backup/Restore with recovery entry points.

A single trusted application may satisfy more than one UI surface only when that is the real implementation. For example, `swir-system-monitor.py` provides both process monitoring and its read-only Diagnostics tab, while Archive Manager is a dedicated GTK4 application mode inside the trusted `swir-files` executable.

## Runtime-evidence authority audit

Every one of the 19 baseline capabilities now declares an `evidenceWorkflow` in `system/apps/native-daily-suite.json`. The current inventory resolves to 15 distinct first-party runtime/security workflows: the shared core-apps and Software/Update gates plus dedicated Settings/Default Apps, Hardware, Browser, Player, Photo Studio, PDF, Archive, Calculator, Screenshot, Clock, Task Manager, Diagnostics and Backup/Restore authorities.

The integration verifier fails closed if an evidence authority disappears, moves outside `.github/workflows`, stops being a pull-request gate, loses read-only repository permissions, no longer references the native source it claims to cover, or no longer contains a runtime/self-test execution marker. This prevents a capability from remaining in the umbrella inventory on source/staging evidence alone after its real runtime authority has been removed.

This audit proves **coverage of runtime-evidence authorities**, not that every product-depth requirement is automatically complete. The dedicated workflows remain responsible for the actual behavior and security assertions of their applications.

## What the verifier proves

The gate fails closed when:

- a baseline capability disappears or is duplicated in the manifest;
- an essential source becomes HTML/PWA/JavaScript instead of native Linux application source;
- a source or companion is missing, symlinked, outside the repository, syntactically invalid, or no longer GTK4 based;
- graphical-image provisioning stops staging a required native executable;
- the fixed SWIR Shell launcher no longer exposes a required capability;
- a capability loses its declared runtime-evidence workflow or that workflow stops gating pull requests, referencing the native source or running runtime/self-test evidence;
- high-risk implementations lose key safety markers, such as Archive Manager no-follow/exclusive extraction, Screenshot portal mediation, same-user Task Manager identity binding, or read-only diagnostics command allowlisting;
- Backup/Restore loses the recovery companions used by System Edition;
- Photo Studio loses the Product Baseline implementation markers for rectangular crop, color transforms, bounded text annotation or bounded drawing/annotation.

CI additionally executes the real Archive Manager hostile-input/self-test and the Recovery Mode provisioning self-test. Photo Studio retains its separate dedicated Wayland/Debian 13 workflow, which is the runtime authority for real pixel changes, source immutability and export behavior. Settings now has a dedicated Default Apps runtime authority that performs real per-user Gio handler mutations for browser, media, image and PDF categories inside an isolated Wayland profile.

## Security boundary

This gate does **not** introduce privilege elevation, arbitrary shell execution, remote payload loading, driver downloads, package-manager bypasses, or destructive disk actions. It only verifies already-reviewed first-party native application and recovery integration.

The gate never replaces the dedicated per-application workflows. Browser, Player, Photo Studio, PDF, Screenshot, Backup/Restore, Task Manager and the remaining native utilities retain their own runtime/security tests.

## Roadmap accounting

Passing this gate does **not** automatically complete `essential native Linux application suite for dependable daily use`.

Photo Studio 0.3 closes the previously documented image-editor depth gap by implementing and separately runtime-verifying user-selectable crop, exposure/brightness/contrast, color controls, filters, bounded text, bounded line drawing/annotation, undo/redo and common-format export. The integration verifier fails closed if those implementation markers disappear.

The runtime-evidence coverage gap is machine-audited across all 19 baseline capabilities. Native Default Apps now has separately verified browser, media, image and PDF categories, while text/code and archive handler completion, locale/accessibility depth and remaining daily-use integration gaps stay open. A green inventory/evidence gate must not hide a product-depth gap or inflate roadmap progress.

The canonical checklist and percentage remain exclusively in `SWIR-OS-ARCHITECTURE.md`.
