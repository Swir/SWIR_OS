<!-- SWIR-README-STANDARD:v1 -->

<div align="center">

<img src="assets/branding/swir-os-logo.svg" width="720" alt="SWIR OS official electric-blue logo" />

# ⚡ SWIR OS

### Hybrid desktop operating-system platform

**Linux foundation • Native Linux applications • Managed Windows compatibility • Secure packages • Hardware & Driver Center**

[![System Edition Contracts](https://github.com/Swir/SWIR_OS/actions/workflows/system-contracts.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/system-contracts.yml)
[![Package Provider Image E2E](https://github.com/Swir/SWIR_OS/actions/workflows/system-package-provider-image-e2e.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/system-package-provider-image-e2e.yml)
[![Desktop Windows Build](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-windows-build.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-windows-build.yml)
[![Roadmap Contract](https://github.com/Swir/SWIR_OS/actions/workflows/roadmap-contract.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/roadmap-contract.yml)

![Roadmap](https://img.shields.io/badge/ROADMAP-71.7%25-02050A?style=for-the-badge&logoColor=62E5FF)
![Completed](https://img.shields.io/badge/DONE-43%2F60-02050A?style=for-the-badge&logoColor=62E5FF)
![Status](https://img.shields.io/badge/STATUS-IN%20PROGRESS-02050A?style=for-the-badge&logoColor=62E5FF)

**Canonical source repository:** `Swir/SWIR_OS`

</div>

<img width="100%" src="https://raw.githubusercontent.com/Swir/Swir/main/assets/power-divider-v4.svg" alt="SWIR electric divider" />

## 📊 Project status

SWIR OS is actively being developed toward a real installable Linux-based hybrid desktop system. The browser-based Web Edition remains useful as a portable UI/API laboratory, the Windows Desktop Edition is the executable bridge with native adapters, and the System Edition is the final Linux-native direction.

| Edition | Current state | Version / status |
|---|---|---|
| **Web Edition** | Portable shell, applications and API laboratory | `1.7.13` |
| **Desktop Edition** | Windows host with native OS adapters and guarded update/recovery foundations | `0.5.7-preview` |
| **System Edition** | Bootable Debian 13 foundation with verified native/runtime/hardware/package integration | In development |

### Overall roadmap

```text
██████████████░░░░░░ 71.7%
```

**43 of 60 measurable roadmap deliverables are complete.** The authoritative checklist and progress math live in [`SWIR-OS-ARCHITECTURE.md`](SWIR-OS-ARCHITECTURE.md). A prototype, contract skeleton or CI job alone does not count as a completed roadmap item.

---

## 🚀 What is SWIR OS?

SWIR OS is designed as a hybrid desktop platform with one shared application/service model and edition-specific native implementations. It is not intended to remain a themed browser desktop.

The target System Edition uses a maintained Linux base and keeps Linux-native hardware support first:

```text
Linux kernel / Debian 13 base
        │
        ├── SWIR boot + authenticated session layer
        ├── native SWIR desktop shell and applications
        ├── NetworkManager + native system services
        ├── SWIR Store / Package Provider layer
        ├── Hardware Service + Driver Center
        └── recovery / rollback services

Linux applications   -> native Linux execution
Windows applications -> managed Wine / Proton compatibility profiles
```

Windows kernel drivers are **not** treated as a general solution for Linux hardware. SWIR OS prefers kernel in-tree drivers, `linux-firmware`, selected distribution repositories, `fwupd`/LVFS where supported, and explicit official vendor repositories for exceptional proprietary components.

---

## ✨ Highlights

| Area | Verified/current direction |
|---|---|
| 🐧 **Linux System foundation** | Debian 13 base, kernel, UEFI boot path and systemd foundation are covered by System Edition gates. |
| 🖥️ **Desktop bridge** | Windows Desktop Host exposes native filesystem, app-data, account/session, process/service, device/network, clipboard, tray, shortcuts, file-association and notification adapters. |
| 🍷 **Windows compatibility** | Managed Wine compatibility has a live E2E that launches a deterministic Win64 application through controlled per-app compatibility state. Broader application compatibility is still being expanded. |
| 📦 **Packages** | The production distribution Package Provider is verified inside the selected Debian 13 System rootfs; Flatpak/AppImage remain explicit experimental adapters behind separate trust boundaries. |
| 🔧 **Hardware & drivers** | PCI/USB inventory, Hardware Catalog, Driver Center runtime, Linux in-tree drivers and `linux-firmware` are verified foundations. |
| 🌐 **Networking** | NetworkManager integration is exercised through a real isolated live E2E path. |
| 🔐 **Security** | Privileged operations are designed around explicit brokers, Polkit/session identity binding, trusted repository policy, journals and fail-closed validation. |
| 🌍 **i18n** | Shared BCP-47 locale architecture, English fallback, RTL/LTR handling and bundled core locale packs are maintained across the project. |

---

## 🧠 Architecture

SWIR OS shares contracts where that improves portability, while replacing browser-only implementations with native adapters as the project moves toward System Edition.

```text
                    SWIR contracts / package metadata
                               │
              ┌────────────────┼────────────────┐
              │                │                │
              ▼                ▼                ▼
        Web Edition      Desktop Edition   System Edition
        Browser/PWA      Windows host      Native Linux
        prototype UI     native brokers    shell + services
        IndexedDB        native adapters   Linux services
                                              │
                              ┌───────────────┴───────────────┐
                              ▼                               ▼
                    Native Linux apps                 Windows apps
                                                     Wine / Proton
```

Portable contracts may be reused across editions, but essential System Edition functionality must not depend on a browser runtime.

### System Edition application policy

Core daily-use applications must become native Linux desktop applications. The minimum product baseline includes File Manager, Settings, Terminal, Software/Store, Update Center, Hardware & Driver Center, Network Center, SWIR Browser, Notes/Text Editor, SWIR Player, SWIR Photo Studio/Image Viewer, PDF Viewer, Archive Manager, Calculator, Screenshot Tool, Task Manager/System Monitor, diagnostics and backup/recovery entry points.

See [`SWIR-PRODUCT-BASELINE-1.0.md`](SWIR-PRODUCT-BASELINE-1.0.md) for the mandatory end-user baseline.

---

## 📦 Software and package model

System Edition keeps software sources behind a common provider boundary instead of allowing Store UI to execute arbitrary package-manager commands.

```text
SWIR package metadata
        │
        ├── distribution packages  -> production provider verified in Debian 13 image
        ├── Flatpak                -> experimental / later production gate
        ├── AppImage               -> experimental / later production gate
        ├── Wine compatibility profiles
        └── Proton compatibility profiles
```

Distribution package plans require trusted source metadata, signature verification, a structured operation plan and privileged transaction boundaries. The image E2E verifies APT selection, signed/allowlisted repository binding and fail-closed provider separation without performing package mutation. Flatpak/AppImage stay deliberately gated until their production lifecycle, rollback/update policy and System-image integration satisfy their own requirements.

Microsoft Store is not copied, impersonated or bypassed. Any future integration would require an official Microsoft-supported and licensable path.

---

## 🔧 Hardware & Driver Center

The hardware architecture is **read-only first**. Hardware Service normalizes PCI/USB identities and maps known devices through Hardware Catalog data to modules, firmware, packages and trusted update sources.

Allowed driver/firmware source classes are limited to:

- Linux kernel in-tree drivers,
- `linux-firmware`,
- selected signed distribution repositories,
- `fwupd` / LVFS where supported,
- allowlisted official vendor repositories for exceptional proprietary components.

Unknown hardware may be diagnosed, but it must not trigger arbitrary binary downloads. Firmware/driver mutation remains behind explicit privileged transaction and recovery policy.

---

## 🔐 Security model

Security-sensitive paths are designed to fail closed. Current foundations include:

- closed permission/provider allowlists,
- owner/session-bound capability checks,
- Polkit-based privileged authorization boundaries,
- Ed25519 signed catalog verification foundations,
- SHA-256 payload validation,
- anti-rollback catalog sequencing,
- transactional package/update journals,
- guarded Desktop update activation with health proof and rollback,
- pinned WebView2 runtime acquisition metadata and integrity checks,
- root-owned repository/driver policy for System Edition,
- no random driver-download path,
- no shell execution for reviewed package/provider command paths.

Production package signing remains a roadmap item until the official production trust root and protected release-key provisioning are deployed and verified. Production private signing keys must never be stored in this repository.

---

## 🌍 Language architecture

SWIR OS is designed for multilingual use from the shared runtime upward:

- system/device locale detection,
- English fallback for unsupported locales,
- BCP-47 language/region matching,
- LTR/RTL direction propagation,
- locale-aware formatting foundations,
- bundled core locale packs currently covering 15 locales,
- localized First Boot/OOBE and critical application surfaces,
- offline availability of core locale resources.

Repository documentation and development files are maintained in English.

---

## ▶️ Quick Start — Web Edition

The Web Edition is useful for portable UI/API development and compatibility testing. It is **not** the final System Edition runtime.

```bash
git clone https://github.com/Swir/SWIR_OS.git
cd SWIR_OS
python -m http.server 8000
```

Open `http://localhost:8000`.

---

## 🪟 Build — Windows Desktop Host

### Developer requirements

- Windows 10 or Windows 11 x64,
- .NET 8 SDK,
- network access only when the packaging script must obtain the repository-pinned Microsoft WebView2 Fixed Version Runtime.

These are developer/build-machine requirements. The release packaging path is designed to bundle the required runtime components for the end user.

```powershell
cd desktop/windows
dotnet build SWIR.Desktop.Host.csproj -c Release
```

Self-contained preview publish:

```powershell
./publish-desktop-host.ps1 `
  -PublishDir ./publish `
  -ReleaseVersion 0.5.7 `
  -Channel preview
```

A local build is not equivalent to an official verified release. Release pipelines add package/catalog, runtime provenance, signing/trust and update-chain verification.

---

## 📁 Repository structure

| Path | Purpose |
|---|---|
| `desktop/windows/` | Windows Desktop Host, native brokers, updater, packaging and self-tests |
| `system/` | System Edition image, services, package/runtime, hardware/driver and security foundations |
| `updates/` | Repository-owned Desktop update-channel metadata; binaries belong in immutable GitHub Releases |
| `scripts/` | Package, catalog, roadmap, trust-chain and release validators |
| `.github/workflows/` | Desktop/System/security/package/i18n CI gates |
| `SWIR-OS-ARCHITECTURE.md` | Canonical measurable roadmap and architecture |
| `SWIR-PRODUCT-BASELINE-1.0.md` | Mandatory daily-use product baseline |
| `SWIR-ROADMAP-STANDARD.md` | Locked roadmap dashboard format |
| `assets/branding/` | SWIR OS visual identity assets |

`Swir/SWIR_OS` is the authoritative development repository. `Swir/swir.github.io` is presentation/status only and is not an operating-system source/update authority.

---

## 🗺️ Roadmap & releases

Development currently prioritizes the highest-impact path to a dependable Desktop/System platform:

1. harden the Desktop host/update/signing lifecycle,
2. complete dependency-aware System package updating and journaled recovery on top of the verified common provider boundary,
3. build the native SWIR desktop shell and mandatory native application suite,
4. finish firmware/vendor-source transaction and recovery paths,
5. complete installer/recovery, full-system i18n, reliability, accessibility and physical-hardware qualification.

The authoritative roadmap is [`SWIR-OS-ARCHITECTURE.md`](SWIR-OS-ARCHITECTURE.md). Public releases are only considered available when a real GitHub Release/build exists and its required verification passes.

---

## ⚠️ Current limitations

SWIR OS is under active development and is **not yet a finished System Edition distribution**.

- System Edition still lacks the final native SWIR desktop shell and full daily-use native application suite.
- Desktop Edition remains a preview line.
- Production package-signing provisioning is not yet fully cut over.
- The signed GitHub-backed update feed/user-policy roadmap gate remains open.
- Flatpak and AppImage provider paths are experimental and not silently enabled in the production System provider factory.
- `fwupd`/LVFS mutation, exceptional vendor repositories, dependency-aware system updates and complete recovery remain separate open roadmap gates.
- Hardware catalog coverage is intentionally limited; current CI does not claim broad physical-hardware qualification.
- Managed Wine execution is verified as a controlled compatibility foundation, not as a claim that every Windows application works.
- Full localization of every native System Edition application screen is not complete.

These limitations are kept visible instead of presenting prototypes as finished product capabilities.

---

## 🛡️ Development principles

1. Build real functionality before increasing roadmap progress.
2. Keep privileged operations behind permission-aware native brokers.
3. Prefer native Linux execution for System Edition core applications.
4. Use Wine/Proton only for managed Windows user-application compatibility.
5. Use trusted kernel/distribution/LVFS/official-vendor sources for drivers and firmware.
6. Keep package, update and firmware mutations journaled and recoverable where the roadmap claims support.
7. Keep Web Edition useful for prototyping without making the final OS browser-dependent.
8. Keep `Swir/SWIR_OS` as the canonical source and `swir.github.io` as presentation only.
9. Never store production private signing keys in the repository.

---

## 🔎 Search Keywords

`SWIR OS` • `Linux desktop operating system` • `hybrid desktop OS` • `Debian 13 desktop` • `native Linux applications` • `Wine Proton compatibility` • `Windows apps on Linux` • `Linux package management` • `SWIR Package Provider` • `Linux driver center` • `PCI USB hardware manager` • `linux-firmware` • `fwupd LVFS` • `NetworkManager desktop` • `secure software updates` • `Linux recovery rollback` • `Windows desktop host` • `open source desktop platform`

---

<div align="center">

### `BUILD • VERIFY • BOOT • EVOLVE`

**SWIR OS — by Swir**

[**← SWIR profile**](https://github.com/Swir) · [**All projects →**](https://github.com/Swir?tab=repositories) · [**Project status site →**](https://swir.github.io/)

</div>
