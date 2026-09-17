# SWIR Driver Mutation Transactions 0.1

## Purpose

SWIR Driver Center remains read-only by default. A diagnostic driver plan is never executable by itself. When an operator explicitly selects a supported privileged action, this layer binds that exact Driver Center operation to an already guarded child transaction and writes a durable parent journal **before** handing control to the child service.

The goal is to make driver-related package and firmware changes recoverable and auditable without introducing a second unsafe mutation path.

```text
Hardware Service / Driver Center preview
               |
               v
explicit selected operation
               |
      +--------+--------+
      |                 |
      v                 v
review-package       review-fwupd
      |                 |
      v                 v
System Package       Firmware Update
Transaction          Transaction
      |                 |
      +--------+--------+
               |
               v
child durable journal + Driver Center parent journal
```

## Supported routes

### Distribution package backed driver/firmware support

`review-package` can delegate only to the production `swir.package.system` transaction service. The selected package must already be listed in `packageCandidates` for that exact Driver Center operation. The child package plan must require its own durable journal and keep repository signature verification and source allowlisting inside the package transaction boundary.

### fwupd/LVFS firmware

`review-fwupd` can delegate only to a candidate discovered as trusted `fwupd-lvfs` / `lvfs`. Direct firmware URLs remain forbidden and discovery cannot pre-authorize mutation. The child firmware transaction owns its authorization, command allowlist, pre-mutation journal, postcondition verification and reboot reconciliation.

## Deliberately unsupported

Direct kernel-module load/unload or replacement is **not** an automatic Driver Center mutation route. `review-module` stays review-only. The System Edition primary driver path remains in-tree Linux drivers plus distribution firmware/packages; SWIR does not inject Windows kernel drivers and does not fetch random driver binaries.

This separation is intentional. Kernel module operations have different lifetime and rollback semantics and should not be silently treated as ordinary package or firmware updates.

## Journal contract

The parent journal uses `swir.driver-mutation-transaction/0.1` and defaults to:

```text
/var/lib/swir/transactions/drivers/<transaction-id>.json
```

The journal directory is private, files are written atomically with mode `0600`, and each entry binds:

- the exact Driver Center operation;
- a SHA-256 digest of the mutation request;
- the selected package or firmware binding;
- the child transaction class and transaction id after delegation;
- recovery ownership and operator-review state.

A failed or ambiguous child handoff is recorded as `failed-needs-recovery`. A firmware transaction that requires a real reboot is recorded as `staged-reboot-required` and remains owned by the child firmware reconciliation path. The coordinator does not invent automatic rollback when the child service cannot prove one.

## Recovery model

`inspectRecovery()` is read-only. It reports parent transactions that still require child reconciliation or operator review. It never retries a package installation, flashes firmware, loads a module, or performs rollback by itself.

The dedicated System recovery environment can inspect these journals alongside the existing package and firmware journals. Mutation remains disabled in read-only recovery mode until a separately verified recovery workflow explicitly authorizes it.

## Verification boundary

The contract self-test proves:

1. exact Driver Center operation binding;
2. package candidate binding to a System package transaction;
3. fwupd/LVFS source restrictions;
4. journal-before-delegation behavior;
5. parent-to-child transaction references;
6. reboot-staged firmware recovery visibility;
7. fail-closed behavior for unsupported module mutation, unlisted packages and untrusted firmware sources;
8. private journal file permissions;
9. failed child mutation becoming `failed-needs-recovery` rather than being silently retried.

The CI test does **not** flash runner firmware or claim broad hardware qualification. Real firmware mutation remains limited to hardware that fwupd/LVFS reports as supported, and the separate fwupd/LVFS roadmap gate stays open until that live supported-device path is verified safely.
