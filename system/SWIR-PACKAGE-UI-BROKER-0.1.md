# SWIR Package UI Broker 0.1

Status: **native UI mutation wiring + System-image runtime staging implemented; booted mutation E2E pending**

This component closes the security gap between the native Software/Update Center surfaces and the existing privileged package transaction stack without allowing GTK applications to invoke APT, `pkexec`, `sudo`, or a root helper directly.

## Security flow

```text
native SWIR Software / Update UI
        |
        | preview(package, operation)
        v
/run/swir/package-transaction.sock
        |
        +--> fixed System Edition provider manifest
        +--> DistributionPackageProvider
        +--> AptDependencyResolver
        +--> exact SHA-256 package plan digest
        |
        v
read-only preview returned to user
        |
        | explicit confirmation of that exact digest
        v
/run/swir/peer-authorization.sock
        |
        +--> kernel SO_PEERCRED
        +--> active local graphical systemd-logind session
        +--> Polkit exact action/package/operation/plan digest
        v
short-lived one-time HMAC authorization envelope
        |
        | commit(package, operation, envelope)
        v
package transaction broker recomputes the plan
        |
        +--> peer grant must match recomputed digest
        +--> repository trust / native signature probe
        +--> pre-mutation package snapshot
        +--> durable journal before mutation
        +--> guarded package-manager argv
        +--> post-mutation health verification
        v
committed transaction or fail-closed recovery state
```

## Confused-deputy protections

The package broker accepts only `preview` and `commit` requests, only the package operations `install`, `update`, and `remove`, and only package names matching the distribution-package allowlist syntax. Unknown request fields are rejected. In particular the client cannot supply a Unix UID, PID, GID, session, repository URL, executable, command vector, journal location, or authorization subject.

A commit must carry the short-lived envelope produced by the peer-authorization broker. The package transaction service recomputes the dependency-resolved plan before mutation. The peer grant verifier binds authorization to that newly computed plan digest, exact package identity and exact operation. If package metadata or dependency resolution changes after the preview, the old grant does not match and the transaction fails closed rather than silently applying a different plan.

## Native clients and explicit confirmation

`system/apps/package_transaction_client.py` is deliberately unprivileged. It performs JSON-line IPC only and contains no subprocess invocation or direct APT/dpkg/`pkexec` mutation path.

`system/apps/package_mutation_flow.py` adds the application-layer confirmation contract used by both GTK package surfaces. A preview becomes an immutable mutation intent. The UI must confirm the exact preview digest before authorization is requested, and each confirmed digest is single-use inside the client flow. The intent is consumed before requesting Polkit so a double-click, re-entrant callback, failed authorization, or repeated UI callback cannot replay the same confirmation. A retry requires a fresh preview.

The native flow is:

1. request a dependency-aware package preview;
2. display package, manager, command preview and the exact SHA-256 plan digest;
3. require a separate explicit user confirmation;
4. request interactive Polkit authorization from the peer broker;
5. submit the one-time peer-bound envelope to the privileged package broker;
6. require the committed transaction digest to match the confirmed preview.

The Software Center exposes brokered **Install** only for search results while both broker sockets are available. The Update Center exposes brokered per-package **Update** for the locally simulated update list. Bulk upgrade and package removal UI remain deliberately unavailable until their user experience and recovery semantics have separate verification. If the broker is unavailable, the controls are disabled rather than falling back to direct package-manager execution.

## Privileged service

`system/ipc/swir-package-transaction-broker.mjs` composes the existing SWIR components rather than implementing a second mutation engine:

- `DistributionPackageProvider`;
- `AptDependencyResolver`;
- `createPeerAuthorizedSystemPackageSecurityBoundary`;
- `SystemPackageTransactionService`;
- `DistributionPackageSnapshotProvider`;
- `GuardedPkexecPackageExecutor`;
- `NativePackageHealthVerifier`.

The production composition is fixed to the selected Debian System Edition foundation and the root-owned `/etc/swir/repository-trust-policy.json`. Arbitrary repository input is not accepted over IPC.

`system/ipc/swir-package-transaction.service` defines the root service boundary. It deliberately does **not** use a filesystem sandbox that would prevent the already-authorized package manager from changing the operating system. Instead the service narrows IPC request shape and network/address families while leaving package mutation constrained by the existing trust, Polkit, journal and executor layers.

## System-image runtime staging

`system/image/system-package-ui-runtime-provisioning.mjs` stages and verifies the broker's exact runtime closure into a disposable System Edition rootfs. It installs only repository-owned broker/package/security modules, the pinned Debian repository trust policy and systemd service. It composes the existing peer-authorization image provisioning rather than creating a second authorization implementation.

The provisioning contract rejects `/` as a target, symlink traversal, unexpected destination types and source files that escape the repository. In production the rootfs and runtime artifacts must be root-owned and non-writable by group/world. `/usr/bin/node` must already be the trusted Debian runtime. The runtime HMAC authorization key is **not** baked into the image; it remains a boot-time `/run/swir` secret owned by the peer-authorization service.

`system/session/provision-graphical-session.sh` installs Debian `nodejs` only through the already-configured signed Debian repositories when required, stages the broker + peer authorization runtime, installs the unprivileged Python client/confirmation helper, compiles the Python sources and verifies the service/runtime files before the graphical image is accepted. The package transaction service is enabled for `multi-user.target`.

## Verification

`.github/workflows/system-package-ui-broker-contract.yml` verifies the privileged broker/client boundary and existing security stack.

`.github/workflows/system-package-ui-mutation-contract.yml` additionally verifies:

- Python/Node/shell syntax;
- client and single-use confirmation self-tests;
- package UI runtime image provisioning, integrity and tamper detection;
- absence of direct subprocess/privileged-package execution in the GTK mutation surfaces;
- presence of explicit confirmation wiring;
- image integration of the client, helper, Debian Node runtime and package broker service.

Existing graphical/Live USB/installer workflows are also expected to rebuild the System Edition image because the graphical provisioning path changed.

## Remaining production gates

This milestone does **not** yet claim a fully verified package mutation experience on a booted final image. The remaining high-value gates are:

1. boot a disposable System Edition VM with real `systemd-logind`, `polkitd`, peer authorization socket and package transaction service active;
2. perform a harmless package install/update transaction against a disposable VM disk and verify durable journal + post-mutation health state;
3. prove cancellation before authorization makes no package change;
4. prove denial, expired grant, replay and changed-plan rejection in the booted service path;
5. prove broker/service restart and interrupted mutation recovery behavior against a disposable image;
6. add progress/recovery presentation in the native UI without bypassing the transaction service;
7. qualify physical hardware separately from VM evidence.

The authoritative roadmap does not advance merely because the UI and image-runtime wiring exists. Completion still requires the relevant roadmap deliverable itself to be fully implemented and verified.
