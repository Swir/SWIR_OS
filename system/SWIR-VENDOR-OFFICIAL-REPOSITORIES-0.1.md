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
- repository `InRelease` and `Packages.gz` metadata;
- package probes `cuda-keyring` and `nvidia-open`.

The live probe refuses redirects and arbitrary URLs, applies strict download/decompression size bounds, derives the full primary signing-key fingerprint with GnuPG, requires that fingerprint to end in the reviewed NVIDIA key ID `8793F200`, validates the `InRelease` signature with `gpgv`, binds the signature's primary fingerprint to the fetched key, and confirms both reviewed package names are present in `Packages.gz`. It records SHA-256 digests for the fetched key, `InRelease` and compressed package index.

This evidence is **not an independent trust anchor**: the public key and signed metadata are fetched from the same pinned official origin. Before any repository can become enabled project data, an operator still has to review and pin the complete 40-hex fingerprint in the root-owned SWIR policy, review the exact repository/package scope, and route all mutation through the journaled package/Driver Center broker. The probe never writes `/etc/apt`, imports a system keyring, runs `apt`/`dpkg`, installs a package or claims physical-hardware support.

## Verification

`vendor-official-repository-service.selftest.mjs` exercises exact platform/vendor matching and fail-closed rejection of HTTP URLs, foreign hosts, direct downloads, automatic enablement, arbitrary package policy, key downloads, unsafe keyring paths, wildcard packages and duplicate IDs.

`vendor-repository-trust-evidence.selftest.mjs` verifies profile pinning, primary-vs-subkey fingerprint parsing, `VALIDSIG` binding, required package parsing, redirect rejection, key-ID mismatch rejection and missing-package rejection without touching a real package manager.

The dedicated GitHub Actions workflow additionally:

- creates a real root-owned policy fixture and proves writable/symlink policy files are rejected;
- runs syntax and unit/self-test gates for both policy and evidence layers;
- performs the pinned NVIDIA Debian 13 public-metadata qualification against the exact official origin;
- validates the resulting full signing-key fingerprint and `InRelease` signature binding;
- verifies `cuda-keyring` and `nvidia-open` are present in the live package index;
- statically rejects package/source mutation shortcuts from the qualification probe.

A transient or changed upstream repository fails this qualification gate closed and requires review; CI does not silently change hostnames, paths, packages or key identity.

## Roadmap accounting

This is meaningful implementation and trust-qualification progress but does **not** complete the roadmap checkbox by itself. The item remains open until a real exceptional proprietary component is represented by reviewed root-owned project policy with the complete signing-key fingerprint, the repository activation and package scope are bound to the journaled package/Driver Center mutation path, and the resulting transaction/recovery behavior is verified without bypassing distribution trust or safety gates.
