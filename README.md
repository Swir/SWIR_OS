<div align="center">

# ⚡ SWIR OS

### Hybrid Operating System Platform

**Linux foundation • Native applications • Windows compatibility • SWIR App Platform • Secure updates • Hardware & Driver Center**

SWIR OS is an actively developed operating-system platform designed to become a **bootable Linux-based hybrid desktop system** with its own shell, services, native application suite, package layer, hardware management and managed compatibility for Windows applications.

[![System Edition Contracts](https://github.com/Swir/SWIR_OS/actions/workflows/system-contracts.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/system-contracts.yml)
[![Desktop Windows Build](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-windows-build.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-windows-build.yml)
[![Release Trust Chain](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-release-trust-chain-contract.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-release-trust-chain-contract.yml)
[![GitHub Update Contract](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-github-update-contract.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-github-update-contract.yml)
[![Roadmap Contract](https://github.com/Swir/SWIR_OS/actions/workflows/roadmap-contract.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/roadmap-contract.yml)
[![Native Notifications](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-native-notification-contract.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-native-notification-contract.yml)

![Roadmap](https://img.shields.io/badge/ROADMAP-56.7%25-2ea043?style=for-the-badge)
![Completed](https://img.shields.io/badge/DONE-34%2F60-1f6feb?style=for-the-badge)
![Status](https://img.shields.io/badge/STATUS-IN%20PROGRESS-7c3aed?style=for-the-badge)

</div>

---

## 🚀 The goal

SWIR OS is not intended to remain a browser shell or a themed desktop simulation.

The long-term target is a **real installable operating system** built on a maintained Linux base while providing a unified SWIR experience across native applications, system services and hardware management.

The target system is designed around two real desktop application classes:

```text
Linux applications   -> native Linux execution
Windows applications -> managed Wine / Proton compatibility profiles
```

The Web Edition exists as a development, prototyping and compatibility laboratory. **HTML/PWA-only applications are not the final application model for the real bootable System Edition.** Core applications shipped with System Edition must be native Linux applications. Windows desktop applications may run through the controlled compatibility layer.

Windows kernel drivers are **not** treated as a general hardware solution for Linux.

---

## 📊 Development status

| Layer | Current state | Version / status |
|---|---|---|
| **Web Edition** | Portable application platform, shell and API laboratory | `1.7.13` |
| **Desktop Edition** | Executable Windows host with native OS adapters | `0.5.7-preview` |
| **System Edition** | Linux system contracts, hardware and driver foundation | In development |

### Overall roadmap

```text
███████████░░░░░░░░░ 56.7%
```

**34 of 60 measurable roadmap deliverables are complete.**

The percentage is based on implemented and verified roadmap items. CI-only prototypes do not count as completed functionality. The scope now explicitly includes the required SWIR Browser, installable shell themes/skins, SWIR Player, SWIR Photo Studio, GitHub-backed update policy and the complete native application baseline. Adding real required scope can reduce the percentage until those deliverables are implemented and verified.

➡️ Full architecture and measurable roadmap: [`SWIR-OS-ARCHITECTURE.md`](SWIR-OS-ARCHITECTURE.md)

➡️ Mandatory end-user product baseline: [`SWIR-PRODUCT-BASELINE-1.0.md`](SWIR-PRODUCT-BASELINE-1.0.md)

---

## 🧠 SWIR OS architecture

SWIR OS keeps shared service and package contracts while replacing the implementation underneath each edition.

```text
                       SWIR contracts / package metadata
                                  │
                   ┌──────────────┼──────────────┐
                   │              │              │
                   ▼              ▼              ▼
             Web Edition    Desktop Edition   System Edition
             Browser/PWA    Native Windows    Native Linux
             Prototype UI   Host + brokers    Shell + services
             IndexedDB      Native adapters   Linux services
                                                │
                         ┌──────────────────────┴─────────────────────┐
                         ▼                                            ▼
                 Native Linux applications                  Windows applications
                                                            Wine / Proton profiles
```

Portable contracts may be reused across editions, but System Edition must not depend on browser-only APIs for essential desktop functionality.

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

The release host uses **self-contained .NET 8 Windows Desktop + a pinned Microsoft WebView2 Fixed Version Runtime bundled inside the SWIR Desktop package**. A release package is designed so the end user does not manually install .NET or WebView2. The packaging pipeline obtains the repository-pinned WebView2 runtime from an approved Microsoft HTTPS source, checks its pinned SHA-256, exact version and Microsoft Authenticode signer, records acquisition provenance, bundles the runtime, and the Desktop Host verifies the bundled integrity/provenance chain before release startup.

The Desktop updater is being moved to a repository-owned signed release channel. Official package URLs are immutable assets under `Swir/SWIR_OS` GitHub Releases, signed update metadata is promoted through `updates/<channel>/`, and downloaded bytes remain subject to signed size/SHA-256 verification, guarded Candidate activation, startup health proof and rollback. `swir.github.io` is presentation only and is not an operating-system update authority.

Privileged operating-system actions remain behind explicit native brokers and permission checks. Desktop Edition may still host portable Web Edition surfaces during the transition. That transitional architecture does **not** define the final System Edition application model.

---

## 🐧 System Edition

The System Edition is the final operating-system direction.

Planned architecture includes:

```text
Linux kernel / maintained base
        │
        ├── SWIR boot + session layer
        ├── SWIR desktop shell + theme/skin system
        ├── SWIR services
        ├── NetworkManager integration
        ├── native Linux application suite
        ├── SWIR Package Provider
        ├── Wine / Proton compatibility service
        ├── Hardware Service
        ├── SWIR Driver Center
        └── recovery / rollback environment
```

### Native application policy

For the bootable System Edition:

- essential applications must be **native Linux desktop applications**, preferably maintained inside the SWIR project where a dedicated SWIR experience is required,
- third-party Linux applications may be integrated through controlled distribution packages and later Flatpak/AppImage providers,
- Windows desktop applications may be supported through managed Wine/Proton prefixes,
- HTML/PWA applications are **not accepted as the final bundled core application set**,
- browser technology may remain available as a browser and as a development target, but the operating system must remain usable if the browser/web runtime is unavailable.

The minimum dependable native application set is planned to include:

- File Manager,
- Settings / Control Center,
- Terminal,
- Software / SWIR Store,
- Update Center,
- Hardware & Driver Center,
- Network Center,
- **SWIR Browser**,
- Text Editor / Notes,
- **SWIR Player**,
- **SWIR Photo Studio / Image Viewer**,
- PDF Viewer,
- Archive Manager,
- Calculator,
- Screenshot Tool,
- Clock / alarms / calendar basics,
- Task Manager / System Monitor,
- Logs / Diagnostics,
- Backup / Restore and recovery entry points.

The shell is also planned to support safe installable **SWIR Themes / Shell Skins** with accessibility overrides and a guaranteed recovery path to the default theme. Alternative browsers, media players and other supported applications should be installable through SWIR Store and selectable through Default Apps.

These applications must share coherent SWIR design, accessibility, locale support, file associations, permissions, update integration and crash-safe data handling. They should not be treated as placeholder demos.

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

## 📦 Software and packages

The Web/Desktop work already provides reusable package, dependency and trust-chain contracts. System Edition will reuse the useful contracts while changing payload execution to real native software.

Current foundations include:

- **SWIR App SDK 1.6.1** for portable contracts and Web/Desktop development,
- **SWIR App Package 1.0** metadata,
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

For System Edition, a SWIR package/provider entry must ultimately resolve to a supported **native Linux payload** or an explicitly managed **Windows compatibility payload**. A package containing only an HTML application does not satisfy the final System Edition native-application requirement.

The future common provider layer is intended to coordinate multiple software sources without merging their security models:

```text
SWIR native package metadata
Linux distribution packages
Flatpak
AppImage
Wine compatibility profiles
Proton compatibility profiles
```

Microsoft Store is not copied, impersonated or bypassed. Any future Microsoft Store integration requires an official, licensable Microsoft-supported path; otherwise Store-only Windows applications remain tied to their legitimate Windows environment, account and licensing model.

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
- recovery after interrupted updates,
- pinned bundled-runtime source metadata and acquisition provenance,
- startup SHA-256 binding for the Desktop Host, WebView2 executable and WebView2 provenance record.

### Production signing status

The production roadmap item **package signatures and integrity verification** remains open until the official production trust root and protected release signing-key provisioning are deployed and verified.

Private production signing keys must never be stored in this repository.

---

## 🌍 Language architecture

SWIR OS is designed for multilingual operation and global use.

- the runtime detects the system/device language,
- supported locales can be selected globally without reinstalling the OS,
- unsupported locales fall back to English,
- BCP-47 locale matching includes language/region and likely-script handling,
- LTR and RTL direction are propagated for supported interfaces,
- the core distribution currently bundles 15 locale packs: English, Polish, Norwegian Bokmål, German, Spanish, French, Italian, Brazilian Portuguese, Ukrainian, Russian, Turkish, Arabic, Hebrew, Japanese and Simplified Chinese,
- First Boot / OOBE is localized across the bundled core locale set,
- critical File Explorer, Store, Update Center and Settings UI strings are supplied through bundled application locale packs,
- application locale resources are kept available by the offline runtime/cache and are intended to expand until the complete system/application surface is localized,
- no core language pack requires the user to visit another site and install it manually.

Repository documentation and development files are maintained in **English**.

---

## 🗂️ Repository structure

| Path | Purpose |
|---|---|
| `desktop/windows/` | Windows Desktop Host, native brokers, updater, self-tests and pinned bundled-runtime policy |
| `system/` | System Edition architecture, Hardware Service and Driver Center contracts |
| `updates/` | repository-owned signed Desktop update channel metadata; binaries stay in immutable GitHub Releases |
| `scripts/` | package, catalog, trust-chain, roadmap and release validators |
| `.github/workflows/` | CI contracts for Desktop, System, security, packages, updates, roadmap and i18n |
| `SWIR-OS-ARCHITECTURE.md` | canonical measurable project roadmap |
| `SWIR-PRODUCT-BASELINE-1.0.md` | mandatory end-user application and experience baseline |
| `SWIR-ROADMAP-STANDARD.md` | locked roadmap dashboard format |
| `swir-*.js` | Web Edition portable runtime, i18n and prototype services |
| `swir-*.html` | Web Edition applications and prototype system UI; not the final System Edition app implementation |

---

## ▶️ Run the Web Edition

The Web Edition remains useful for portable UI/API development and compatibility testing. It is not the final System Edition runtime.

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

### Developer requirements

A source/developer build requires:

- Windows 10 or Windows 11 x64,
- .NET 8 SDK,
- network access only when the packaging script needs to obtain the repository-pinned WebView2 Fixed Version Runtime.

These are **developer/build-machine requirements, not end-user prerequisites**. The verified Desktop release is intended to bundle the required .NET runtime and WebView2 runtime so the user receives one SWIR Desktop package.

### Build

```powershell
cd desktop/windows
dotnet build SWIR.Desktop.Host.csproj -c Release
```

### Self-contained preview publish

```powershell
./publish-desktop-host.ps1 `
  -PublishDir ./publish `
  -ReleaseVersion 0.5.7 `
  -Channel preview
```

If no explicit Fixed Version Runtime directory is supplied, the publisher reads `webview2-fixed-runtime.lock.json`, downloads only the pinned official Microsoft artifact, verifies SHA-256/version/Microsoft Authenticode, records provenance and bundles it into the output. An explicit preverified runtime directory may still be supplied for controlled/offline build infrastructure.

A local build is **not** equivalent to an official verified release. Official release pipelines add package/catalog validation, signed update metadata and trust-chain checks.

---

## 🎯 Current priorities

Development is currently focused on the highest-value steps toward a dependable Desktop/System platform:

1. complete the production package-signing trust cutover,
2. finish the signed GitHub Desktop update channel with user-selectable Automatic / Notify only / Manual behavior,
3. keep hardening the Windows Desktop Host, self-contained packaging and update lifecycle,
4. expand Hardware Service and Driver Center foundations,
5. implement the native Linux application framework and mandatory SWIR Browser / Player / Photo Studio application baseline,
6. implement the safe installable SWIR Themes / Shell Skins framework,
7. build the common System Package Provider architecture,
8. prepare native Linux process/network/filesystem adapters and move toward the first controlled bootable System Edition image,
9. finish full-system i18n, reliability, recovery, accessibility and daily-use workflows before calling System Edition stable.

Roadmap boxes are checked only after the functionality is actually implemented and verified.

---

## ⚠️ Current limitations

SWIR OS is under active development.

- System Edition is not yet a finished bootable distribution,
- Desktop Edition is still a preview line,
- production package-signing provisioning is not yet fully cut over,
- the signed GitHub update channel has secure feed/release plumbing but the complete Automatic / Notify only / Manual user policy is not yet finished,
- hardware catalog coverage is intentionally limited while the safety model is being validated,
- the essential native Linux application suite — including the native SWIR Browser, SWIR Player and SWIR Photo Studio — is not yet implemented,
- the installable System Edition shell theme/skin framework is not yet implemented,
- Windows application compatibility through Wine/Proton belongs to the System Edition roadmap and is not yet a completed subsystem,
- full localization of every application screen is still being expanded beyond the bundled core/OOBE/critical application UI coverage.

These limitations are intentionally kept visible instead of marking unfinished prototypes as complete.

---

## 🤝 Development principles

1. Build real functionality before increasing roadmap progress.
2. Keep privileged operations behind permission-aware brokers.
3. Treat Web Edition as a prototype/development layer, not as the final System Edition application runtime.
4. Ship System Edition core applications as native Linux applications; use Wine/Proton only for Windows desktop applications.
5. Use trusted operating-system, distribution, LVFS and official vendor sources only for drivers and firmware.
6. Keep update, package and driver mutations transactional and recoverable.
7. Preserve a path from Desktop Edition to a native bootable System Edition.
8. Make the default application set complete enough for real daily use before calling the system stable.
9. Bundle end-user runtime prerequisites with SWIR releases instead of requiring manual prerequisite downloads.
10. Bundle core locale resources and keep English as a safe fallback while expanding complete worldwide localization.
11. Treat `Swir/SWIR_OS` as the authoritative operating-system development and update source; keep `swir.github.io` presentation-only.
12. Never commit production private signing keys.

---

<div align="center">

## 👨‍💻 Author

**SWIR OS — by Swir**

[github.com/Swir](https://github.com/Swir)

### Building a real hybrid operating-system platform — one verified native layer at a time.

</div>
