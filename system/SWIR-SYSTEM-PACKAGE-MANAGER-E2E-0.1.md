# SWIR System Package Manager Image E2E 0.2

## Purpose

This gate verifies the Debian System Edition package path against a disposable Debian 13 root filesystem built from the canonical SWIR System Edition base profile. It covers dependency-aware package planning, a real journaled APT installation, and fail-closed recovery of an interrupted APT transaction when the package mutation completed but the caller lost the acknowledgement before the journal could be committed.

The recovery path is deliberately conservative. It does **not** guess an inverse APT operation. It may convert an interrupted transaction to `committed` only after a fresh `packages.recover` authorization, an exact live package-state comparison, `dpkg --audit`, `apt-get check`, and the native package health check all agree that the original intended state was reached. Ambiguous or inconsistent state remains `failed-needs-recovery` for manual/recovery-environment handling.

This still does not complete the broader roadmap item for journaled **driver + firmware + package** transactions, because driver mutation/recovery and full recovery-mode integration remain separate gates.

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
        +---------------- normal completion ----------------+
        |                                                   |
        v                                                   v
native health check                                    committed

interrupted mutation / lost acknowledgement
        |
        v
failed-needs-recovery journal
        |
        v
packages.recover authorization bound to original digest
        |
        v
fresh package snapshot + dpkg --audit + apt-get check
        |
        v
native health / intended-state verification
        |
        +--> verified exact state -> committed (no new package mutation)
        |
        +--> ambiguous/broken state -> failed-needs-recovery
```

`SystemPackageStack.execute()` resolves APT dependencies before handing the plan to the transaction service. Because the dependency plan is attached to the package plan before its digest is calculated, the durable journal cryptographically binds the dependency closure that was reviewed immediately before mutation.

`AptInterruptedTransactionRecoveryService` is a separate production recovery component. It reads the existing durable transaction journal and is allowed to reconcile only APT records in `mutating`, `verifying`, or `failed-needs-recovery`. It has no package executor and therefore cannot silently install, remove, upgrade, downgrade, or otherwise reverse packages during reconciliation.

## APT safety properties

- Dependency discovery uses only `/usr/bin/apt-get -s` with a fixed argv shape and `shell=false`.
- `apt-get`, `dpkg`, and package-state probes must use trusted system paths; the live consistency probe requires root-owned binaries that are not group/world writable.
- The resolver cannot supply repository URLs or disable signature verification.
- The production privileged executor still validates the original provider command exactly.
- After authorization, the APT transport adds only `-y` so a closed, already-authorized request can run deterministically with ignored stdin.
- `DEBIAN_FRONTEND=noninteractive` is set explicitly; inherited user environment is not passed through.
- Arbitrary executables and arbitrary package-manager arguments remain rejected.
- Recovery requires the separate `packages.recover` Polkit scope and binds the original SHA-256 plan digest, package identity, operation, and current process subject.
- Recovery consistency probes are read-only: `dpkg --audit` and `apt-get -o Debug::NoLocking=1 check`.
- APT recovery never performs an automatic inverse package mutation. If live state is ambiguous, the journal remains failed-needs-recovery.

## What the image E2E proves

The CI gate builds the selected Debian 13 rootfs with `mmdebstrap` and Debian's archive keyring, installs Node.js inside that disposable rootfs, then uses `cowsay` as a deterministic package fixture.

The test requires all of the following:

1. `cowsay` is not installed before the first transaction.
2. Signed `debian-main` policy is present and root-owned.
3. A real `apt-get -s install -- cowsay` dependency simulation succeeds.
4. The resulting affected-package set contains the requested package plus at least one additional dependency/configuration package.
5. The dependency plan is attached to the exact plan that enters the durable transaction journal.
6. The transaction captures the pre-state before mutation.
7. The contained root E2E executor performs the exact validated APT request with the same non-interactive transport behavior as production.
8. APT actually installs the package inside the disposable System Edition rootfs.
9. The normal transaction reaches `committed` and its journal remains owner-only (`0600`).
10. The native `/usr/games/cowsay` entry point passes the production native health verifier.
11. Dependency-aware update and remove plans are also resolved through APT simulation.
12. A second transaction performs a real APT remove and then deliberately loses the executor acknowledgement after APT succeeds.
13. The original transaction service durably records `failed-needs-recovery` instead of claiming success.
14. A fresh recovery service re-authorizes `packages.recover` against the exact original plan digest.
15. Recovery observes the intended removed state, a clean `dpkg --audit`, a successful `apt-get check`, and a healthy remove postcondition.
16. The interrupted journal reaches `committed` only from that verified live evidence.
17. Recovery evidence explicitly records `packageMutationPerformedByRecovery=false`.

The E2E authorization broker is intentionally a contained CI root harness because the chroot does not run a real user desktop/polkit session. Production Polkit authorization remains covered by the existing security and package-stack contracts; the image gate does not weaken or replace that boundary.

## Failure model

The covered interruption is the high-value acknowledgement-loss case: the trusted APT command has already completed successfully, but the calling process fails before execution/health/commit evidence is durably finalized. This is important because blindly re-running or inversely mutating packages in that situation can make a healthy machine worse.

The recovery service therefore distinguishes **reconciliation** from **rollback**. It proves what state the package database is already in and only commits the journal when that state is unambiguous. It does not claim to repair a half-configured `dpkg` database, restore removed dependency packages, roll back an arbitrary package upgrade, or recover from filesystem corruption.

## Roadmap interpretation

A green exact-revision run continues to support the completed roadmap item **dependency-aware system package manager/updater** and additionally proves a real package-side interrupted-transaction recovery slice.

It is **not yet sufficient** to mark **journaled driver/firmware/package transactions** complete because the checkbox spans all three mutation domains. It is also not sufficient to mark **filesystem integration and recovery mode** or **hardware/firmware rollback or documented manual recovery path** complete. Those remain open until their own implementations and exact-revision gates exist.
