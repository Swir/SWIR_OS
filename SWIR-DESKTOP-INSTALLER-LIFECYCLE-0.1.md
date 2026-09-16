# SWIR Desktop Installer Lifecycle 0.1

This document defines the current fail-closed installer lifecycle for SWIR OS Desktop Edition. It complements the release/update contracts and describes behavior implemented by the one-file Setup executable.

## Distribution rule

The end-user artifact remains one self-contained file:

```text
SWIR-Desktop-Setup-<version>-<channel>.exe
```

The Setup embeds the already verified Desktop release ZIP. The release contains the self-contained .NET runtime, the repository-pinned Microsoft WebView2 Fixed Version Runtime, core language resources and the SWIR Desktop runtime. Manual prerequisite downloads are not part of the supported end-user path.

## Installation identity

Every accepted embedded payload is bound to:

```text
version
channel
package SHA-256
entry point
desktop-host-build.json release identity
bundled-runtime integrity manifest
```

Setup rejects mismatched release version/channel identity even if an archive has otherwise valid structure. Installation receipts bind the package identity to the final versioned installation directory.

## Versioned layout

The installer root contains versioned immutable runtime directories plus small atomic selection pointers:

```text
SWIR OS Desktop/
  current.json
  previous.json          # only when a verified rollback candidate exists
  0_5_7-preview/
  0_5_8-preview/
```

A new version is extracted into a private staging directory and fully verified before it can be promoted. The previous verified installation is retained as the rollback candidate when upgrading to another version.

## Supported Setup actions

```text
--verify-only
--repair
--rollback
--uninstall
--no-launch
--install-root <directory>
--lang <BCP-47>
--quiet
```

`--verify-only`, `--repair`, `--rollback` and `--uninstall` are mutually exclusive.

### Install / upgrade

- clean install creates a verified versioned runtime and `current.json`;
- installing a newer version first verifies the existing current runtime, preserves it in `previous.json`, stages and verifies the new payload, then switches `current.json`;
- normal reinstall of the exact current version re-verifies the existing runtime instead of silently overwriting it;
- an in-place downgrade is refused; rollback uses only the verified `previous.json` candidate.

### Repair

Repair is explicit. It is allowed only when the Setup package identity exactly matches the selected current installation. A damaged current runtime is never silently trusted or overwritten by a normal install.

Repair performs:

```text
verify Setup payload
  -> stage complete replacement
  -> verify staged runtime
  -> move damaged current to temporary backup
  -> promote verified replacement
  -> atomically refresh current pointer
  -> remove backup after commit
```

If promotion/commit fails, Setup attempts to restore the previous directory rather than leaving an unverified partial replacement selected.

### Rollback

Rollback requires both `current.json` and `previous.json`. Both referenced installations must have valid receipts, build identity and bundled-runtime integrity. Setup then atomically changes the selected current/previous pointers. No arbitrary directory can be supplied as a rollback target.

### Uninstall

Uninstall validates that the selected path remains inside the configured SWIR Desktop installation root and that its receipt matches the current pointer. This allows a damaged runtime to be removed without first treating its executable bytes as trusted.

If a verified previous version exists, uninstalling the current version restores that previous installation as current. If no verified previous version exists, Setup removes the active pointer and current versioned runtime.

## Localization

Installer user-facing status/error framing supports the 15 bundled SWIR core locales:

```text
en, pl, nb, de, es, fr, it, pt-BR,
uk, ru, tr, ar, he, ja, zh-Hans
```

Setup uses the Windows UI culture automatically. `--lang <BCP-47>` can explicitly select a language for controlled deployment/testing. Unsupported or invalid locale tags fall back to English. Language resources are compiled into Setup; users do not download language packs separately.

## Security properties

The installer lifecycle intentionally keeps these rules fail-closed:

- embedded ZIP SHA-256 must match installer metadata;
- archive traversal, absolute paths and symbolic links are refused;
- archive entry count and expanded size are bounded;
- final payload build identity must match Setup version/channel;
- bundled Host/WebView2 runtime integrity must verify before selection;
- install/previous pointers may reference only directories below the installer root;
- receipts must bind version, channel, package SHA-256 and final install path;
- upgrades cannot use an unverified current installation as the rollback baseline;
- downgrade by arbitrary installer execution is refused;
- rollback candidates are selected from verified installer state, not caller-provided paths.

## CI contract

`Desktop Installer Contract` exercises the lifecycle on Windows using real self-contained payloads. It covers localization mapping, embedded payload verification, clean install, tamper refusal, explicit repair, a synthetic newer-version upgrade, previous-version preservation, rollback, current-version uninstall with previous-version restoration, and final uninstall.

The synthetic newer version used by CI is an installer lifecycle fixture only. It does not change the public SWIR Desktop version or constitute a release milestone.
