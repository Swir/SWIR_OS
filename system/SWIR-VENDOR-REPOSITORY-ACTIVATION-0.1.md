# SWIR Vendor Repository Activation Transaction 0.1

## Scope

This package advances the System Edition roadmap item **allowlisted official vendor repositories for exceptional proprietary components** from qualification/binding-only work to a guarded Driver Center activation/deactivation/recovery lifecycle. The roadmap item remains open until the disposable-VM gate is green on the final exact head and the reviewed vendor policy/key trust material is staged through the final System image path.

The transaction consumes only a previously verified `swir.vendor-repository-transaction-binding/0.1`. It never accepts an arbitrary repository URL, arbitrary signing key, raw shell command or package name from the activation caller.

## Maintained reviewed policy

`system/hardware/vendor-repositories.debian13.json` is the maintained project policy for the first exceptional proprietary source. It allowlists the NVIDIA Debian 13 x86_64 repository at `developer.download.nvidia.com`, binds PCI vendor `10de`, uses the full fingerprint `02182E60104FCDC26EAE1B8597A5D4CB8793F200`, keeps `automaticEnable=false`, forbids direct binary downloads and limits package scope.

The policy parser now supports the vendor's flat APT suite `./` without accepting parent traversal, empty path segments, absolute paths, duplicate suites or control/newline injection. The Driver Center NVIDIA catalog entry uses the same repository ID, so stale policy/catalog aliases cannot silently match.

## Activation plan

`buildVendorRepositoryActivationPlan(...)` derives a deterministic, non-executable preview from the verified binding. The plan binds:

- exact repository ID and `bindingDigest`;
- exact `/etc/apt/sources.list.d/swir-vendor-<id>.sources` target;
- SHA-256 of the generated deb822 source document;
- exact root-owned keyring path and full 40-hex signing-key fingerprint;
- evidence expiry and normalized Debian architecture;
- the fixed targeted metadata refresh argv for that single source file.

The generated deb822 source always uses HTTPS from the prior binding, `Signed-By`, `Trusted: no`, `Enabled: yes` and the reviewed suites/components. `x86_64` is mapped to APT `amd64` and `aarch64` to `arm64`.

## Driver Center integration

`vendor-repository-driver-center-integration.mjs` accepts one exact `review-package` Driver Center operation and requires exactly one fresh transaction binding matching the operation's verified vendor source, repository ID and package scope. It produces a read-only review that retains the activation digest and cannot authorize mutation by itself.

`DriverCenterVendorRepositoryCoordinator` delegates activation and interrupted-source recovery to the existing journaled activation service. It also supports explicit deactivation, but only after the privilege broker authorizes the exact committed transaction and only while the active source still has the committed digest. A source changed outside the transaction is refused rather than overwritten.

Package installation remains a separate transaction. Driver Center does not gain a direct APT or direct `pkexec` path and automatic repository enablement remains disabled.

## Privilege and confirmation boundary

The transaction service requires the existing privilege broker interface before mutation and requires the user-visible `activationDigest` to be confirmed exactly. Production execution additionally requires effective UID 0; the service does not call `sudo`, `pkexec`, a shell, `curl` or `wget` itself.

The only external command accepted by the executor is the exact argv equivalent of:

`apt-get -o Dir::Etc::sourcelist=<exact generated .sources path> -o Dir::Etc::sourceparts=- -o APT::Get::List-Cleanup=0 update`

This refreshes metadata for the newly staged source only. It does not install a package.

## Signing-key verification

Before writing the APT source, `GpgVendorKeyringVerifier` requires the reviewed keyring to remain a bounded regular non-symlink file under `/usr/share/keyrings/`, not writable by group/others, root-owned in production, and resolving to the exact reviewed path. It uses fixed `/usr/bin/gpg --show-keys --with-colons --fingerprint` argv with `shell=false` and requires the reviewed full fingerprint to be present.

The activation transaction itself does not download or import a key. The disposable VM qualification lane independently fetches only the pinned profile URL, verifies byte digest and the full fingerprint against signed qualification evidence, and installs that keyring only inside the disposable test image. A production System-image key provisioning path is still required before the roadmap checkbox can close.

## Journal, deactivation and recovery

The owner-only journal is written **before** the APT source mutation and records the complete plan plus its deterministic digest and the previous source state. Source writes are temporary-file + fsync + atomic rename, with symlink and path-escape refusal.

A synchronous metadata-refresh failure restores the exact previous source state. If rollback itself is interrupted or ambiguous, the journal enters `failed-needs-recovery`; `inspectRecovery()` exposes that state without mutating anything. `recoverSource(...)` requires the same activation digest plus a new privilege-broker authorization and refuses to overwrite a source that diverged from both the transaction-staged and pre-transaction digests.

Explicit Driver Center deactivation also requires a new broker authorization and verifies the committed source digest before restoring the exact pre-activation state. Recovery/deactivation only restore the APT source file; they do not claim to undo package installations, firmware updates or unrelated APT metadata.

## Verification

The unit/policy lanes verify deterministic binding, strict deb822 tokens, exact confirmation, broker boundaries, atomic source activation, explicit deactivation, synchronous rollback, interrupted recovery, stale-evidence refusal and no direct package-install/shell shortcuts.

`system/e2e/vendor-repository-activation-vm-e2e.sh` plus its guest script provide a separate disposable Debian 13 VM gate. The gate is designed to:

- load the maintained root-owned vendor policy;
- collect fresh signed NVIDIA InRelease/Packages evidence using the pinned full fingerprint;
- build the real Driver Center vendor source from the catalog and binding;
- activate the exact reviewed source and run real targeted `apt-get update`;
- verify `nvidia-open` is visible through that source without installing it;
- explicitly deactivate and verify the source is restored/removed;
- fault-inject an interrupted rollback, observe durable `failed-needs-recovery`, then perform operator-authorized source recovery;
- emit evidence that explicitly states VM-only scope and does not claim physical hardware, Live USB or package installation.

The VM lane uses a controlled root authorization harness to exercise transaction semantics. It does not claim production desktop authentication integration by itself.

## Roadmap accounting

This work is a substantial implementation of the vendor-repository roadmap item, but the checkbox remains open until all of the following are true on the same verified revision:

1. the disposable-VM E2E is green with signed metadata/package visibility plus interruption/recovery evidence;
2. the maintained reviewed policy and trusted key provisioning are staged through the final System image path without automatic enablement;
3. final exact-head CI and roadmap read-back are green.

No progress percentage changes until that complete gate is satisfied.
