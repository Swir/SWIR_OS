# SWIR Vendor Repository Activation Transaction 0.1

## Scope

This package advances the System Edition roadmap item **allowlisted official vendor repositories for exceptional proprietary components** from qualification/binding-only work toward a real recoverable activation transaction. It still does **not** complete the roadmap item: Driver Center integration and disposable-VM activation/interruption/recovery evidence remain required before the checkbox can close.

The transaction consumes only a previously verified `swir.vendor-repository-transaction-binding/0.1`. It never accepts an arbitrary repository URL, arbitrary signing key, raw shell command or package name from the activation caller.

## Activation plan

`buildVendorRepositoryActivationPlan(...)` derives a deterministic, non-executable preview from the verified binding. The plan binds:

- exact repository ID and `bindingDigest`;
- exact `/etc/apt/sources.list.d/swir-vendor-<id>.sources` target;
- SHA-256 of the generated deb822 source document;
- exact root-owned keyring path and full 40-hex signing-key fingerprint;
- evidence expiry and normalized Debian architecture;
- the fixed targeted metadata refresh argv for that single source file.

The generated deb822 source always uses HTTPS from the prior binding, `Signed-By`, `Trusted: no`, `Enabled: yes` and the reviewed suites/components. `x86_64` is mapped to APT `amd64` and `aarch64` to `arm64`.

## Privilege and confirmation boundary

The transaction service requires the existing privilege broker interface before mutation and requires the user-visible `activationDigest` to be confirmed exactly. Production execution additionally requires effective UID 0; the service does not call `sudo`, `pkexec`, a shell, `curl` or `wget` itself.

The only external command accepted by the executor is the exact argv equivalent of:

`apt-get -o Dir::Etc::sourcelist=<exact generated .sources path> -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 update`

This refreshes metadata for the newly staged source only. It does not install a package. Package installation remains a separate existing journaled System package transaction.

## Signing-key verification

Before writing the APT source, `GpgVendorKeyringVerifier` requires the reviewed keyring to remain a bounded regular non-symlink file under `/usr/share/keyrings/`, not writable by group/others, root-owned in production, and resolving to the exact reviewed path. It uses fixed `/usr/bin/gpg --show-keys --with-colons --fingerprint` argv with `shell=false` and requires the reviewed full fingerprint to be present.

No key is downloaded or imported by this transaction.

## Journal and recovery

The owner-only journal is written **before** the APT source mutation and records the complete plan plus its deterministic digest and the previous source state. Source writes are temporary-file + fsync + atomic rename, with symlink and path-escape refusal.

A synchronous metadata-refresh failure restores the exact previous source state. If rollback itself is interrupted or ambiguous, the journal enters `failed-needs-recovery`; `inspectRecovery()` exposes that state without mutating anything. `recoverSource(...)` requires the same activation digest plus a new privilege-broker authorization and refuses to overwrite a source that diverged from both the transaction-staged and pre-transaction digests.

Recovery only restores the APT source file. It does not claim to roll back package installations, firmware updates or unrelated APT metadata.

## Verification

`vendor-repository-activation-transaction.selftest.mjs` verifies:

- deterministic activation planning from a real vendor binding fixture;
- deb822 `Signed-By`, `Trusted: no`, architecture mapping and exact targeted `apt-get update` argv;
- exact activation-digest confirmation and privilege-broker authorization;
- successful atomic source activation;
- synchronous metadata-refresh failure restoring the prior source;
- symlink-target refusal without changing the symlink target;
- interrupted rollback surfacing an explicit recovery record and authorized operator recovery;
- stale evidence refusal at mutation time;
- no direct package install, arbitrary repository/key path or shell execution policy.

The dedicated workflow syntax-checks the implementation and runs the self-test on Node.js 22.

## Roadmap accounting

This is a substantial prerequisite for the vendor-repository roadmap item, but the item remains open. Before completion is claimed, SWIR OS still needs:

1. Driver Center/broker integration that invokes this transaction for a matching verified vendor binding;
2. a disposable-VM E2E that activates the reviewed source, verifies signed metadata/package visibility, exercises interruption/recovery and then removes/restores the source safely;
3. final exact-head CI and roadmap read-back.

No progress percentage changes in this package by itself.
