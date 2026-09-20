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
- `verified` — a later read-only fwupd inventory shows the same bound device at the reviewed target version and the required fwupd history evidence does not report failure.
- `failed-needs-recovery` — result is ambiguous or failed; no automatic rollback is attempted.

Every successful mutation result still carries `verificationRequired: true`. Transaction verification is a separate step and does not prove that a required reboot/power-cycle happened, nor does it count as physical-hardware qualification.

## Post-update verification

`system/hardware/firmware-update-verification-service.mjs` adds a fail-closed, read-only verification layer over the transaction journal and trusted fwupd inventory.

Verification is allowed only for `committed`, `staged-reboot-required` or already `verified` transactions. It reopens the exact journal entry, binds to the same device ID and target version, requires trusted read-only fwupd inventory, rejects duplicate device identities, and records the observed installed version plus fwupd history state back into the owner-only transaction journal.

The trusted read-only fwupd surface includes `get-devices`, `get-updates` and `get-history`. For reboot-required updates SWIR does **not** accept `get-devices` alone as success evidence: the current installed version must equal the reviewed target and the latest matching history record must report update state `2` with no update error. A history state `3`, any history error, a missing history record, a missing device or an unchanged version blocks verification or keeps it pending. This protects SWIR from treating a live device view as authoritative when fwupd history records a failed post-reboot update.

Failed or still-executing transactions are never promoted by the verifier, and the verifier never retries, downgrades, force-flashes or claims automatic rollback. The verification result intentionally includes `physicalHardwareQualification: false` and `rebootOrPowerCycleProven: false`; those stronger claims require separate operator-controlled evidence on supported hardware.

## Driver Center integration

`DriverMutationTransactionService` already delegates `review-fwupd` through a child object exposing `update(candidate, context)` and requires result schema `swir.firmware-transaction-result/0.1`. `FirmwareUpdateTransactionService` implements that interface.

The caller first obtains `firmwareTransactions.plan(candidate)`, displays the plan, then invokes the parent driver transaction with the same context containing `plan`, the exact `confirmationDigest`, and the authenticated local `actorId` when available. The parent forwards that context to the firmware child; the child independently revalidates the plan and live metadata and owns the firmware journal.

The native GTK4 Hardware & Driver Center also exposes the trusted LVFS candidate set as a bounded **Firmware updates** diagnostics tab. `driver-center-report.mjs` obtains the same read-only `fwupdmgr` inventory and adds only candidates that retain the `fwupd-lvfs` / `lvfs` source binding, no direct-download URL, and `mutationAuthorized:false`. The Python adapter revalidates that boundary and caps the visible set before the UI renders device name, current/target version, release ID, checksum count and reboot-review requirement. The graphical app intentionally exposes no firmware mutation button, does not accept a confirmation digest and cannot invoke the privileged update transaction; mutation remains a separate reviewed broker path.

## Physical qualification harness

`firmware-physical-qualification-service.mjs` and `firmware-physical-qualification-cli.mjs` provide an operator-controlled evidence path for **dedicated physical lab hardware only**. They do not make CI, a VM, a mock fwupd result, or the mere presence of the harness count as physical qualification.

The harness deliberately wraps the existing transaction and verification services rather than creating a second firmware flasher:

1. `preflight --device <fwupd-device-id>` selects exactly one trusted LVFS candidate, creates the normal reviewed firmware plan, captures privacy-minimized host evidence, and persists an owner-only qualification session. This step does not flash firmware.
2. `apply --session <id>` requires an interactive TTY, an explicit dedicated-physical-hardware attestation, the exact plan digest and an exact typed `APPLY <device-id> <digest>` phrase. It refuses a changed machine/boot since preflight and then delegates mutation to `FirmwareUpdateTransactionService`, which performs its own live metadata revalidation.
3. If the reviewed LVFS metadata requires reboot or power-cycle, the operator performs it separately. The harness never reboots automatically.
4. `verify --session <id>` delegates post-update checks to `FirmwareUpdateVerificationService`, captures the new boot identity and requires the same hashed machine identity. For a reboot-required update, the boot ID must actually differ from preflight before the session becomes eligible for final review.
5. `finalize --session <id>` is a separate interactive action. It requires physical observation, dedicated-hardware and recovery-review attestations plus an exact `QUALIFY <device-id> <target-version> <digest>` phrase. Only then may that exact session record `physicalHardwareQualification:true`.

Qualification evidence intentionally stores only a SHA-256 hash of `/etc/machine-id`, the kernel boot ID, timestamps and bounded firmware/session metadata. The raw machine ID is not persisted. DMI product/vendor strings are used only to derive a bounded virtualization hint and are not stored. A virtualization hint blocks the physical qualification flow, while the absence of such a hint **does not prove** that hardware is physical; final qualification remains an explicit operator attestation backed by the real fwupd transaction/history evidence.

The qualification journal defaults to `/var/lib/swir/qualification/firmware`, requires a private root-owned directory in production and writes `0600` evidence atomically. CI fixtures cannot be finalized as physical evidence (`ciEvidenceCountsAsPhysicalQualification:false`), apply/finalize have no non-interactive confirmation bypass, and the qualification layer exposes no arbitrary firmware file/URL, automatic reboot or automatic rollback path.

This harness is for disposable/dedicated qualification machines with known vendor recovery instructions. Do **not** use it as an unattended updater or on a user's primary device. Creating or testing the harness does not close the fwupd/LVFS or physical-hardware roadmap item: an accepted real-device session is still required.

## Verification

`firmware-update-transaction-selftest.mjs` uses a fake read-only fwupd/LVFS inventory and fake command runner; it never flashes hardware. It verifies plan hashing, exact digest confirmation, stale-plan refusal, ambiguous-candidate refusal, safe argv construction, journal state/permissions, no automatic reboot/rollback and rejection of unsafe flags.

`firmware-update-verification-selftest.mjs` creates real journaled transaction fixtures through `FirmwareUpdateTransactionService` and then exercises the separate verifier. It proves exact target-version plus history verification, persistence of verified evidence, pending reboot/power-cycle handling, missing-history handling, explicit rejection of a history-reported reboot failure even when the live device view has no error, no physical-qualification claim, no automatic retry and no automatic rollback.

`firmware-physical-qualification-selftest.mjs` uses injected transaction, verification and host fixtures only; it never invokes `fwupdmgr`. It proves that non-interactive apply is rejected, exact digest/typed confirmations are mandatory, a reboot before apply invalidates preflight, a detected virtualization hint blocks mutation, a required reboot must change boot identity before final review, CI/fixture evidence cannot be finalized, and owner-only journal permissions are enforced.

`firmware-driver-mutation-integration.selftest.mjs` wires the real `DriverMutationTransactionService` to the real firmware transaction service with controlled fakes only at the fwupd inventory/command boundary. It verifies that the reviewed plan/digest reaches the child transaction, the parent records the child journal identity, and a reboot-required result propagates as a recovery-relevant parent state.

`.github/workflows/system-firmware-update-transactions.yml` runs syntax, transaction, post-update verification, physical-qualification harness and Driver Center integration self-tests on the normal GitHub runner and on Debian 13, the current System Edition base. The workflow never invokes qualification `apply` or `finalize`. `.github/workflows/system-native-hardware-center.yml` additionally maps the real GTK4 Hardware Center on headless Wayland and asserts that firmware inventory remains read-only, rows stay bounded and the UI exposes no firmware mutation controls. These are contract/runtime tests only, not evidence of a real firmware flash.

## Required E2E before roadmap completion

A later disposable-machine or dedicated physical-hardware qualification must use a genuinely fwupd-supported device and keep VM/emulation evidence separate from physical evidence. It must cover preview, explicit digest confirmation, mutation, interruption/recovery handling, required reboot or power cycle, post-boot `fwupdmgr` history/device verification, persistence of the SWIR journal, and confirmation that the installed device version matches the reviewed target. No test may flash a user's real device without explicit interaction.

The accepted real-device evidence should include the finalized qualification session ID, exact SWIR commit, exact plan digest, bound device/release/target version, whether reboot/power-cycle was required, post-boot boot-identity change when required, verifier result, and any recovery observation. It must remain clear that one qualified device/release does not imply support for every computer or firmware family.
