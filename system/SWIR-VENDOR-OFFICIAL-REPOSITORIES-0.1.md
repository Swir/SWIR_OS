# SWIR Official Vendor Repository Policy 0.1

## Scope

This foundation introduces a fail-closed policy boundary for the System Edition roadmap item **allowlisted official vendor repositories for exceptional proprietary components**. It does not enable any vendor repository by default and it does not download drivers, signing keys or arbitrary binaries.

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

## Verification

`vendor-official-repository-service.selftest.mjs` exercises exact platform/vendor matching and fail-closed rejection of HTTP URLs, foreign hosts, direct downloads, automatic enablement, arbitrary package policy, key downloads, unsafe keyring paths, wildcard packages and duplicate IDs.

The dedicated GitHub Actions workflow additionally creates a real root-owned policy fixture, verifies that the production loader accepts it, then proves that a group/world-writable policy and a symlink policy are rejected.

## Roadmap accounting

This is meaningful implementation progress but does **not** complete the roadmap checkbox by itself. The item remains open until a real exceptional proprietary component is integrated through a reviewed official vendor repository, the exact repository/key/package policy is documented, and the journaled package/Driver Center mutation path is verified without bypassing distribution trust or safety gates.
