# SWIR Package UI Broker 0.1

Status: **implemented source foundation / System-image provisioning and native-UI mutation wiring pending**

This component closes the security gap between the native Software/Update Center surfaces and the existing privileged package transaction stack without allowing GTK applications to invoke APT, `pkexec`, or a root helper directly.

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
        | explicit second confirmation
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

A commit must carry the short-lived envelope produced by the existing peer-authorization broker. The package transaction service recomputes the dependency-resolved plan before mutation. The peer grant verifier then binds authorization to that newly computed plan digest, exact package identity and exact operation. If package metadata or dependency resolution changes after the preview, the old grant does not match and the transaction fails closed rather than silently applying a different plan.

## Native client

`system/apps/package_transaction_client.py` is deliberately unprivileged. It performs JSON-line IPC only. It contains no subprocess invocation and no direct APT/dpkg/`pkexec` mutation path. Its intended UI flow is:

1. request a package preview;
2. show the exact operation to the user;
3. require an explicit confirmation;
4. request interactive Polkit authorization from the peer broker;
5. submit the one-time envelope to the privileged package broker;
6. verify that the committed transaction digest matches the preview digest.

The client reports broker unavailability instead of falling back to direct package-manager execution.

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

## Verification in this milestone

`.github/workflows/system-package-ui-broker-contract.yml` checks Node/Python syntax, broker/client self-tests, a real temporary AF_UNIX preview request, direct-tool bans in the Python client, rejection of caller identity fields and the systemd unit contract. The self-tests do not mutate the CI host package database.

## Remaining production gates

This milestone intentionally does **not** claim that package mutation is available in a booted SWIR image yet. Before that claim, the following remain required:

1. stage the broker, its Node module dependency closure, the client and service unit into the System Edition image from trusted repository sources;
2. install the required Debian `nodejs` runtime from the signed distribution repositories or replace the service with an equivalently verified packaged runtime;
3. enable/start the service in the image and verify root ownership/modes of all runtime files;
4. wire Software Center and Update Center to the client with preview followed by a distinct explicit confirmation step;
5. boot a disposable System Edition VM with real `systemd-logind`, `polkitd` and both SWIR sockets;
6. perform a harmless package transaction against a disposable test disk/image, validate the durable journal and ensure a changed plan invalidates an old grant;
7. exercise denial, cancellation, expired grant, replay, broker restart and unavailable-service behavior.

Until those gates pass, the current native Software and Update Centers remain read-only package surfaces. The authoritative roadmap therefore does not advance for this source foundation alone.
