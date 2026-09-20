# SWIR fwupd Debian 13 Runtime Qualification 0.1

## Purpose

This gate verifies that the System Edition Debian 13 image/runtime actually provides the distro-managed `fwupd` userspace that SWIR's existing LVFS discovery, firmware transaction and post-update verification services are designed to use.

It closes a packaging/runtime-evidence gap only. It does **not** claim that a firmware update was flashed successfully on physical hardware and it does not complete the `fwupd/LVFS firmware updates where supported` roadmap item by itself.

## Verified runtime surface

`system/hardware/fwupd-debian13-runtime-qualification.mjs` fails closed unless all of the following are true on the qualified root:

- `/etc/os-release` identifies Debian 13;
- `dpkg-query` reports the `fwupd` package in installed state `ii` and returns its real installed version;
- `/usr/bin/fwupdmgr` is a real root-owned executable file and is not group/world writable;
- `/usr/libexec/fwupd/fwupd` is a real root-owned executable file and is not group/world writable;
- `/etc/fwupd/remotes.d/lvfs.conf` is a real root-owned regular file and is not group/world writable;
- the exact trusted `fwupdmgr` binary can execute its local `--help` surface successfully;
- SHA-256 evidence is recorded for the three trusted fwupd/LVFS files above.

The version is intentionally read from the installed Debian package instead of being hard-coded, so normal Debian 13 security/stable updates do not require weakening the gate.

## Safety boundary

The qualification is observation-only. It does not call firmware mutation commands, refresh or modify remotes, enable a repository, accept a firmware URL/file, reboot the machine or access a physical device.

The emitted evidence explicitly records:

- `readOnlyQualification: true`;
- `networkAccessRequired: false` for the qualification step itself;
- `firmwareMutationAllowed: false`;
- `remoteMutationAllowed: false`;
- `arbitraryFirmwareFileOrUrlAllowed: false`;
- `physicalHardwareQualification: false`;
- `secureBootQualification: false`.

Installing `fwupd` in the disposable CI container is test-environment preparation from Debian repositories; it is not a SWIR firmware transaction.

## CI

`.github/workflows/system-fwupd-debian13-runtime.yml` has two independent gates:

1. a Node syntax/self-test and static observation-only policy gate;
2. a real `debian:trixie-slim` runtime that installs Debian's `fwupd` package and qualifies the production paths and package state.

The gate deliberately does not use CI as physical-hardware evidence. The existing guarded physical qualification workflow remains the authority for an eventual real-device session.

## Roadmap accounting

Passing this runtime qualification improves evidence for the open System Edition firmware milestone, but **must not** change the canonical roadmap percentage on its own. The roadmap item remains open until the required supported-hardware update path and accepted real-device evidence satisfy its documented completion gate without weakening the transaction, verification, recovery or physical-qualification controls.
