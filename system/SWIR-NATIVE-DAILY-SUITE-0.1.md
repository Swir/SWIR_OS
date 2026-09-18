# SWIR Native Daily-Use Suite Gate 0.1

## Scope

This gate reconciles the **System Edition essential-utility list** in `SWIR-PRODUCT-BASELINE-1.0.md` with the native applications actually present in `Swir/SWIR_OS`. It is intentionally an integration gate, not a second roadmap and not a completion claim.

The machine-readable inventory is `system/apps/native-daily-suite.json`. `system/apps/verify-native-daily-suite.py` verifies that every baseline capability is represented by trusted native source, is staged into the graphical System Edition image, and is reachable through the fixed native SWIR Shell launcher allowlist.

## Covered baseline capabilities

The manifest covers the 19 explicit Product Baseline essential-utility capabilities: Files, Settings, Terminal, Software, Update Center, Hardware & Driver Center, Network Center, Browser, Notes, Player, Photo Studio/Image Viewer, PDF Viewer, Archive Manager, Calculator, Screenshot Tool, Clock/calendar basics, Task Manager/System Monitor, Logs/Diagnostics, and Backup/Restore with recovery entry points.

A single trusted application may satisfy more than one UI surface only when that is the real implementation. For example, `swir-system-monitor.py` provides both process monitoring and its read-only Diagnostics tab, while Archive Manager is a dedicated GTK4 application mode inside the trusted `swir-files` executable.

## What the verifier proves

The gate fails closed when:

- a baseline capability disappears or is duplicated in the manifest;
- an essential source becomes HTML/PWA/JavaScript instead of native Linux application source;
- a source or companion is missing, symlinked, outside the repository, syntactically invalid, or no longer GTK4 based;
- graphical-image provisioning stops staging a required native executable;
- the fixed SWIR Shell launcher no longer exposes a required capability;
- high-risk implementations lose key safety markers, such as Archive Manager no-follow/exclusive extraction, Screenshot portal mediation, same-user Task Manager identity binding, or read-only diagnostics command allowlisting;
- Backup/Restore loses the recovery companions used by System Edition.

CI additionally executes the real Archive Manager hostile-input/self-test and the Recovery Mode provisioning self-test.

## Security boundary

This gate does **not** introduce privilege elevation, arbitrary shell execution, remote payload loading, driver downloads, package-manager bypasses, or destructive disk actions. It only verifies already-reviewed first-party native application and recovery integration.

The gate never replaces the dedicated per-application workflows. Browser, Player, Photo Studio, PDF, Screenshot, Backup/Restore, Task Manager and other applications retain their own runtime/security tests.

## Roadmap accounting

Passing this gate does **not** automatically complete `essential native Linux application suite for dependable daily use`.

The umbrella roadmap item remains open until the full Product Baseline definition of done is satisfied, including required feature depth and integration. In particular, the current SWIR Photo Studio basic milestone still lacks Product Baseline features such as crop, exposure/brightness/contrast and color controls, filters, text, and drawing/annotation. A green inventory/integration gate must not hide those product gaps or inflate roadmap progress.

The canonical checklist and percentage remain exclusively in `SWIR-OS-ARCHITECTURE.md`.
