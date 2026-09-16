# SWIR OS Product Baseline 1.0

This document defines mandatory end-user capabilities for SWIR OS. It is a product contract, not a claim that every item is implemented today. Completion is tracked in `SWIR-OS-ARCHITECTURE.md` and requires working, verified behavior.

## 1. Complete system out of the box

A normal user must be able to install SWIR OS and immediately browse the web, manage files, configure the device, play media, view and edit common images/documents, install software, update the system, diagnose hardware and recover from a failed update. Core applications must be bundled with the edition that requires them; users must not be sent hunting for basic runtime dependencies.

## 2. SWIR Browser

SWIR Browser is a required first-party application. It must provide tabs, history, bookmarks, downloads, private browsing, permissions, default-browser integration and secure update handling. The browser UI is SWIR-owned; the project may use a maintained upstream web engine rather than building a rendering engine from scratch.

SWIR Store must also make supported alternative browsers easy to install. Settings must expose Default Apps so the user can choose a different browser without uninstalling SWIR Browser.

## 3. SWIR Themes / Shell Skins

The shell must support installable theme/skin packages with safe boundaries. A theme may control design tokens, colors, typography, icon packs, window chrome, taskbar/dock/launcher presentation, spacing and approved animations/layout variants. Theme packages must not gain arbitrary privileged code execution simply because they alter appearance.

SWIR may ship original presets inspired by broad interface families such as classic desktop, glass, minimal, neon, retro or mobile-like layouts. Do not copy proprietary logos, copyrighted asset sets or trademark-confusing branding from other operating systems.

Accessibility overrides, recovery to the default theme and compatibility metadata are mandatory. A broken theme must never make Settings/recovery inaccessible.

## 4. SWIR Player

A first-party media player is mandatory. The target includes a local music/video library, playlists, metadata and cover art, seek/volume controls, media keys, notification/media-session integration and an equalizer where the selected backend supports it. Common formats should be handled through maintained system multimedia frameworks/codecs rather than unsafe bundled codec packs from random sources.

## 5. SWIR Photo Studio

A first-party image editor is mandatory. The dependable baseline includes crop, rotate/flip, resize, exposure/brightness/contrast, color controls, filters, text, drawing/annotation, undo/redo and export to common formats. Edits should be non-destructive while a document is open, with explicit save/export behavior.

## 6. Essential utilities

The final System Edition baseline includes at least:

- File Manager
- Settings / Control Center
- Terminal
- Software / SWIR Store
- Update Center
- Hardware & Driver Center
- Network Center
- SWIR Browser
- Text Editor / Notes
- SWIR Player
- SWIR Photo Studio / Image Viewer
- PDF Viewer
- Archive Manager
- Calculator
- Screenshot tool
- Clock / alarms / calendar basics
- Task Manager / System Monitor
- Logs / Diagnostics
- Backup / Restore and recovery entry points

System Edition core utilities must be native Linux applications or native system integrations. Web/PWA applications can remain prototypes and Desktop transitional surfaces, but the bootable System Edition must not require a browser runtime for essential daily use.

## 7. Software choice and defaults

SWIR Store/Package Core should present supported native Linux packages first on System Edition and later integrate approved Flatpak/AppImage providers. Windows user applications are handled by the managed Wine/Proton compatibility service with per-app profiles/prefixes when appropriate.

Default Apps must cover at least browser, media player, image viewer/editor, PDF handler, text/code handler and archive handler. Alternative applications installed from approved providers should become selectable without manual file editing.

Microsoft Store must not be copied, impersonated or bypassed. If Microsoft provides an official and licensable integration path it can be evaluated separately; otherwise Windows Store-only applications require their legitimate Windows environment/account/licensing path.

## 8. Update behavior

The primary SWIR OS release/update source is the `Swir/SWIR_OS` GitHub repository and its immutable GitHub Releases. `swir.github.io` is presentation only and is never an OS update authority.

Desktop Update Center must support signed release metadata, exact version/channel checks, package size and SHA-256 verification, staged candidate activation, startup health proof, rollback/recovery and controlled restart. User policy should ultimately provide:

- **Automatic** — download/prepare trusted updates automatically and request restart when required.
- **Notify only** — check automatically but require user approval before download/install.
- **Manual** — check only on user request except any future explicitly documented emergency/security policy.

Security updates must be clearly identified. Update Center must never silently replace trust roots or downgrade the installed system. A failed update must preserve a recoverable previous state.

System Edition expands the same experience to base-system packages, SWIR components, approved application providers, firmware via fwupd/LVFS where supported, and trusted driver/firmware sources.

## 9. Hardware trust baseline

Linux in-tree drivers and `linux-firmware` are the primary System Edition path. Distribution repositories, fwupd/LVFS and explicitly allowlisted official vendor repositories are permitted sources. Random driver download sites are not.

Windows drivers are not a generic Linux kernel driver strategy. Windows **applications** may use Wine/Proton; hardware support remains a native Linux responsibility.

## 10. Definition of done

A product-baseline item is complete only when its real edition-specific implementation exists, integrates with permissions/locale/accessibility/default apps/update/recovery where relevant, and has an automated or reproducible verification path. A mockup, placeholder UI, disabled backend or Web-only prototype does not complete a Desktop/System roadmap checkbox.
