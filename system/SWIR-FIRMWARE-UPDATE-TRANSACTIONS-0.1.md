# SWIR OS firmware update transactions 0.1

Status: development contract. This layer does **not** make System Edition hardware-ready by itself and does not close the Hardware/Driver Center roadmap item.

## Purpose

`system/hardware/firmware-update-transaction-service.mjs` is the privileged mutation boundary intentionally missing from the read-only `fwupd-lvfs-service.mjs`. Discovery remains read-only; mutation is a separate reviewed transaction.

Upstream fwupd exposes machine-readable discovery with `get-updates --json` and supports updating a selected device with `update [DEVICE-ID]`. SWIR therefore refuses an ambiguous device with more than one live LVFS candidate instead of guessing which release `update` would choose. It never accepts a local firmware file or arbitrary URL.

## Safety contract

A transaction is allowed only when all of these conditions hold:

- the candidate came from the existing `fwupd-lvfs` inventory and the `lvfs` remote;
- device ID, current version, target version, release ID, LVFS source ref and SHA-1/SHA-256 metadata checksums are bound into the plan;
- exactly one LVFS candidate exists for the device;
- the user/operator reviews the generated plan and confirms its exact SHA-256 digest;
- immediately before mutation, live inventory is queried again and must match the reviewed binding;
- `/usr/bin/fwupdmgr` resolves exactly to the allowlisted executable, is not group/world writable and is root-owned in production;
- execution uses argv arrays with `shell:false`; no arbitrary command, URL or local archive is accepted;
- SWIR never adds `--force`, `--allow-older`, `--allow-reinstall` or `--no-safety-check`;
- `--no-reboot-check` prevents the transaction from autonomously rebooting the computer; reboot/power-cycle stays a separate explicit action;
- a root-owned `0600` journal is durably written before `fwupdmgr update` starts;
- firmware rollback is never promised automatically. An interrupted/failed flash or a staged reboot requires operator review and device-specific recovery guidance.

The command boundary is intentionally narrow:

`/usr/bin/fwupdmgr update <bound-device-id> --assume-yes --no-reboot-check --no-unreported-check --json`

`--assume-yes` is reached only after the SWIR plan digest has already been explicitly confirmed. fwupd device safety checks remain enabled.

## Transaction states

- `prepared` — journal exists and no firmware mutation has started.
- `executing` — the exact reviewed device update command is running.
- `committed` — fwupd returned success and the candidate did not declare a reboot requirement.
- `staged-reboot-required` — fwupd returned success for a candidate whose metadata requires reboot; SWIR does not reboot automatically.
- `failed-needs-recovery` — result is ambiguous or failed; no automatic rollback is attempted.

Every successful result still carries `verificationRequired: true`. Firmware version/history must be checked after any required reboot or power cycle before hardware qualification evidence can be claimed.

## Driver Center integration

`DriverMutationTransactionService` already delegates `review-fwupd` through a child object exposing `update(candidate, context)` and requires result schema `swir.firmware-transaction-result/0.1`. `FirmwareUpdateTransactionService` implements that interface.

The caller first obtains `firmwareTransactions.plan(candidate)`, displays the plan, then invokes the parent driver transaction with the same context containing `plan`, the exact `confirmationDigest`, and the authenticated local `actorId` when available. The parent forwards that context to the firmware child; the child independently revalidates the plan and live metadata and owns the firmware journal.

## Verification

`firmware-update-transaction-selftest.mjs` uses a fake read-only fwupd/LVFS inventory and fake command runner; it never flashes hardware. It verifies plan hashing, exact digest confirmation, stale-plan refusal, ambiguous-candidate refusal, safe argv construction, journal state/permissions, no automatic reboot/rollback and rejection of unsafe flags.

`firmware-driver-mutation-integration.selftest.mjs` wires the real `DriverMutationTransactionService` to the real firmware transaction service with controlled fakes only at the fwupd inventory/command boundary. It verifies that the reviewed plan/digest reaches the child transaction, the parent records the child journal identity, and a reboot-required result propagates as a recovery-relevant parent state.

`.github/workflows/system-firmware-update-transactions.yml` runs syntax, transaction and Driver Center integration self-tests on the normal GitHub runner and on Debian 13, the current System Edition base. These are contract tests only, not evidence of a real firmware flash.

## Required E2E before roadmap completion

A later disposable-machine or dedicated physical-hardware qualification must use a genuinely fwupd-supported device and keep VM/emulation evidence separate from physical evidence. It must cover preview, explicit digest confirmation, mutation, interruption/recovery handling, required reboot or power cycle, post-boot `fwupdmgr` history/device verification, and persistence of the SWIR journal. No test may flash a user's real device without explicit interaction.
