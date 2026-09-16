<div align="center">

# SWIR OS

### Web → Desktop → Linux-based Hybrid System

**SWIR OS is an experimental operating-system platform that is evolving from a portable Web Edition into a native Desktop Edition and, later, a bootable Linux-based System Edition.**

[![System Contracts](https://github.com/Swir/SWIR_OS/actions/workflows/system-contracts.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/system-contracts.yml)
[![Desktop Windows Build](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-windows-build.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-windows-build.yml)
[![Desktop Release Trust Chain](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-release-trust-chain-contract.yml/badge.svg)](https://github.com/Swir/SWIR_OS/actions/workflows/desktop-release-trust-chain-contract.yml)
![Roadmap](https://img.shields.io/badge/ROADMAP-63.0%25-2ea043?style=for-the-badge)
![Done](https://img.shields.io/badge/DONE-34%2F54-1f6feb?style=for-the-badge)

</div>

---

## Project status

**Current Web Edition:** `1.7.13`  
**Desktop Host preview line:** `0.5.7-preview`  
**Roadmap:** `34 / 54` deliverables completed — **63.0%**

```text
█████████████░░░░░░░ 63.0%
```

SWIR OS is under active development. The Desktop Edition already has a real Windows host and native adapters, but the project must not yet be treated as a finished production operating system.

See [`SWIR-OS-ARCHITECTURE.md`](SWIR-OS-ARCHITECTURE.md) for the measurable Web → Desktop → System roadmap.

---

## Architecture

SWIR OS uses one portable application model across three editions:

```text
SWIR Application
      |
      v
SWIR App SDK
      |
      v
SWIR Platform API / SwirRuntime
      |
      +------------------+------------------+
      |                  |                  |
      v                  v                  v
 Web Adapter        Desktop Adapter       System Adapter
 Browser APIs       Native Windows        Linux services
 IndexedDB          Native filesystem     Linux filesystem
 PWA runtime        WebView2 host         Native shell/runtime
```

### Web Edition

The browser/PWA implementation is the design and compatibility laboratory for the shared SWIR APIs, Store, package model, applications and shell.

### Desktop Edition

The Windows Desktop Host currently provides native filesystem, App Data, device/network information, account/session information, process/service inspection, clipboard, tray, global shortcuts, file associations, notifications, `.swirapp` installation, sandboxed permissions and guarded update activation/rollback.

The lightweight host is based on **.NET 8 Windows Desktop + WebView2 Evergreen Runtime** and keeps privileged operations behind native brokers rather than exposing unrestricted browser-to-OS access.

### System Edition

The future bootable edition is deliberately **Linux-based and hybrid**:

- maintained Linux kernel/base,
- native Linux applications,
- Windows user applications through managed **Wine/Proton compatibility profiles**,
- common SWIR Package/Store provider layer,
- future distribution-package, Flatpak and AppImage providers,
- Hardware Service and SWIR Driver Center,
- NetworkManager integration,
- journaled system/package/driver operations with recovery paths.

Windows kernel drivers are not treated as a general Linux hardware solution.

---

## Trusted hardware sources

System Edition hardware support is designed around controlled sources only:

- Linux kernel in-tree drivers,
- `linux-firmware`,
- selected distribution repositories,
- `fwupd` / LVFS where supported,
- official vendor repositories for exceptional proprietary components.

The Hardware Catalog maps PCI/USB identities to kernel modules, firmware, packages and approved source classes. Unknown hardware may be diagnosed, but must not trigger arbitrary binary downloads.

---

## Desktop security model

Important Desktop foundations already present include:

- package execution-policy allowlists,
- owner/session-bound capabilities,
- isolated package execution contexts,
- native App Data isolation,
- signed catalog verification with Ed25519,
- SHA-256 package payload verification before archive parsing,
- anti-rollback catalog sequencing,
- current/next trust-root rotation contracts,
- transactional package/update slots,
- health-checked update activation and rollback,
- fail-closed release/runtime staging.

The production **package signatures and integrity verification** roadmap item remains open until the official production trust root and protected signing-key provisioning are fully deployed and verified.

---

## Repository map

| Path | Purpose |
|---|---|
| `desktop/windows/` | Windows Desktop Host, native brokers, updater and self-tests |
| `system/` | Linux-based System Edition contracts, Hardware Service and Driver Center foundation |
| `scripts/` | package, catalog, release and contract validators |
| `.github/workflows/` | Windows/Linux CI security and integration contracts |
| `SWIR-OS-ARCHITECTURE.md` | canonical measurable roadmap |
| `SWIR-ROADMAP-STANDARD.md` | locked roadmap dashboard standard |
| `swir-*.js`, `swir-*.html` | portable runtime, services and applications |

Historical experimental directories are intentionally retained but are not the active architecture target.

---

## Run the Web Edition locally

```bash
git clone https://github.com/Swir/SWIR_OS.git
cd SWIR_OS
python -m http.server 8000
```

Open `http://localhost:8000`.

---

## Build the Windows Desktop Host

Requirements:

- Windows 10/11 x64,
- .NET 8 SDK for development,
- Microsoft Edge WebView2 Evergreen Runtime.

```powershell
cd desktop/windows
dotnet build SWIR.Desktop.Host.csproj -c Release
```

For the controlled lightweight publish contract use:

```powershell
./publish-desktop-host.ps1 -PublishDir ./publish -ReleaseVersion 0.5.7 -Channel preview
```

The release pipeline performs additional signed-catalog, Store-package, update-bundle and trust-chain verification. A local build alone is not equivalent to an official verified release.

---

## Development principles

1. Prefer `SwirAppSDK`, `SwirPlatform` and `SwirRuntime` over edition-specific APIs.
2. Keep privileged operations behind explicit native brokers and permission checks.
3. Fail closed when package identity, authorization, trust roots or update state cannot be verified.
4. Do not download arbitrary driver binaries.
5. Keep Desktop/System work portable enough to reuse contracts across Windows and Linux implementations.
6. Do not mark a roadmap deliverable complete until the described function is implemented and verified.

---

## Author

Created and maintained by **Swir** — [github.com/Swir](https://github.com/Swir)

<div align="center">

**SWIR OS — building the path from a portable web shell to a real hybrid desktop/system platform.**

</div>
