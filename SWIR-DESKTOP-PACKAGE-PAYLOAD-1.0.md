# SWIR Desktop Package Payload 1.0

`swir.desktop-package-payload/1.0` defines the native Desktop Edition payload deployment core for `.swirapp` bundles.

## Security boundary

The payload installer is not a trust authority. A caller must supply the SHA-256 value obtained from already trusted package metadata. The installer fails closed when the archive hash differs. Package signature/catalog trust remains a separate Package Core responsibility.

The installer never executes payload code while inspecting or deploying a package.

## Bundle requirements

A `.swirapp` is a ZIP-compatible archive containing `swir-package.json` at its root. The manifest must use `swir.app/1.0` and provide the required Package 1.0 identity/runtime fields used by Desktop deployment: package identity, version, name, author, type and entry.

Native extraction rejects absolute/rooted paths, `..` traversal, duplicate case-insensitive paths, symbolic links, oversized entries and archives whose expanded size exceeds the configured ceiling.

Before promotion to `Current`, the staged package is health-checked without executing application code. The declared entry must be a safe relative path, must remain inside the staging root, must exist as a regular file and must not be a reparse point. Invalid or incomplete manifests and missing/unsafe entries fail before any installed slot is replaced.

## Deployment slots

Per package, Desktop Edition maintains:

```text
Packages/Installed/<packageId>/
  Current/
  Previous/
```

A new payload is fully extracted and validated in a managed staging directory before it can affect `Current`. Updates rotate the old `Current` into `Previous`; if promotion of the incoming payload fails, the previous slot is restored. Successful deployments persist `.swir-deployment.json` containing the installed version, verified bundle SHA-256, package type and verified entry path.

Rollback swaps `Current` and `Previous`, allowing the last known payload to be restored without downloading it again.

### Startup recovery

The installer performs bounded recovery whenever the Desktop package service is created. It removes orphaned staging and `.incoming-*` directories left by an interrupted deployment. If a crash happened after `Current` was moved aside but before a replacement reached `Current`, an existing `Previous` slot is promoted back to `Current`. Interrupted `.rollback-*` swaps are also reconciled conservatively so a known package slot is not silently discarded.

Recovery never downloads replacement files and never invents package metadata; it only reconciles already-local managed slots.

## Capability-bound Package bridge

`DesktopPackageBridge` places the installer behind an owner-bound file capability instead of accepting an arbitrary filesystem path from web content. Package mutation is restricted to the trusted `swir.system.shell` owner, and the file capability is consumed after an install attempt, including integrity failures.

This creates the intended native boundary:

```text
trusted shell / Store
       |
       v
owner-bound file capability
       |
       v
DesktopPackageBridge
       |
       +--> expected trusted SHA-256
       +--> capability ownership check
       v
DesktopAppPackageInstaller
       |
       +--> archive hardening
       +--> manifest validation
       +--> staged entry health verification
       +--> Current / Previous promotion
       +--> startup crash recovery
       v
verified desktop payload
```

## Current integration state

`DesktopAppPackageInstaller` and `DesktopPackageBridge` are compiled into the shipping Windows Desktop Host and exposed to the trusted shell through the native `SwirRuntime.packages` surface. The bridge accepts structured signed-catalog authorization, binds catalog package identity/version to the bundle manifest, independently verifies the embedded package signature, and only then enters the payload installer. The installer still verifies the exact catalog-authorized SHA-256 before any slot mutation.

The Desktop release workflow builds reviewed `.swirapp` artifacts, signs them with a distinct Ed25519 package-signing key, independently verifies each signature, computes catalog hashes from the final signed bytes, stages a generated `package-trust-roots.json` with `requireSignedPackages: true`, and verifies the packaged artifacts again in the final release bundle. Signed-catalog and package lifecycle self-tests cover install, update, Host reconstruction, rollback, unsigned-package rejection, payload tamper rejection and catalog anti-rollback behavior.

The checked-in `desktop/windows/package-trust-roots.json` remains an intentionally permissive development placeholder; it is not acceptable as production release trust. A production release replaces it with generated fail-closed trust material next to the Desktop Host. Protected production evidence is intentionally tracked separately from contract evidence: the package-signing evidence workflow has a `desktop-production-signing` environment and protected-key path, but no `workflow_dispatch` production run has yet been recorded. Therefore the roadmap item for production package signatures and integrity verification remains open until protected production evidence is actually produced and independently validated.
