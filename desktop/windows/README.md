# SWIR OS Desktop Host — Windows Preview 0.5.7

This is the native-host line for SWIR OS Desktop Edition.

## Current state

Preview 0.5.7 keeps the `swir.runtime/1.0` boundary, capability broker, Desktop package policy registry and package execution-context broker while moving the Windows distribution toward a **single-download, self-contained Desktop release**. Release packaging now publishes a self-contained .NET 8 host, a repository-pinned Microsoft WebView2 Fixed Version Runtime, signed Store/catalog metadata, the updater worker and a one-file SWIR Desktop Setup executable. End users are not expected to install .NET or WebView2 separately.

The host now:

- hosts the SWIR shell at `https://swir.local/index.html`;
- maps every trusted installable package to a deterministic dedicated origin;
- enables package isolation routing only for package entries validated by the trusted policy registry;
- loads `app-policy.json` fail-closed and validates it against the official package catalog in CI;
- keeps shell and package execution tokens host-side;
- accepts native shell calls only from the exact shell document;
- resolves package native identity only from exact trusted package origin + exact entry path;
- rejects non-default ports and user-info on trusted shell/package source checks;
- creates package execution contexts from installed permission grants and validates them against `app-policy.json`;
- revokes package capability tokens when package contexts disappear or grants change;
- stores native application data below `%LOCALAPPDATA%\SWIR\Apps\<packageId>\Data` with per-package isolation and quotas;
- verifies signed update envelopes using RSA-PSS/SHA-256 and strict HTTPS/host/version/package metadata policy;
- downloads only a previously verified update target with redirects, cookies and ambient credentials disabled;
- stages verified update streams below `%LOCALAPPDATA%\SWIR\Updates\Staging` using streaming SHA-256, signed-size enforcement, temporary files and atomic promotion;
- prepares a non-executing handoff plan and re-verifies the staged package before an apply transaction can begin;
- journals update transactions through prepared/applying/awaiting-health-check/commit or rollback states with stale-state protection and recovery discovery;
- prepares verified candidate payloads from the Desktop package manifest with traversal, symlink, duplicate-name, file-count, expanded-size and per-file SHA-256 enforcement;
- maintains rollback-safe `Current`, `Previous` and transaction-scoped `Candidate` deployment slots with conservative crash recovery;
- issues a short-lived 256-bit health challenge after activation, stores only its SHA-256 digest, requires the exact target version for commit, and moves expired health checks to `rollback-pending`;
- immediately restores `Previous` if activation succeeds but the health challenge cannot be created;
- launches an activated candidate only through the standalone updater worker after a one-shot old-host shutdown handoff and PID-exit verification;
- passes update health/shutdown secrets only through process environment and scrubs/captures them instead of persisting them in clear text;
- confirms candidate health only after WebView2 successfully loads the trusted SWIR shell;
- runs `DesktopStartupRecovery` before creating WebView2, rolling back interrupted/expired active transactions and failing closed when an active transaction has lost its canonical worker plan;
- centralizes canonical Desktop transaction/deployment locations in `DesktopUpdatePaths` so startup recovery does not trust mutable metadata for its root boundary;
- keeps process spawn/kill and unrestricted native network control denied to WebView applications;
- keeps external filesystem access behind expiring owner-bound capability tokens;
- publishes the Desktop Host as self-contained .NET 8 for `win-x64`;
- obtains only the repository-pinned official Microsoft WebView2 Fixed Version Runtime during controlled packaging, verifies its SHA-256/version/Microsoft Authenticode identity and stores acquisition provenance;
- verifies the bundled Host/WebView2/provenance integrity contract before normal bundled-release startup;
- can package the already-verified release ZIP into one self-contained `SWIR-Desktop-Setup-<version>-<channel>.exe`;
- makes Setup verify the embedded package SHA-256, safely extract it, verify bundled runtime integrity, install transactionally into a versioned directory and write a final-path install receipt/current pointer;
- refuses to silently reuse an existing installation when its receipt or bundled runtime bytes no longer match the verified package.

## App isolation routing

The five official installable applications communicate with the shell through `swir-app-bridge.js` + `swir-app-bridge-host.js` rather than direct `parent.SwirPlatform` / `parent.SwirAppSDK` access.

Preview 0.5.7 advertises:

```text
features.packageContextBroker = true
features.appIsolationRouting = true
features.appIsolationState = APP_BRIDGE_VERIFIED
features.nativeAppData = true
```

`swir-apps.js` routes installed iframe packages to origins such as:

```text
https://app-swir-code.swir.local/swir-code.html
https://app-swir-chat.swir.local/swir-chat.html
```

Web Edition remains on same-origin relative application URLs.

## Trust boundary

Isolation depends on multiple checks rather than hostname alone:

```text
trusted package catalog
  -> app-policy.json
  -> deterministic isolated origin
  -> exact package entry path
  -> managed iframe source
  -> App Bridge packageId check
  -> granted package permission
  -> host-owned execution context
```

The package-side App Bridge never receives native execution tokens. Package-native messages are attributed by the host from their exact source origin and entry path, and the corresponding execution token is resolved internally.

## Native App Data

`SwirRuntime.appData` is the portable application-storage contract. Web Edition keeps a namespaced browser fallback, while Desktop Edition routes storage through the native host.

Desktop storage uses:

```text
%LOCALAPPDATA%\SWIR\Apps\<packageId>\Data\
```

The broker enforces package identity, storage permissions, a 1 MiB maximum value, a 16 MiB package quota and a 512-item limit. Writes use temporary files and atomic replacement. Corrupt JSON and I/O failures are surfaced as controlled errors.

CI includes native App Data isolation tests and Permission Broker tests covering cross-package denial, permission downgrade, capability invalidation and package-context removal.

## Signed update pipeline

`UpdateBroker` accepts only signed `swir.update-envelope/0.1` envelopes carrying `swir.desktop-update/0.1` payloads. Current signature algorithm is `RSA-PSS-SHA256`.

Before an update can be considered verified, the broker checks signature/key material, release channel, monotonic version upgrade, publication timestamp, canonical HTTPS package URL with explicit host allowlist, signed package size capped at 512 MiB and SHA-256 package digest.

The current pipeline is deliberately split into narrow trust boundaries:

```text
signed manifest
  -> UpdateBroker verification
  -> restricted UpdateDownloadClient
  -> UpdateStagingBroker streaming verification
  -> UpdateHandoffBroker re-verification + prepared handoff
  -> UpdateTransactionJournal crash-safe state machine
  -> UpdaterWorkerProtocol planning
  -> CandidatePackagePreparer verified extraction
  -> HostShutdownHandoff old-host exit proof
  -> DeploymentSlotActivator Current/Previous swap
  -> UpdateActivationCoordinator guarded health issuance
  -> ControlledCandidateLauncher
  -> StartupHealthHandshake after trusted shell readiness
  -> UpdateRecoveryCoordinator + DesktopStartupRecovery
  -> commit or rollback
```

`UpdateDownloadClient` refuses redirects and ambient HTTP credentials. `UpdateStagingBroker` never promotes a partial package. `UpdateHandoffBroker` hashes the package again before creating a prepared handoff. `UpdateTransactionJournal` records recoverable state transitions atomically and rejects stale writers.

`CandidatePackagePreparer` extracts only manifested content into a transaction-specific candidate sandbox and re-verifies the payload before activation. `DeploymentSlotActivator` preserves the known-good deployment in `Previous`, promotes the candidate into `Current`, quarantines ambiguous/failed promoted content and prefers rollback over forward recovery after an interrupted swap.

`UpdateActivationCoordinator` couples successful slot activation with health challenge creation. A raw 256-bit token exists only in memory; persistent `health.json` stores its SHA-256 digest. If challenge issuance fails after the candidate has already been promoted, the coordinator immediately transitions to rollback and restores `Previous` rather than leaving an unconfirmable `Current` active.

`ControlledCandidateLauncher` launches only the manifest-bound executable from `Current`, injects the one-shot health token into the child environment, and rolls back on process-start failure or very early exit. `StartupHealthHandshake` captures and removes update secrets from the environment, validates transaction/version/journal binding, and commits only after the trusted shell completes navigation.

`DesktopStartupRecovery` now runs before normal shell startup. Prepared transactions remain pending because they have not touched `Current`; interrupted `applying`, missing/expired health metadata and persisted rollback states are reconciled before WebView2 starts. An active transaction without its canonical `worker-plan.json` blocks shell startup rather than silently continuing in an ambiguous deployment state.

The update subsystem deliberately does **not** expose unrestricted update execution to WebView applications, replace arbitrary binaries outside controlled deployment slots, execute arbitrary installers or bypass signature checks.

## One-file Desktop Setup

The end-user distribution target is one file:

```text
SWIR-Desktop-Setup-<version>-<channel>.exe
```

The official release pipeline builds that Setup **from the already verified signed Desktop release ZIP**, cryptographically binds `desktop-installer-build.json` to both the ZIP and Setup bytes, executes `--verify-only`, performs a clean-install smoke test and only then exposes the Setup as a release artifact.

The Setup embeds the Desktop runtime, including self-contained .NET and the pinned WebView2 Fixed Version Runtime. The end user should not be sent to Microsoft, .NET or another dependency site to make SWIR OS Desktop start.

Current installer safety properties include:

- embedded release ZIP SHA-256 verification before extraction;
- full bundled-runtime integrity verification in `--verify-only` and installation paths;
- archive traversal/absolute-path/symlink rejection;
- bounded archive entry count and expanded size;
- versioned install directories and atomic staging-to-final promotion;
- install receipts bound to version, channel, package SHA-256 and final install path;
- refusal to overwrite/reuse a tampered existing installation as if it were trusted.

## Runtime diagnostics

SWIR Runtime exposes the portable security/App Data surfaces used by Desktop Edition, including:

```js
await SwirRuntime.security.context();
await SwirRuntime.security.can('filesystem.sandbox.read');
await SwirRuntime.security.policyCatalog();
await SwirRuntime.security.isolationInfo();
await SwirRuntime.security.packageContexts();
await SwirRuntime.security.syncInstalledContexts();
await SwirRuntime.appData.info(packageId);
```

## Verification status

Windows CI checks Runtime/registry/App Bridge syntax and contracts, validates the Desktop package policy and all five isolated application entries, runs native App Data and Permission Broker self-tests, signed Update Broker/download/staging/handoff tests, transaction recovery/health-check tests, guarded activation/rollback tests, candidate launch/startup-health tests, shutdown/restart launcher tests, Desktop startup-recovery tests and updater worker tests, then builds the standalone updater worker and Windows host.

The dedicated Desktop Installer Contract builds a real self-contained payload with the pinned official WebView2 runtime, creates the one-file Setup, verifies hashes and sizes, executes Setup verification, performs a clean installation and checks fail-closed behavior against a tampered installed Host. The Desktop Release Contract also puts Setup construction and clean-install smoke testing inside the signed release/Candidate/health lifecycle.

A green CI run verifies those automated paths. It is not yet a claim that every application workflow has been exercised manually on every supported Windows hardware configuration.

## End-user requirements

- Windows 10 or Windows 11 x64.
- **One SWIR Desktop Setup EXE.**
- No manual .NET Runtime installation.
- No manual Microsoft WebView2 Runtime installation.
- No separate core language-pack download.

Runtime prerequisites are part of the verified SWIR release package rather than a manual end-user setup checklist.

## Developer requirements

A source/developer build requires Windows 10/11 x64 and the .NET 8 SDK. Packaging may require network access to acquire the repository-pinned WebView2 Fixed Version Runtime from the approved Microsoft HTTPS source; its archive hash, exact runtime version and Microsoft signature are verified before it can enter a release package.

## Build

```powershell
cd desktop\windows
dotnet restore SWIR.Desktop.Host.csproj
dotnet build SWIR.Desktop.Host.csproj -c Release
```

Self-contained Desktop publish:

```powershell
.\publish-desktop-host.ps1 `
  -PublishDir .\publish `
  -ReleaseVersion 0.5.7 `
  -Channel preview
```

A local developer build is not equivalent to an official signed release.

## Next host milestones

1. deploy and verify the protected production package/catalog signing roots and key rotation process;
2. add production Authenticode signing and verification for public Setup/Host executables without committing private signing keys;
3. add user-facing installer upgrade/uninstall lifecycle and polished localized installer UI while preserving transactional/fail-closed behavior;
4. continue hardening update/restart recovery with packaged Windows failure-injection tests;
5. expand isolated-origin runtime smoke coverage and full application localization/accessibility;
6. reduce remaining build warnings and continue performance/startup profiling before promoting Desktop Edition from preview.
