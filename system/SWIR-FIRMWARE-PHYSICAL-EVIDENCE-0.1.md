# SWIR OS physical firmware qualification evidence 0.1

Status: development evidence contract. This layer reduces the manual handoff gap after a **real** fwupd/LVFS qualification. It does not flash firmware, does not prove that a host is physical by software alone, does not replace operator observation, and does not close the `fwupd/LVFS firmware updates where supported` roadmap item without an accepted real-device session.

## Purpose

`firmware-physical-qualification-evidence.mjs` exports a privacy-minimized, deterministic JSON bundle only after `FirmwarePhysicalQualificationService` has already reached the `qualified` state. The exporter refuses prepared, applied, verification-pending, CI-fixture, virtualized or otherwise incomplete sessions.

The bundle binds the finalized session to:

- qualification ID and finalization timestamp;
- exact fwupd device ID, target version, release ID and LVFS source reference;
- exact reviewed firmware plan SHA-256 digest;
- exact firmware transaction ID;
- post-update verifier transaction ID, plan digest, installed version and verification state;
- the existing hashed machine identity;
- SHA-256 hashes of the before/after kernel boot IDs instead of persisting those raw boot IDs in the exported bundle;
- required-reboot observation, same-host, LVFS-source and no-virtualization-hint assessment results;
- explicit operator attestations for observed physical hardware, dedicated qualification hardware and reviewed recovery guidance.

The raw `/etc/machine-id` is never exported. The exported machine identity remains the SHA-256 value already used by the qualification journal.

## Integrity versus provenance

The payload is canonicalized by recursively sorting object keys and is sealed with SHA-256. The same finalized session therefore produces the same payload digest.

This digest is an **integrity/binding checksum, not a signature**. A self-contained JSON bundle cannot authenticate its own origin because an attacker who can rewrite the whole file could also recompute an unsigned digest. For that reason the verifier reports:

- `cryptographicOriginAuthentication: false`;
- `physicalityProvenByBundle: false`;
- `trustedComparisonRequiredForProvenance: true`.

For meaningful provenance, keep the expected qualification ID, device ID, target version, plan digest, transaction ID, machine hash and/or payload digest in a separately trusted record. `verifyPhysicalQualificationEvidenceBundle()` can require those expected bindings and fails closed on any mismatch, including a bundle whose internal digest has been recomputed after alteration.

A future signed attestation format may strengthen origin authentication, but this contract deliberately does not invent a signing key lifecycle or call an unsigned digest a signature.

## File safety

`writePhysicalQualificationEvidenceFile()`:

- requires an absolute output path;
- requires the immediate parent to be a real, non-symlink directory and rejects a symlinked parent path;
- uses exclusive creation and refuses to overwrite an existing evidence file;
- writes owner-only mode `0600`;
- caps the evidence file at 2 MiB.

`readPhysicalQualificationEvidenceFile()` opens with `O_NOFOLLOW` where available, requires an owner-only regular file within the same size cap, parses JSON and reruns the full structural/digest verifier.

## Operator CLI

`firmware-physical-qualification-evidence-cli.mjs` has two read/export operations:

```text
firmware-physical-qualification-evidence-cli.mjs export --session <qualification-id> --output <absolute-json-path>
firmware-physical-qualification-evidence-cli.mjs verify --file <absolute-json-path> [expected bindings]
```

`export` must run as root because the production qualification journal is private under `/var/lib/swir/qualification/firmware`. It reads an already-finalized session and does not invoke `fwupdmgr`, mutate firmware, reboot, enable remotes or accept a firmware file/URL.

`verify` can additionally require any of these separately trusted bindings:

- `--expect-qualification <id>`;
- `--expect-device <fwupd-device-id>`;
- `--expect-target <firmware-version>`;
- `--expect-plan-digest <sha256>`;
- `--expect-transaction <transaction-id>`;
- `--expect-machine-hash <sha256>`.

The verification output explicitly repeats that bundle integrity is not cryptographic origin authentication and cannot independently prove physical hardware.

## CI and roadmap accounting

`firmware-physical-qualification-evidence-selftest.mjs` uses fixtures only. It verifies deterministic bundling, expected-binding checks, rejection of incomplete/CI/virtualized sessions, detection of ordinary tampering, rejection of resealed device/target/plan/transaction/machine substitutions when trusted expectations are supplied, owner-only file permissions, overwrite refusal and symlink-parent refusal.

`.github/workflows/system-firmware-physical-qualification-evidence.yml` runs the evidence and existing qualification harness self-tests on the normal GitHub runner and Debian 13. It never calls qualification `apply` or `finalize`, and CI output never counts as real-hardware evidence.

Passing this gate must **not** change the canonical roadmap percentage. The `fwupd/LVFS firmware updates where supported` item remains open until an accepted supported-device session performs the reviewed real firmware path on dedicated physical hardware and satisfies the existing transaction, reboot/recovery, verification and operator-finalization gates.
