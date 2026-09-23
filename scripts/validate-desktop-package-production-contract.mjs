import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(scriptDir, '..');
let passed = 0;

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

function requireText(source, needle, label) {
  if (!source.includes(needle)) throw new Error(`Desktop package production contract failed: ${label}`);
  passed += 1;
  console.log(`PASS ${label}`);
}

function requireOrder(source, first, second, label) {
  const a = source.indexOf(first);
  const b = source.indexOf(second);
  if (a < 0 || b < 0 || a >= b) throw new Error(`Desktop package production contract failed: ${label}`);
  passed += 1;
  console.log(`PASS ${label}`);
}

const bridge = read('desktop/windows/DesktopPackageBridge.cs');
const trustStore = read('desktop/windows/DesktopPackageTrustRootStore.cs');
const runtime = read('swir-runtime.js');
const builder = read('desktop/windows/build-store-packages.ps1');
const release = read('.github/workflows/desktop-release.yml');
const evidence = read('.github/workflows/desktop-package-signing-evidence.yml');

requireText(runtime, "const SIGNED_RELEASE_ARTIFACT_REF = 'release:verified-catalog-artifact';", 'runtime pins the catalog-selected release artifact reference');
requireText(runtime, 'installAuthorizedReleaseArtifact:', 'runtime exposes signed release artifact installation only through structured catalog authorization');
requireText(bridge, 'CATALOG_PACKAGE_IDENTITY_MISMATCH', 'native bridge binds signed catalog identity to the package manifest');
requireText(bridge, 'PACKAGE_SIGNATURE_IDENTITY_MISMATCH', 'native bridge binds embedded package signature identity to the package manifest');
requireText(bridge, '_packageSignatures.Verify(path, _requireSignedPackages)', 'native bridge independently verifies embedded package signatures');
requireOrder(bridge, '_packageSignatures.Verify(path, _requireSignedPackages)', '_installer.Install(path, trust.Sha256, ToTrustProof(trust))', 'signature verification completes before package installation mutation');

requireText(trustStore, 'Path.Combine(AppContext.BaseDirectory, DefaultFileName)', 'shipping package trust roots are loaded from the Desktop runtime directory');
requireText(trustStore, 'PACKAGE_TRUST_ROOTS_MISSING', 'explicit missing trust-root configuration fails closed');
requireText(trustStore, 'PACKAGE_TRUST_ROOT_REQUIRED', 'requireSignedPackages cannot run without an enabled package signing root');

requireText(builder, 'dotnet $packageSigner sign $artifactPath', 'Store builder signs each Desktop package artifact');
requireText(builder, 'dotnet $packageSigner verify $artifactPath $packageTrustRoots', 'Store builder independently verifies each signed package');
requireText(builder, 'requireSignedPackages -ne $true', 'Store builder verifies that generated package trust policy is fail-closed');
requireOrder(builder, 'dotnet $packageSigner sign $artifactPath', '$sha = (Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256)', 'catalog SHA-256 is calculated from final signed package bytes');

requireText(release, 'package_key_id:', 'Desktop release requires an explicit package signing key identifier');
requireText(release, 'SWIR_PACKAGE_SIGNING_PRIVATE_KEY_BASE64', 'Desktop release requires protected package signing key material');
requireText(release, "Copy-Item -LiteralPath (Join-Path $store 'package-trust-roots.json') -Destination (Join-Path $publish 'package-trust-roots.json') -Force", 'release stages the generated fail-closed package trust policy beside the Desktop Host');
requireText(release, '$packageTrust.requireSignedPackages -ne $true', 'release rejects a staged package policy that does not require signatures');
requireText(release, 'Final bundle package signature verification failed', 'final release bundle independently verifies every embedded package signature');
requireText(release, "'package-trust-roots.json'", 'package trust roots are mandatory release artifacts');

requireText(evidence, 'environment: desktop-production-signing', 'production signing evidence is protected by a dedicated GitHub environment');
requireText(evidence, 'SWIR_PACKAGE_SIGNING_PRIVATE_KEY_BASE64', 'production evidence uses protected package signing material');
requireText(evidence, 'Independently validate production signing evidence', 'production evidence has an independent validation step');
requireText(evidence, 'Destroy protected signing key material', 'production evidence destroys temporary private-key material');

console.log(`Desktop package production contract passed: ${passed} checks.`);
