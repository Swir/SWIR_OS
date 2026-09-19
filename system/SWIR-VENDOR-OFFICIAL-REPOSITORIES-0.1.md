# SWIR Official Vendor Repository Policy 0.1

## Scope

This foundation introduces a fail-closed policy boundary for the System Edition roadmap item **allowlisted official vendor repositories for exceptional proprietary components**. It does not enable any vendor repository by default and it does not download drivers, signing keys or arbitrary binaries for installation.

`system/hardware/vendor-official-repository-service.mjs` consumes a root-owned policy file at `/etc/swir/hardware/vendor-repositories.json`. The checked-in `vendor-repositories.example.json` is deliberately empty and is documentation only; it is not project data and it does not authorize a vendor.

## Trust boundary

A production policy file must be a regular, non-symlink, root-owned file that is not writable by group or others and is at most 128 KiB. Every enabled entry must explicitly bind:

- source class `vendor-official-repository`;
- one or more exact PCI/USB vendor IDs;
- supported distribution IDs, versions and architectures;
- HTTPS repository base URL whose hostname is in the entry's exact official-host allowlist;
- APT suites/components and an explicit package allowlist;
- an existing signing keyring under `/usr/share/keyrings/` plus a pinned 40-hex signing-key fingerprint;
- `directBinaryDownloads=false`, `automaticEnable=false` and `arbitraryPackages=false`.

The policy rejects embedded credentials, query/fragment URLs, direct signing-key download URLs, wildcard package names, untrusted keyring paths and duplicate repository IDs.

## Driver Center boundary

Repository matching is read-only. A matching hardware vendor and platform produces a `swir.vendor-official-repository-review/0.1` candidate with `mutationAuthorized=false` and `automaticEnable=false`. The service intentionally does **not** edit APT source files, import keys, run package managers, fetch network content or install drivers.

Any future repository activation must reuse the existing journaled package/Driver Center broker, bind the reviewed repository/package set to the exact transaction digest, preserve distro signature verification, and require the normal privileged authorization path. There is no direct kernel-module mutation or random driver-download fallback.

## Pinned qualification evidence

`system/hardware/vendor-repository-trust-evidence.mjs` adds a separate **qualification-only** probe for a fixed, reviewed public repository profile. It is deliberately outside the mutation path and always reports `authorizesMutation=false` and `authorizesRepositoryEnablement=false`.

The first profile is `nvidia-debian13-amd64`, bound to:

- NVIDIA PCI vendor ID `10de`;
- Debian 13, `x86_64`;
- exact origin `https://developer.download.nvidia.com`;
- exact repository path `/compute/cuda/repos/debian13/x86_64/`;
- NVIDIA public key file `8793F200.pub`;
- pinned full primary fingerprint `02182E60104FCDC26EAE1B8597A5D4CB8793F200`;
- repository `InRelease` and `Packages.gz` metadata;
- package probes `cuda-keyring` and `nvidia-open`.

The live probe refuses redirects and arbitrary URLs, applies strict download/decompression size bounds, derives the full primary signing-key fingerprint with GnuPG, requires an exact match with the reviewed 40-hex NVIDIA fingerprint, validates the `InRelease` signature with `gpgv`, binds the signature's primary fingerprint to the fetched key, and confirms both reviewed package names are present in `Packages.gz`. It records SHA-256 digests for the fetched key, `InRelease` and compressed package index.

Signed repository metadata is also freshness-gated. `InRelease` must contain a parseable signed `Date`, must not be more than 24 hours in the future, and must be no older than 14 days when checked. If `Valid-Until` is present it must parse, be later than `Date`, and not be expired; the effective expiry is the earlier of `Valid-Until` and the 14-day local cap. If `Valid-Until` is absent, the 14-day cap from the signed `Date` is mandatory. Evidence records the signed date, optional upstream expiry, effective expiry, check time, age and remaining verified lifetime.

This evidence is **not an independent trust anchor** merely because the key and metadata originate from the same official host. The complete fingerprint is now pinned in the reviewed qualification profile, but repository enablement still requires a separately reviewed root-owned SWIR policy entry with the same full fingerprint and exact repository/package scope, followed by the journaled package/Driver Center broker path. The probe never writes `/etc/apt`, imports a system keyring, runs `apt`/`dpkg`, installs a package or claims physical-hardware support.

## Transaction binding

`system/hardware/vendor-repository-transaction-binding.mjs` closes the integrity gap between qualification evidence and the existing package/Driver Center transaction architecture without introducing a second privileged executor. It accepts only a trusted root-owned-policy review plus fresh qualification evidence and fails closed unless all of the following match exactly:

- repository ID, hardware vendor and Debian platform tuple;
- normalized HTTPS repository origin/path;
- the same pinned 40-hex primary signing-key fingerprint and `VALIDSIG` primary fingerprint;
- unexpired signed-metadata evidence with SHA-256 identities for the key, `InRelease` and `Packages.gz`;
- every requested package is simultaneously inside the root-owned policy allowlist and the qualified package evidence.

The binder emits `swir.vendor-repository-transaction-binding/0.1`, a read-only preview with a deterministic SHA-256 `bindingDigest`. That digest covers repository scope, platform/hardware identity, keyring path/fingerprint, fetched evidence digests, metadata validity window and the sorted requested package set. Changing any bound field therefore changes the digest.

For each requested package the binder emits a System package-provider manifest input for `swir.package.system`. The manifest preserves the underlying vendor source identity as `upstreamSourceClass=vendor-official-repository` while using the existing distribution package transaction route, and it carries the exact `vendorRepositoryBindingDigest`. This deliberately reuses the existing `swir.system-package-plan/0.1` → `swir.system-package-transaction/0.1` → Driver Center journal architecture rather than adding a package-manager shortcut.

The transaction binding itself **does not enable a repository and does not authorize a mutation**. It always reports `mutationAuthorized=false`, `repositoryEnablementAuthorized=false`, `requiresExplicitConfirmation=true`, `directAptMutationAllowed=false`, `directPkexecAllowed=false` and `repositoryActivationImplementedHere=false`. Repository activation still needs a separately implemented broker operation that is root-policy bound, journaled before mutation, authorized through the existing privilege boundary and recoverable after interruption.

The intended complete path is therefore:

`pinned qualification → root-owned policy review → deterministic trust/package binding → explicit user confirmation → existing journaled package/Driver Center broker → post-mutation verification/recovery`

No stage may convert qualification evidence into authorization by itself.

## Package journal integrity

The production distribution-provider path now preserves the vendor binding instead of dropping it while translating the binder manifest into `swir.system-package-plan/0.1`. A vendor-backed manifest is accepted only when it retains `upstreamSourceClass=vendor-official-repository`, an explicit repository ID and a lowercase 64-hex `vendorRepositoryBindingDigest`. Partial, malformed or foreign upstream binding metadata fails closed before a package plan is produced.

The resulting package plan retains both the upstream source class and exact binding digest inside the trust section. The existing `SystemPackageTransactionService` already hashes the complete plan before authorization, stores that plan plus its digest in the durable owner-only transaction journal before privileged mutation, and passes the same plan digest to the guarded executor. This means the reviewed vendor binding is now covered by the exact digest that authorizes and journals the package mutation route instead of existing only in pre-transaction metadata.

`system/hardware/vendor-repository-journal-binding.selftest.mjs` exercises the complete in-process path from `bindVendorRepositoryTransaction(...)` through `buildDistributionPackagePlan(...)` into a real `SystemPackageTransactionService` journal. It verifies that the binding digest survives into the committed journal, that authorization and executor handoff use the digest of the same complete plan, and that post-write tampering with `vendorRepositoryBindingDigest` is rejected by journal digest verification.

This closes the **binding-digest-to-package-journal integrity gap**. It still does not enable the vendor repository, write an APT source, import a system signing key or prove interruption/recovery for repository activation. Those remain separate release gates.

## Verification

`vendor-official-repository-service.selftest.mjs` exercises exact platform/vendor matching and fail-closed rejection of HTTP URLs, foreign hosts, direct downloads, automatic enablement, arbitrary package policy, key downloads, unsafe keyring paths, wildcard packages and duplicate IDs.

`vendor-repository-trust-evidence.selftest.mjs` verifies profile pinning, exact full-fingerprint matching, primary-vs-subkey fingerprint parsing, `VALIDSIG` binding, required package parsing, redirect rejection, key-fingerprint mismatch rejection and missing-package rejection without touching a real package manager. It also exercises missing/invalid/stale/future `Date`, invalid or expired `Valid-Until`, and the bounded freshness fallback used when upstream omits `Valid-Until`.

`vendor-repository-transaction-binding.selftest.mjs` verifies deterministic binding, digest changes when repository scope changes, package-provider manifest linkage, and fail-closed rejection of fingerprint, repository URL, platform, policy package, evidence package, expiry, preauthorization and signature-binding mismatches. It performs no privileged operation.

`vendor-repository-journal-binding.selftest.mjs` verifies the canonical vendor manifest → distribution provider plan → package transaction path and proves the exact binding digest is retained in the durable package journal and covered by the transaction plan digest. It also corrupts the stored binding digest after commit and requires journal verification to reject the modified record.

The dedicated GitHub Actions workflow additionally:

- creates a real root-owned policy fixture and proves writable/symlink policy files are rejected;
- runs syntax and unit/self-test gates for policy, evidence, transaction-binding, distribution-provider and journal-integrity layers;
- performs the pinned NVIDIA Debian 13 public-metadata qualification against the exact official origin;
- requires the exact reviewed 40-hex signing-key fingerprint and `InRelease` signature binding;
- requires fresh signed metadata under the 14-day maximum-age and 24-hour future-skew policy;
- verifies `cuda-keyring` and `nvidia-open` are present in the live package index;
- statically rejects package/source mutation shortcuts from qualification and binding layers.

A transient, stale or changed upstream repository fails this qualification gate closed and requires review; CI does not silently change hostnames, paths, packages, freshness limits or key identity.

## Roadmap accounting

This is meaningful implementation and transaction-integrity progress but does **not** complete the roadmap checkbox by itself. The exact vendor binding digest now reaches and is integrity-protected by the existing package mutation journal, satisfying that sub-gate. The item remains open until a real exceptional proprietary component is represented by reviewed root-owned project policy with the complete signing-key fingerprint, repository activation is implemented through the existing privileged/journaled broker, and disposable-VM activation/interruption/recovery behavior is verified without bypassing distribution trust or safety gates.
