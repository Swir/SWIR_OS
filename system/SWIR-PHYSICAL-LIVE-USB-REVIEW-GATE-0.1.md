# SWIR OS System Edition — physical Live USB review gate 0.1

## Purpose

The existing physical evidence collector proves a read-only two-phase candidate:

`physical USB Live boot -> installed disk boot with source USB detached`

This review gate closes the remaining **evidence-quality gap** before a physical
qualification run can be considered for the roadmap. It binds the operator's
manual safety/usability review to the exact Live evidence digest, installed
evidence digest, final image SHA-256, image byte length and source commit.

A passing review is **review-ready evidence**. It does not change the roadmap
checkbox by itself, does not claim Secure Boot/legacy BIOS support and does not
claim broad PC compatibility. The final roadmap decision still requires a
human review of evidence from dedicated physical test hardware.

## Safety and privacy boundary

The new tools remain non-destructive and unprivileged:

- no disk formatting, partitioning, mounting or installer execution;
- no `sudo`, `pkexec`, shell execution or reboot/poweroff commands;
- review output is created with mode `0600`, exclusive creation and no overwrite;
- the free-form hardware scope label is hashed locally and never stored raw;
- serial numbers, usernames, hostnames, MAC addresses and DMI UUIDs are not
  added to the review bundle;
- Secure Boot, legacy BIOS and all-PC support claims are forced to `false`.

## Required files

Complete the procedure in
[`SWIR-PHYSICAL-LIVE-USB-QUALIFICATION-0.1.md`](SWIR-PHYSICAL-LIVE-USB-QUALIFICATION-0.1.md)
and keep:

1. `swir-live-physical-evidence.json` from the physical Live session;
2. `swir-installed-physical-evidence.json` after power-off, physical USB
   removal and boot from the installed test disk;
3. a local observations JSON object containing every required observation below
   with the value `true` only after it was actually checked.

## Required observations

The observation object is intentionally explicit. All fields are required:

```json
{
  "finalImageSha256VerifiedBeforeWrite": true,
  "bootedFromPhysicalUsb": true,
  "graphicalLiveSessionUsable": true,
  "internalDiskIdleUnchanged": true,
  "sourceUsbTargetRefused": true,
  "cancelLeavesTargetUnchanged": true,
  "wrongConfirmationLeavesTargetUnchanged": true,
  "targetAndPartitionPlanReviewed": true,
  "destructiveConfirmationBoundToTarget": true,
  "installedToDedicatedEmptyDisk": true,
  "sourceUsbPhysicallyDetachedBeforeInstalledBoot": true,
  "installedBootWithoutSourceUsb": true,
  "graphicalInstalledSessionUsable": true,
  "persistenceVerified": true,
  "graphicsVerified": true,
  "networkVerified": true,
  "audioVerified": true,
  "suspendResumeVerified": true,
  "firmwareInventoryReviewed": true,
  "noUserDataDiskUsed": true
}
```

The creator rejects missing, false or unknown observation keys. This prevents a
partial checklist from being silently promoted to qualification evidence.

## Create the bound review bundle

Use the exact SHA-256 and byte size of the final image that was written to the
USB, plus the full 40-character source commit used to build it:

```bash
python3 system/e2e/new-physical-live-usb-review.py \
  --live ~/swir-live-physical-evidence.json \
  --installed ~/swir-installed-physical-evidence.json \
  --observations ~/swir-physical-observations.json \
  --image-sha256 <final-image-sha256> \
  --source-commit <40-character-git-sha> \
  --image-bytes <exact-image-byte-length> \
  --hardware-scope "dedicated test machine local label" \
  --output ~/swir-physical-review.json
```

`--hardware-scope` exists only to create a stable privacy-safe SHA-256 identity
for the tested hardware scope. The raw label is not written to the review JSON.
Do not put serial numbers or personal identifiers in it.

The creator first re-runs the two-phase sequence verifier. It refuses to create
review output if the Live/installed evidence pair is not already valid. It then
binds both evidence digests to the image provenance and the explicit operator
observations and adds a deterministic review digest.

## Verify the final physical review

Run:

```bash
python3 system/e2e/verify-physical-live-usb-review.py \
  --live ~/swir-live-physical-evidence.json \
  --installed ~/swir-installed-physical-evidence.json \
  --review ~/swir-physical-review.json
```

The verifier fails closed when:

- the review or collector evidence was modified after creation;
- the review references a different Live or installed evidence digest;
- image SHA-256, image byte length or source commit provenance is malformed;
- any required observation is missing/false or an unknown observation key is
  injected;
- the hardware sequence no longer satisfies the physical UEFI USB -> detached
  installed-disk rules;
- Secure Boot, legacy BIOS or all-PC claims are asserted.

A successful result sets `reviewReady=true` and
`physicalHardwareRoadmapCompletionClaimed=false`. The latter is deliberate: CI
can validate the evidence machinery, but CI cannot manufacture the real
physical test that the roadmap requires.

## CI contract

`.github/workflows/system-physical-live-usb-review.yml` verifies:

- Python syntax and the existing two-phase sequence contract;
- a complete review is accepted;
- missing observations, cross-evidence replay, malformed image provenance,
  unsupported claims and review tampering are rejected;
- review creation is mode-0600/exclusive and does not retain the raw hardware
  scope label;
- incomplete observations cannot create an output file;
- production review tools contain no destructive or privilege-escalating
  command path.

This gate reduces the manual physical qualification step to collecting genuine
hardware evidence and an explicit review. It does not replace that hardware
step and does not alter the current 61/65 roadmap count on its own.
