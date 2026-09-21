import fs from 'node:fs';

const fail = (message) => { throw new Error(message); };
const read = (path) => fs.readFileSync(path, 'utf8');

const workflow = read('.github/workflows/desktop-release.yml');
const roots = JSON.parse(read('desktop/windows/catalog-trust-roots.json'));
const packageRoots = JSON.parse(read('desktop/windows/package-trust-roots.json'));
const lifecycle = read('desktop/windows/DesktopSignedPackageLifecycleSelfTests.cs');
const cutover = read('.github/workflows/desktop-catalog-cutover-contract.yml');
const runtimeStage = read('desktop/windows/stage-desktop-runtime.ps1');
const packageBridge = read('desktop/windows/DesktopPackageBridge.cs');
const packageInstaller = read('desktop/windows/DesktopAppPackageInstaller.cs');
const packageSignatureVerifier = read('desktop/windows/DesktopPackageSignatureVerifier.cs');
const packageSignatureTool = read('desktop/windows/DesktopPackageSignatureTool.cs');
const storeBuilder = read('desktop/windows/build-store-packages.ps1');

const requiredWorkflowFragments = [
  'SWIR_CATALOG_SIGNING_PRIVATE_KEY_PEM: ${{ secrets.SWIR_CATALOG_SIGNING_PRIVATE_KEY_PEM }}',
  'SWIR_CATALOG_EXPECTED_ROOT_SHA256: ${{ secrets.SWIR_CATALOG_SIGNING_PUBLIC_KEY_SHA256 }}',
  'SWIR_CATALOG_SEQUENCE: ${{ inputs.catalog_sequence }}',
  'SWIR_CATALOG_KEY_ID: ${{ inputs.catalog_key_id }}',
  'SWIR_PACKAGE_KEY_ID: ${{ inputs.package_key_id }}',
  'SWIR_PACKAGE_SIGNING_PRIVATE_KEY_BASE64: ${{ secrets.SWIR_PACKAGE_SIGNING_PRIVATE_KEY_BASE64 }}',
  'Build signed reviewed Desktop Store swirapp artifacts',
  '-PackageSigningKeyId $env:SWIR_PACKAGE_KEY_ID',
  '-PackageSigningPrivateKeyFile $packagePrivateKey',
  '-PackageTrustRootsOutput $packageTrustRoots',
  'package-trust-roots.json',
  'requireSignedPackages -ne $true',
  'dotnet $packageSigner verify',
  'build-signed-catalog-release.mjs',
  'verify-catalog-root-pin.mjs',
  'requireSignedCatalog -ne $true',
  'Verify staged Store artifacts against signed catalog',
  'persist-credentials: false'
];
for (const fragment of requiredWorkflowFragments) {
  if (!workflow.includes(fragment)) fail(`Desktop release trust-chain wiring missing: ${fragment}`);
}

const catalogPrivateKeyAssignments = workflow
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter((line) => line.startsWith('SWIR_CATALOG_SIGNING_PRIVATE_KEY_PEM:'));
const expectedCatalogPrivateKeyAssignment =
  'SWIR_CATALOG_SIGNING_PRIVATE_KEY_PEM: ${{ secrets.SWIR_CATALOG_SIGNING_PRIVATE_KEY_PEM }}';
if (catalogPrivateKeyAssignments.length === 0 || catalogPrivateKeyAssignments.some((line) => line !== expectedCatalogPrivateKeyAssignment)) {
  fail('Catalog signing private key must only enter the release workflow through GitHub Actions secrets.');
}

const packagePrivateKeyAssignments = workflow
  .split(/\r?\n/)
  .map((line) => line.trim())
  .filter((line) => line.startsWith('SWIR_PACKAGE_SIGNING_PRIVATE_KEY_BASE64:'));
const expectedPackagePrivateKeyAssignment =
  'SWIR_PACKAGE_SIGNING_PRIVATE_KEY_BASE64: ${{ secrets.SWIR_PACKAGE_SIGNING_PRIVATE_KEY_BASE64 }}';
if (packagePrivateKeyAssignments.length === 0 || packagePrivateKeyAssignments.some((line) => line !== expectedPackagePrivateKeyAssignment)) {
  fail('Package signing private key must only enter the release workflow through GitHub Actions secrets.');
}
if (/BEGIN (?:ED25519 |EC |RSA )?PRIVATE KEY/.test(workflow)) {
  fail('Private signing-key material must never be embedded in the release workflow.');
}

if (roots.schema !== 'swir.catalog-trust-roots/1.0') fail('Unexpected checked-in catalog trust-root schema.');
if (roots.requireSignedCatalog !== false || !Array.isArray(roots.roots) || roots.roots.length !== 0) {
  fail('The source-tree preview trust store must remain empty/fail-neutral; production roots are staged only by the controlled release pipeline.');
}
if (packageRoots.schema !== 'swir.package-trust-roots/1.0') fail('Unexpected checked-in package trust-root schema.');
if (packageRoots.requireSignedPackages !== false || !Array.isArray(packageRoots.roots) || packageRoots.roots.length !== 0) {
  fail('The source-tree package trust store must remain empty/fail-neutral; production package roots must be provisioned by a controlled signing pipeline.');
}

for (const fragment of [
  "Copy-Item -LiteralPath (Join-Path $catalogRelease 'catalog-trust-roots.json')",
  "$trust.requireSignedCatalog -ne $true",
  "@($trust.roots).Count -lt 1",
  "throw 'Production signed catalog trust roots must require signed catalogs and contain at least one root.'"
]) {
  if (!runtimeStage.includes(fragment)) fail(`Desktop runtime signed-catalog staging guard missing: ${fragment}`);
}

for (const fragment of [
  'legacySha256Fallback = _catalogTrust is null',
  'trustMode = _catalogTrust is null ? "LEGACY_SHA_UNTIL_ROOT_PROVISIONED" : "SIGNED_CATALOG_REQUIRED"',
  'persistedTrustProvenance = true',
  'packageSignatureVerification = true',
  'packageSignatureRequired = _requireSignedPackages',
  'packageSignatureTrustedRoots = _packageSignatures.TrustedRootCount',
  'CATALOG_AUTHORIZATION_REQUIRED',
  '_packageSignatures.Verify(path, _requireSignedPackages)',
  '_installer.Install(path, trust.Sha256, ToTrustProof(trust))',
  'DesktopPackageTrustProof.SignedCatalog',
  'trust.CatalogSequence.Value',
  'trust.ExpiresAt.Value'
]) {
  if (!packageBridge.includes(fragment)) fail(`Desktop package bridge production trust boundary missing: ${fragment}`);
}

// The signed catalog is only useful if its authorized digest is enforced again at the final
// native payload boundary. Keep these invariants in CI so a refactor cannot accidentally turn
// signed metadata into an identity-only check or replace constant-time digest comparison.
for (const fragment of [
  'integrity = "sha256-required"',
  'trustProvenance = "deployment-recorded"',
  'signedCatalogProvenance = true',
  'var expected = NormalizeHash(expectedSha256);',
  'var actual = ComputeSha256(bundlePath);',
  'CryptographicOperations.FixedTimeEquals',
  'PACKAGE_HASH_MISMATCH',
  'PACKAGE_TRUST_PROOF_INVALID',
  'PACKAGE_TRUST_EXPIRED',
  'TrustMode',
  'SignatureVerified',
  'SignerKeyId',
  'CatalogSequence',
  'CatalogVersion',
  'TrustExpiresAt',
  'bundleSha256 = actual'
]) {
  if (!packageInstaller.includes(fragment)) fail(`Desktop package payload integrity/trust boundary missing: ${fragment}`);
}
const hashCheck = packageInstaller.indexOf('CryptographicOperations.FixedTimeEquals');
const archiveOpen = packageInstaller.indexOf('ZipFile.OpenRead(bundlePath)');
if (hashCheck < 0 || archiveOpen < 0 || hashCheck > archiveOpen) {
  fail('Desktop package SHA-256 must be verified before the .swirapp archive is opened or extracted.');
}

for (const fragment of [
  'SignatureSchema = "swir.package-signature/1.0"',
  'PACKAGE_SIGNATURE_REQUIRED',
  'PACKAGE_CONTENT_DIGEST_MISMATCH',
  'PACKAGE_SIGNATURE_UNKNOWN_KEY',
  'SignatureAlgorithm.Ed25519.Verify',
  'CryptographicOperations.FixedTimeEquals'
]) {
  if (!packageSignatureVerifier.includes(fragment)) fail(`Embedded package signature verifier invariant missing: ${fragment}`);
}

for (const fragment of [
  'trust-root',
  'verify',
  'requireSignedPackages = true',
  'DesktopPackageTrustRootStore.LoadProvisioned()',
  'Verify(bundlePath, requireSignature: true)',
  'CryptographicOperations.ZeroMemory'
]) {
  if (!packageSignatureTool.includes(fragment)) fail(`Package signing utility release guard missing: ${fragment}`);
}

for (const fragment of [
  'PackageSigningKeyId',
  'PackageSigningPrivateKeyFile',
  'PackageTrustRootsOutput',
  'PackageSignerDll',
  'dotnet $packageSigner sign',
  'dotnet $packageSigner verify',
  'The signed bytes are authoritative',
  'Get-FileHash -LiteralPath $artifactPath -Algorithm SHA256'
]) {
  if (!storeBuilder.includes(fragment)) fail(`Reviewed Store package signing pipeline missing: ${fragment}`);
}

for (const fragment of [
  'requireSignedCatalog = true',
  'requireSignedPackages = true',
  'SignatureAlgorithm.Ed25519',
  'PACKAGE_SIGNATURE_REQUIRED',
  'PACKAGE_CONTENT_DIGEST_MISMATCH',
  'CATALOG_ROLLBACK_DETECTED',
  'persistedTrustProvenance',
  'packageSignatureRequired',
  'packageSignatureTrustedRoots',
  'trustMode',
  'signatureVerified',
  'signerKeyId',
  'catalogSequence',
  'catalogVersion',
  'trustExpiresAt',
  'signed package status must preserve signed catalog trust mode',
  'rollback should restore v1 catalog sequence',
  'Rolling the payload back must never roll the catalog trust high-water mark back.'
]) {
  if (!lifecycle.includes(fragment)) fail(`Signed catalog + package lifecycle/provenance coverage missing: ${fragment}`);
}

for (const fragment of [
  'test-catalog-root-cutover-e2e.mjs',
  'verify-catalog-root-rotation.mjs',
  'Run signed install-update-restart-rollback root cutover lifecycle'
]) {
  if (!cutover.includes(fragment)) fail(`Catalog root-cutover contract coverage missing: ${fragment}`);
}

console.log('Desktop release trust-chain preflight passed.');