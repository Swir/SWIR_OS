# SWIR OS — Architecture Roadmap

## Project direction

SWIR OS is designed in three editions sharing platform, package, security and service contracts where that reuse is appropriate:

1. **SWIR OS Web Edition** — browser/PWA prototype and design laboratory.
2. **SWIR OS Desktop Edition** — executable Windows desktop bridge with real files, processes, networking and OS integrations.
3. **SWIR OS System Edition** — future bootable Linux-based system with the SWIR shell, services, accounts, native Linux applications and a managed Windows compatibility layer.

**System Edition application rule:** the real bootable OS must not depend on HTML/PWA applications for its essential desktop experience. Core bundled applications must be native Linux applications. Windows desktop applications may run through a controlled Wine/Proton compatibility layer. Web Edition applications remain useful prototypes and design references, but they are not the final System Edition application implementation.

The mandatory end-user application and experience scope is defined in [`SWIR-PRODUCT-BASELINE-1.0.md`](SWIR-PRODUCT-BASELINE-1.0.md). Product-baseline items count as complete only when their edition-specific implementation is real and verified.

<!-- SWIR-ROADMAP-STANDARD:v1 -->
<!-- ROADMAP-PROGRESS:START -->
<p align="center">
  <a href="https://github.com/Swir/SWIR_OS/actions/workflows/system-contracts.yml"><img alt="CI" src="https://github.com/Swir/SWIR_OS/actions/workflows/system-contracts.yml/badge.svg"></a>
  <img alt="Roadmap progress" src="https://img.shields.io/badge/ROADMAP-89.2%25-2ea043?style=for-the-badge">
  <img alt="Completed" src="https://img.shields.io/badge/DONE-58%2F65-1f6feb?style=for-the-badge">
  <img alt="Status" src="https://img.shields.io/badge/STATUS-IN%20PROGRESS-7c3aed?style=for-the-badge">
</p>

<p align="center">
  <img width="900" src="assets/readme/progress-mini.svg" alt="SWIR OS roadmap progress — 89.2%, 58 of 65 verified deliverables" />
</p>

## 📊 Overall progress


| ✅ Completed | ⏳ Remaining | 📦 Total | 🎯 Progress |
|---:|---:|---:|---:|
| **58** | **7** | **65** | **89.2%** |

> **Progress rule:** the explicit `[x]/[ ]` deliverables in **Version roadmap** are the source of truth for the full Web → Desktop → System plan. Update the checklist first, then badges, numbers, percentage and deterministic SVG outputs. A prototype does not count as complete until the described deliverable is actually implemented and verified.
<!-- ROADMAP-PROGRESS:END -->

```text
SWIR contracts / package metadata / service APIs
      |
      +------------------+------------------+
      |                  |                  |
      v                  v                  v
 Web Edition        Desktop Edition       System Edition
 Browser/PWA        Native Windows        Native Linux
 IndexedDB          Native filesystem     Linux filesystem
 Browser APIs       Native processes      Linux processes
 Local profiles     Native accounts       Linux accounts
 Browser network    Native adapters       NetworkManager
 Prototype apps     Transitional host     Native Linux apps
                                           + Wine/Proton
```

Portable contracts can be shared, but System Edition must remain usable without a browser/PWA runtime for essential desktop functions.

---

## SWIR Platform API 2

Platform API 1 arrived in SWIR OS 1.3. Platform API 2 arrived in 1.4 and added Identity, Sessions and Settings.

Main surfaces:

```text
SwirPlatform.storage
SwirPlatform.settings
SwirPlatform.identity
SwirPlatform.files
SwirPlatform.clipboard
SwirPlatform.permissions
SwirPlatform.packages
SwirPlatform.processes
SwirPlatform.system
```

Web Edition maps these to browser APIs, IndexedDB/localStorage and the SWIR window manager. Desktop/System editions replace privileged and persistent behavior with native implementations while preserving portable call shapes where that does not weaken the native design.

---

## Identity & Session Core — 1.4

Web Edition provides local profiles, active-user selection, roles, optional local PIN, lock state and First Boot/OOBE.

The Web PIN is only a convenience lock. Desktop/System editions must map identity and authentication to native account/session security.

---

## Device & Network Core — 1.5

### Device Manager

Web Edition exposes the device information browsers make available, including logical CPU count, approximate memory, screen/viewport, storage estimate, battery when supported and connection telemetry.

### Network Center

Web Edition exposes online/offline state and connection metrics when supported, plus portable SWIR network profiles.

Browsers do not allow arbitrary scanning/connecting to real Wi-Fi networks. Native editions map the same user model to native adapters; System Edition targets a NetworkManager-backed service.

---

## App SDK & Package Core — 1.6

SWIR OS 1.6 introduced **SWIR App SDK 1.0** and **SWIR App Package 1.0** using schema `swir.app/1.0`.

The specification lives in `SWIR-APP-PACKAGE-1.0.md`.

The Web/Desktop package work is a reusable contract foundation. System Edition may reuse metadata, dependency, permission, trust and transaction concepts, but a final System Edition application payload must resolve to supported native Linux software or an explicitly managed Windows compatibility payload rather than an HTML-only core application.

---

## Files, Associations, Notifications & Dependency Core — 1.7

SWIR OS 1.7 reaches **SWIR App SDK 1.3**. The 1.7 line adds portable file-association, app-data, application-notification and package dependency contracts.

### File handoff

```text
SWIR File Explorer
       |
       v
extension / MIME lookup
       |
       v
SWIR File Association Service
       |
       +--> saved default handler
       +--> first installed compatible package
       |
       v
SwirAppSDK.files.open(...)
       |
       v
application receives SWIR_OPEN_FILE payload
```

Initial Web/Desktop prototype handlers:

```text
swir.code          -> .txt .html .htm .css .js .json .md .log
swir.image-studio  -> .png .jpg .jpeg .webp .gif
swir.archive       -> .zip
swir.pdf-viewer    -> .pdf
```

System Edition must replace the essential HTML-based prototype handlers with native Linux applications or controlled native integrations.

### App Data

Every installable package can declare a logical private data path such as:

```text
SWIR://APPDATA/CODE
SWIR://APPDATA/IMAGE
SWIR://APPDATA/ARCHIVE
SWIR://APPDATA/PDF
SWIR://APPDATA/CHAT
```

Web Edition maps this to namespaced SWIR Platform storage. Desktop Edition maps it to a native application-data directory. System Edition maps native applications to real per-user/per-application filesystem locations and native OS permissions.

### Application Notification Service

Applications with the `notifications` permission can publish portable notifications through the SDK. The Web Edition maps them to the SWIR shell toast/notification center and keeps a bounded application notification history.

```text
SWIR App
   |
   v
SwirAppSDK.notifications.send(appId, options)
   |
   +--> package installed check
   +--> manifest permission declaration
   +--> granted permission check
   |
   v
SWIR Notification Service
```

System Edition maps notifications to its native notification service; native applications do not require a browser runtime to publish system notifications.

### Package Dependency Core

The package resolver implements `swir.dependencies/1.0` and is intentionally independent from the web Store UI.

```text
SWIR package metadata
      |
      v
SWIR Package Resolver
      |
      +--> min SWIR OS version
      +--> provider compatibility
      +--> architecture / edition support
      +--> required package versions
      +--> optional dependency warnings
      |
      v
INSTALL / REMOVE PLAN
```

Supported portable package APIs in the current Web/Desktop line:

```text
SwirAppSDK.packages.check(id)
SwirAppSDK.packages.planInstall(id)
SwirAppSDK.packages.planRemove(id)
SwirAppSDK.packages.audit()
SwirAppSDK.packages.runtime()
SwirAppSDK.packages.compareVersions(a, b)
```

**SWIR Store 2.2** enforces resolver results before install and remove actions. A package that requires a newer OS/SDK/API, unsupported edition, or missing dependency is blocked. Removal is blocked if an installed dependent package would break.

Desktop/System editions can reuse the resolver concepts before native payload download/unpack, signature verification and service/file-association registration.

### Package transaction journal

Package mutations use `swir.package-transaction/1.0`. Install, update and remove operations journal their rollback state before mutation. Package state and permissions are treated as one logical transaction: a partial failure automatically restores the previous package/permission snapshot, while committed operations retain user-approved manual rollback metadata. The Web journal is bounded and edition-neutral so Desktop `.swirapp` and later System providers can reuse the lifecycle with stronger native snapshots.

### Signed catalog metadata

The official package-catalog trust prototype uses `swir.catalog-signature/1.0`: a canonical SHA-256 fingerprint of the reviewed catalog is covered by an Ed25519 signature envelope, verified against an explicitly scoped trusted public key. Unknown keys, wrong scope, malformed metadata, catalog tampering and invalid signatures fail closed. The shipping client contains verification logic only; production private signing keys remain outside the repository and client runtime.

### SDK additions available in 1.7

```text
SwirAppSDK.files.*
SwirAppSDK.notifications.*
SwirAppSDK.packages.*
SwirAppSDK.locale.*
```

The locale surface is backed by the edition-neutral `swir.i18n/1.0` contract. System Settings accepts standards-valid BCP-47 locale tags and propagates language, regional formatting and LTR/RTL direction to the shell. System Edition native applications should consume equivalent native locale services; they must not require the Web App Bridge to obtain essential locale state.

---

## SWIR Services

Current Web service/status model includes:

- Window Manager
- Device Service
- Network Service
- Storage Service
- Identity Service
- Session Service
- Package Service
- **Package Resolver**
- File Association Service
- App Data Service
- Notification Service
- Locale Service
- Chat Service
- Cache Service
- Update Service
- Permission Service

Desktop/System editions map these to native services/daemons where privileged or persistent behavior is required.

---

## SWIR Chat service

Current Web prototype:

```text
SWIR Chat client
      |
      v
SWIR Chat API
      |
      v
MySQL / MariaDB
```

The Web client and Chat Server Kit can remain useful during development. A chat client bundled with the final System Edition must be a native Linux application or a separately installed Windows application running through the managed compatibility layer.

---

## Hybrid System Edition foundation

System Edition is deliberately Linux-based and hybrid rather than pretending that every foreign binary is native.

### Execution classes

```text
linux-native   -> primary System Edition application class
windows-compat -> Windows desktop application in managed Wine/Proton profile
```

HTML/PWA-only applications are a Web Edition development target, not a final System Edition execution class for bundled core applications.

Windows user applications are planned through Wine/Proton-style compatibility prefixes. Windows kernel drivers are not a general Linux hardware solution and must not be treated as one.

### Native application baseline

A dependable System Edition requires a coherent native Linux application suite, not just an ability to launch arbitrary Linux programs. The planned baseline includes:

```text
File Manager
Settings / Control Center
Terminal
Software / Store
Update Center
Hardware & Driver Center
Network Center
SWIR Browser
Text Editor / Notes
SWIR Player
SWIR Photo Studio / Image Viewer
PDF Viewer
Archive Manager
Calculator
Screenshot Tool
Task Manager / System Monitor
Logs / Diagnostics
Backup / Restore
```

These applications must integrate with SWIR locale, accessibility, permissions, file associations, default-app selection, update/recovery, notifications and shared visual design. They must be tested as real daily-use applications rather than placeholder demos.

The first-party SWIR Browser milestone is now verified on the native GTK4/WebKitGTK 6.0 path with tabs, bounded owner-only history/bookmarks, downloads, ephemeral private tabs, explicit permission prompts, Default Apps integration and approved alternative-browser handoff through Software Center. This closes the dedicated Browser roadmap item, not the broader daily-use suite.

The first-party SWIR Player milestone is now verified on the native GTK4/GStreamer path for local audio/video playback, with bounded owner-only library and playlist persistence, MPRIS2 media-key integration, Gio notifications, desktop MIME integration and the distro-managed Debian 13 GStreamer runtime. Its dedicated Wayland gate maps the real GTK4 window and prerolls generated local media, while the Debian 13 target gate verifies the GTK4 video sink. The player remains unprivileged and has no self-updater or direct package mutation. This closes the dedicated Player roadmap item only; the broader daily-use suite, including the remaining media/document utilities, is still open.

The first-party SWIR Photo Studio milestone is verified on the native GTK4/GdkPixbuf path for bounded local regular image files with rotate/flip/resize, rectangular crop, exposure/brightness/contrast/saturation controls, filters, bounded text and line annotation, a bounded 24-state undo/redo history and explicit atomic owner-only PNG/JPEG/WebP export while preserving the source file. Its dedicated Wayland gate verifies the localized EN/PL/NO runtime surface, English fallback, text direction and keyboard-focus/tool-tip accessibility, while the Debian 13 target gate verifies the distro-managed GTK4/GdkPixbuf runtime. The application remains unprivileged with no self-updater or direct package mutation; together with the suite-wide exact-head gate this contributes to the completed essential native daily-use suite milestone.

The installable SWIR Shell Theme/Skin framework milestone is now verified with bounded data-only `.swirtheme` packages, an exact token allowlist, accessibility contrast validation, owner-only atomic storage, Settings import/select/reset controls and fail-safe recovery to the immutable `builtin.swir-dark` theme. The dedicated Wayland gate maps real Settings and Shell windows, proves theme application and verifies missing-theme recovery. Theme packages cannot provide CSS selectors, scripts, commands, URLs or privileged code. This closes the dedicated shell theme/skin roadmap item; it does not imply arbitrary application theming or a theme marketplace.

### Live USB and installation path

System Edition is required to support a real removable-media path rather than only VM boot or developer rootfs execution:

```text
verified raw/hybrid media + SHA-256
        |
        v
firmware boot from USB
        |
        v
usable SWIR Live graphical session
        |
        +--> try without automatic internal-disk writes
        |
        v
native SWIR installer
        |
        v
explicit target + partition review + destructive confirmation
        |
        v
installed SSD/NVMe/HDD
        |
        v
source USB removed -> standalone boot + persistent user data
```

The current VM gate boots the final raw image as QEMU USB mass storage under OVMF, verifies the graphical Live session, proves the separate target remains unchanged through idle/preview/cancel/wrong-token paths, installs to the separate disk, detaches the source USB and verifies the installed disk boots graphically with persistent data. This is VM evidence only: physical USB qualification, Secure Boot and legacy BIOS remain separate claims.

The native GTK4 installer now drives the complete disposable UEFI VM path through read-only target review, an intentionally rejected wrong erase token, account/locale/keyboard/time-zone collection, the normal narrow `pkexec` helper, installation to a separate blank disk, source-USB detachment and graphical installed-system boot. The E2E verifies the configured account and regional settings both on disk and after detached boot without storing password material in evidence. This closes the VM graphical-installer deliverable only; physical USB/hardware qualification remains open.

### Common Store / Package layer

The common provider layer resolves and plans native software across reviewed provider classes while keeping provider security separate from Store UI policy:

```text
SWIR native package metadata
base-distribution packages
Flatpak
AppImage (after explicit sandbox/update policy)
Wine compatibility profiles
Proton compatibility profiles
```

The production System provider factory is distribution-only and is now verified inside the selected Debian 13 rootfs: it resolves APT plans against the allowlisted signed Debian repository policy, keeps privileged mutation behind the journaled broker stack, rejects untrusted repositories and keeps Windows compatibility outside the Linux package layer. Flatpak and AppImage adapters remain explicit experimental opt-ins and are not silently enabled by this completed common-layer milestone.

The Debian System package stack now resolves APT dependencies with a read-only `apt-get -s` simulation before authorization and mutation. The resolved dependency closure is attached to the package plan before its digest is journaled. A disposable Debian 13 image E2E performs a real journaled APT installation, verifies the pre-state and native entry point after mutation, and also resolves update/remove plans. Interrupted-update recovery remains a separate, still-open milestone.

Provider mechanics remain separate from Store UI policy. Privileged mutations require a structured plan, trusted source policy and transaction journal. A System Edition package entry must resolve to a supported native Linux payload or an explicitly managed Windows compatibility payload; an HTML-only payload does not satisfy the native System Edition application requirement.

### Hardware / Driver architecture

System Edition adds a read-only-first **Hardware Service** and a **SWIR Driver Center**. Hardware inventory normalizes PCI/USB IDs and maps devices through the Hardware Catalog to kernel modules, firmware, packages and update sources.

Trusted driver/firmware source classes are limited to:

```text
kernel-in-tree
linux-firmware
distribution-repository
fwupd-lvfs
vendor-official-repository
```

Unknown hardware may be diagnosed but must not trigger arbitrary automatic downloads. Firmware and driver mutations require a privileged transaction with rollback/recovery metadata where supported.

The detailed foundation and machine-readable contract schemas live under `system/`, beginning with `system/SWIR-SYSTEM-EDITION-ARCHITECTURE-0.1.md`.

---

## Version roadmap

### Web Edition 1.x — implemented foundation

- [x] desktop shell / window manager
- [x] launcher / taskbar
- [x] First Boot / OOBE
- [x] Identity & Session Core
- [x] Device Manager
- [x] Network Center
- [x] System Settings
- [x] File Explorer / virtual filesystem
- [x] Notes / Calculator / Player / Matrix
- [x] SWIR Chat + downloadable backend
- [x] Task Manager / SWIR Services
- [x] permissions / clipboard / Update Center
- [x] **SWIR App SDK 1.3**
- [x] **SWIR App Package 1.0**
- [x] **SWIR Store 2.2 dependency-aware lifecycle**
- [x] **package compatibility + dependency resolver**
- [x] **file associations / Default Apps / Open With**
- [x] **App Data namespaces**
- [x] **permission-aware application notification API**
- [x] **global BCP-47 locale service / Language & Region settings / App SDK + read-only App Bridge locale integration**

### Next Web Edition work

- [x] signed catalog metadata prototype
- [ ] widgets as installable packages
- [ ] application developer template / SDK examples
- [ ] larger binary/file storage on IndexedDB instead of localStorage mirror
- [x] package update transactions / rollback metadata
- [x] native-ready notification actions and persistence adapter

### Desktop Edition 2.x

Active direction:

- [x] lightweight native runtime
- [x] native filesystem adapter
- [x] native device/network adapters
- [x] native account/session backend
- [x] process/service manager
- [x] native clipboard and tray
- [x] global shortcuts and native file associations
- [x] `.swirapp` payload installer/updater
- [x] package dependency resolver shared with Web Edition
- [ ] package signatures and integrity verification
- [x] sandboxed permissions
- [x] native notification adapter
- [x] guarded update activation, health proof, rollback and restart handoff
- [ ] signed GitHub-backed stable/preview update feed with Automatic / Notify only / Manual user policy

### System Edition 3.x

Planned:

- [x] maintained Linux base/kernel and bootable image
- [x] SWIR boot splash and login/session manager
- [x] SWIR desktop shell
- [x] NetworkManager integration
- [x] native Linux application execution
- [x] essential native Linux application suite for dependable daily use
- [x] native SWIR Browser with Default Apps integration and one-click approved alternative browser installation
- [x] installable SWIR Shell Theme/Skin framework with accessibility-safe recovery to the default theme
- [x] native SWIR Player with library/playlists/media-key/notification integration
- [x] native SWIR Photo Studio with dependable basic editing, undo/redo and common-format export
- [x] common Package Provider layer for distribution packages and later Flatpak/AppImage
- [x] managed Wine/Proton compatibility service for Windows user applications
- [x] Hardware Service with PCI/USB inventory
- [x] SWIR Driver Center / Hardware Catalog
- [x] in-tree Linux drivers + linux-firmware as primary hardware path
- [ ] fwupd/LVFS firmware updates where supported
- [x] allowlisted official vendor repositories for exceptional proprietary components
- [x] dependency-aware system package manager/updater
- [x] journaled driver/firmware/package transactions
- [x] filesystem integration and recovery mode
- [x] UEFI Live USB raw-image + SHA-256 path verified as USB mass storage with graphical session in disposable VM
- [x] guarded disk-install engine with read-only preview/cancel, source-media rejection and separate-disk install verified in disposable VM
- [x] detached installed-disk UEFI boot + graphical session + persistence after source USB removal verified in disposable VM
- [x] native graphical Live installer drives the complete install path including target review, account, locale, keyboard, time zone and final destructive confirmation
- [ ] physical Live USB boot/install qualification on dedicated test hardware, tracked separately from VM evidence

---

## Development rule

Web Edition may continue to use HTML/CSS/JavaScript for prototyping portable behavior. Desktop Edition may use transitional WebView-hosted surfaces while native brokers are being validated.

**System Edition core applications are different:** essential bundled applications must be native Linux applications. Windows desktop applications are supported only through the managed compatibility service. Browser/PWA availability must not be required for the OS to provide files, settings, terminal, software/update management, hardware/driver management, networking, media/document basics, process monitoring or recovery.

Shared contracts such as package identity, permissions, dependency resolution, locale, notifications and update metadata should be reused where practical, but they must not force native System Edition applications back into a browser-only runtime. Privileged operations remain fail-closed until the corresponding broker/service, identity binding, permission model and recovery path exist.
