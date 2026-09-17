# SWIR System Package Manager Image E2E 0.1

## Purpose

This gate moves the Debian System Edition package path beyond preview-only provider planning. It verifies dependency resolution and one real journaled APT installation inside a disposable Debian 13 root filesystem built from the canonical SWIR System Edition base profile.

The scope is deliberately narrower than full system-update recovery. Interrupted-update recovery remains a separate roadmap deliverable and is not claimed by this gate.

## Production architecture covered

```text
SWIR package manifest
        |
        v
DistributionPackageProvider
        |
        v
APT dependency simulation (read-only)
        |
        v
resolved dependency plan bound into package plan digest
        |
        v
trust / authorization / pre-state snapshot
        |
        v
durable transaction journal
        |
        v
allowlisted apt-get mutation
        |
        v
native entry-point health verification
        |
        v
committed journal state
```

`SystemPackageStack.execute()` now resolves APT dependencies before handing the plan to the transaction service. Because the dependency plan is attached to the package plan before its digest is calculated, the durable journal cryptographically binds the dependency closure that was reviewed immediately before mutation.

## APT safety properties

- Dependency discovery uses only `/usr/bin/apt-get -s` with a fixed argv shape and `shell=false`.
- `apt-get` must be root-owned and not group/world writable.
- The resolver cannot supply repository URLs or disable signature verification.
- The production privileged executor still validates the original provider command exactly.
- After authorization, the APT transport adds only `-y` so a closed, already-authorized request can run deterministically with ignored stdin.
- `DEBIAN_FRONTEND=noninteractive` is set explicitly; inherited user environment is not passed through.
- Arbitrary executables and arbitrary package-manager arguments remain rejected.

## What the image E2E proves

The CI gate builds the selected Debian 13 rootfs with `mmdebstrap` and Debian's archive keyring, installs Node.js inside that disposable rootfs, then uses `cowsay` as a deterministic package fixture.

The test requires all of the following:

1. `cowsay` is not installed before the transaction.
2. Signed `debian-main` policy is present and root-owned.
3. A real `apt-get -s install -- cowsay` dependency simulation succeeds.
4. The resulting affected-package set contains the requested package plus at least one additional dependency/configuration package.
5. The dependency plan is attached to the exact plan that enters the durable transaction journal.
6. The transaction captures the pre-state before mutation.
7. The contained root E2E executor performs the exact validated APT request with the same non-interactive transport behavior as production.
8. APT actually installs the package inside the disposable System Edition rootfs.
9. The transaction reaches `committed` and its journal remains owner-only (`0600`).
10. The native `/usr/games/cowsay` entry point passes the production native health verifier.
11. Dependency-aware update and remove plans are also resolved through APT simulation.

The E2E authorization broker is intentionally a contained CI root harness because the chroot does not run a real user desktop/polkit session. Production Polkit authorization remains covered by the existing security and package-stack contracts; the image gate does not weaken or replace that boundary.

## Roadmap interpretation

A green exact-revision run is sufficient evidence for the scoped roadmap item **dependency-aware system package manager/updater**: the Debian System Edition has a production APT dependency resolver integrated before privileged transactions, an actual journaled install path, health verification, and update/remove dependency planning.

It is **not** evidence for **journaled package transactions and system recovery after interrupted updates**. The transaction journal already exists, but crash/interruption repair and recovery must be demonstrated separately before that checkbox can move to `[x]`.
