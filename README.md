<div align="center">

# ⚡ SWIR OS

### Hybrid Operating System Platform

**Linux foundation • Native applications • Windows compatibility • SWIR App Platform • Secure updates • Hardware & Driver Center**

SWIR OS is an actively developed operating-system platform designed to become a **bootable Linux-based hybrid desktop system** with its own shell, services, application model, package layer, hardware management and managed compatibility for Windows applications.

[![System Edition Contracts](https://github.com/Swir/SWIR_OS/actions/workflows/system-contracts.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/system-contracts.yml)
[![Desktop Windows Build](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-windows-build.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-windows-build.yml)
[![Release Trust Chain](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-release-trust-chain-contract.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-release-trust-chain-contract.yml)
[![Native Notifications](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-native-notification-contract.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-native-notification-contract.yml)

![Roadmap](https://img.shields.io/badge/ROADMAP-63.0%25-2ea043?style=for-the-badge)
![Completed](https://img.shields.io/badge/DONE-34%2F54-1f6feb?style=for-the-badge)
![Status](https://img.shields.io/badge/STATUS-IN%20PROGRESS-7c3aed?style=for-the-badge)

</div>

---

## 🚀 The goal

SWIR OS is not intended to remain a browser shell or a themed desktop simulation.

The long-term target is a **real installable operating system** built on a maintained Linux base while providing a unified SWIR experience across applications, system services and hardware management.

The target system is designed around three application classes:

```text
SWIR applications   -> SWIR App SDK / SWIR Runtime
Linux applications  -> native Linux execution
Windows applications -> managed Wine / Proton compatibility profiles
```

Windows user applications are planned through a controlled compatibility layer. Windows kernel drivers are **not** treated as a general hardware solution for Linux.

---

## 📊 Development status

| Layer | Current state | Version / status |
|---|---|---|
| **Web Edition** | Portable application platform, shell and API laboratory | `1.7.13` |
| **Desktop Edition** | Executable Windows host with native OS adapters | `0.5.7-preview` |
| **System Edition** | Linux system contracts, hardware and driver foundation | In development |

### Overall roadmap

```text
█████████████░░░░░░░ 63.0%
```

**34 of 54 measurable roadmap deliverables are complete.**

The percentage is based on implemented and verified roadmap items. CI-only prototypes do not count as completed functionality.

➡️ Full architecture and measurable roadmap: [`SWIR-OS-ARCHITECTURE.md`](SWIR-OS-ARCHITECTURE.md)

---

## 🧠 SWIR OS architecture

SWIR OS uses one application model with replaceable platform adapters.

```text
                         SWIR Applications
                                │
                                ▼
                         SWIR App SDK
                                │
                                ▼
                     SWIR Platform / Runtime
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
       Web Adapter        Desktop Adapter      System Adapter
       Browser/PWA        Native Windows       Native Linux
       IndexedDB          Files / Process      Files / Process
       Browser APIs       Devices / Network    Services / Drivers
             │                  │                  │
             └──────────────────┴──────────────────┘
                                │
                                ▼
                       Shared SWIR app model
```

Applications should use `SwirAppSDK`, `SwirPlatform` and `SwirRuntime` instead of directly depending on one operating-system edition whenever possible.

---

## 🖥️ Desktop Edition

The Windows Desktop Edition is the current executable bridge between the portable SWIR platform and the future System Edition.

Implemented native foundations include:

- native filesystem access through guarded brokers,
- private per-application App Data,
- device and network adapters,
- native account and session information,
- process and service management,
- clipboard integration,
- native tray lifecycle,
- global shortcuts,
- Windows file associations and Open With integration,
- native notifications,
- `.swirapp` package installation and rollback,
- package execution isolation,
- owner/session-bound capabilities,
- guarded update activation,
- startup health verification,
- automatic rollback and recovery.

The host uses **.NET 8 Windows Desktop + WebView2 Evergreen Runtime**. Privileged operating-system actions remain behind explicit native brokers and permission checks.

---

## 🐧 System Edition

The System Edition is the final operating-system direction.

Planned architecture includes:

```text
Linux kernel / maintained base
        │
        ├── SWIR boot + session layer
        ├── SWIR desktop shell
        ├── SWIR services
        ├── NetworkManager integration
        ├── native Linux applications
        ├── SWIR Package Provider
        ├── Wine / Proton compatibility service
        ├── Hardware Service
        ├── SWIR Driver Center
        └── recovery / rollback environment
```

The bootable System Edition is **not complete yet**. Current work is building and validating the contracts required before privileged system mutation is allowed.

---

## 🔧 Hardware & Driver Center

SWIR OS uses a **read-only-first** hardware architecture.

The Hardware Service is designed to detect and normalize PCI/USB hardware identities. The Hardware Catalog maps known hardware to:

```text
hardware ID
   │
   ├── kernel module
   ├── firmware
   ├── distribution package
   ├── trusted update source
   └── rollback capability
```

Allowed driver and firmware source classes are deliberately restricted to:

- Linux kernel in-tree drivers,
- `linux-firmware`,
- selected distribution repositories,
- `fwupd` / LVFS,
- official vendor repositories for exceptional proprietary components.

SWIR OS does **not** silently download random driver binaries from unknown websites.

---

## 📦 SWIR applications and packages

SWIR OS has its own portable application and package model.

Current foundations include:

- **SWIR App SDK 1.3**,
- **SWIR App Package 1.0**,
- dependency-aware package resolution,
- application permissions,
- App Data namespaces,
- file associations,
- notification APIs,
- BCP-47 locale support,
- package transaction journal,
- rollback metadata,
- signed catalog metadata,
- SHA-256 payload verification.

The future common provider layer is intended to coordinate multiple software sources without merging their security models:

```text
SWIR packages
Linux distribution packages
Flatpak
AppImage
Wine compatibility profiles
Proton compatibility profiles
```

---

## 🛡️ Security model

Security-sensitive features are designed to fail closed.

Current Desktop security work includes:

- closed permission allowlists,
- package execution policies,
- isolated package contexts,
- owner-bound capabilities,
- session-bound execution contexts,
- Ed25519 signed catalog verification,
- SHA-256 package payload validation before extraction,
- anti-rollback catalog sequencing,
- trust-root rotation contracts,
- transactional package/update slots,
- update health challenges,
- restart handoff protection,
- recovery after interrupted updates.

### Production signing status

The production roadmap item **package signatures and integrity verification** remains open until the official production trust root and protected release signing-key provisioning are deployed and verified.

Private production signing keys must never be stored in this repository.

---

## 🌍 Language architecture

SWIR OS is designed for multilingual operation.

- the runtime detects the system/device language,
- supported locales can be selected globally,
- unsupported locales fall back to English,
- applications receive read-only locale information through portable APIs,
- the i18n architecture is designed to accept additional languages without rewriting the shell.

Repository documentation and development files are maintained in **English**.

---

## 🗂️ Repository structure

| Path | Purpose |
|---|---|
| `desktop/windows/` | Windows Desktop Host, native brokers, updater and self-tests |
| `system/` | System Edition architecture, Hardware Service and Driver Center contracts |
| `scripts/` | package, catalog, trust-chain and release validators |
| `.github/workflows/` | CI contracts for Desktop, System, security, packages and i18n |
| `SWIR-OS-ARCHITECTURE.md` | canonical measurable project roadmap |
| `SWIR-ROADMAP-STANDARD.md` | locked roadmap dashboard format |
| `swir-*.js` | portable SWIR runtime and services |
| `swir-*.html` | SWIR applications and system UI |

---

## ▶️ Run the Web Edition

The Web Edition remains useful for portable UI/API development and compatibility testing.

```bash
git clone https://github.com/Swir/SWIR_OS.git
cd SWIR_OS
python -m http.server 8000
```

Open:

```text
http://localhost:8000
```

---

## 🪟 Build the Windows Desktop Host

### Requirements

- Windows 10 or Windows 11 x64,
- .NET 8 SDK,
- Microsoft Edge WebView2 Evergreen Runtime.

### Build

```powershell
cd desktop/windows
dotnet build SWIR.Desktop.Host.csproj -c Release
```

### Preview publish

```powershell
./publish-desktop-host.ps1 `
  -PublishDir ./publish `
  -ReleaseVersion 0.5.7 `
  -Channel preview
```

A local build is **not** equivalent to an official verified release. Official release pipelines add package/catalog validation, signed update metadata and trust-chain checks.

---

## 🎯 Current priorities

Development is currently focused on the highest-value steps toward a real Desktop/System platform:

1. complete the production package-signing trust cutover,
2. continue hardening the Windows Desktop Host and update lifecycle,
3. expand Hardware Service and Driver Center foundations,
4. build the common System Package Provider architecture,
5. prepare native Linux process/network/filesystem adapters,
6. move toward the first controlled bootable System Edition image.

Roadmap boxes are checked only after the functionality is actually implemented and verified.

---

## ⚠️ Current limitations

SWIR OS is under active development.

- System Edition is not yet a finished bootable distribution.
- Desktop Edition is still a preview line.
- production package-signing provisioning is not yet fully cut over,
- hardware catalog coverage is intentionally limited while the safety model is being validated,
- Windows application compatibility through Wine/Proton belongs to the System Edition roadmap and is not yet a completed subsystem.

These limitations are intentionally kept visible instead of marking unfinished prototypes as complete.

---

## 🤝 Development principles

1. Build real functionality before increasing roadmap progress.
2. Keep privileged operations behind permission-aware brokers.
3. Prefer portable SWIR contracts over edition-specific application code.
4. Use trusted operating-system, distribution, LVFS and official vendor sources only for drivers and firmware.
5. Keep update, package and driver mutations transactional and recoverable.
6. Preserve a path from Desktop Edition to a native bootable System Edition.
7. Never commit production private signing keys.

---

<div align="center">

## 👨‍💻 Author

**SWIR OS — by Swir**

[github.com/Swir](https://github.com/Swir)

### Building a real hybrid operating-system platform — one verified layer at a time.

</div>
