import fs from 'node:fs';
import path from 'node:path';

const root = path.resolve(import.meta.dirname, '..');
let checks = 0;

function read(relativePath) {
  return fs.readFileSync(path.join(root, relativePath), 'utf8');
}

function requireText(text, needle, label) {
  if (!text.includes(needle)) throw new Error(`Desktop update production contract failed: ${label}`);
  checks += 1;
}

function requirePattern(text, pattern, label) {
  if (!pattern.test(text)) throw new Error(`Desktop update production contract failed: ${label}`);
  checks += 1;
}

function rejectPattern(text, pattern, label) {
  if (pattern.test(text)) throw new Error(`Desktop update production contract failed: ${label}`);
  checks += 1;
}

const release = read('.github/workflows/desktop-release.yml');
const feed = read('.github/workflows/desktop-update-feed.yml');
const sourceWorkflow = read('.github/workflows/desktop-github-update-contract.yml');
const promotion = read('scripts/promote-desktop-update-feed.mjs');
const broker = read('desktop/windows/UpdateBroker.cs');
const downloader = read('desktop/windows/UpdateDownloadClient.cs');
const releasePolicy = read('desktop/windows/DesktopGitHubUpdatePolicy.cs');
const userPolicy = read('desktop/windows/DesktopUpdateUserPolicy.cs');

// Production release must be explicit, channel-bound and protected by repository secrets.
requireText(release, 'workflow_dispatch:', 'release remains an explicit operator action');
requireText(release, 'options: [preview, stable]', 'release supports only preview/stable channels');
requireText(release, 'SWIR_RELEASE_PRIVATE_KEY_PEM: ${{ secrets.SWIR_DESKTOP_RELEASE_PRIVATE_KEY_PEM }}', 'release uses protected RSA signing material');
requireText(release, "throw 'SWIR_DESKTOP_RELEASE_PRIVATE_KEY_PEM secret is not configured.'", 'release fails closed when the production RSA signing secret is missing');
requireText(release, 'publish_release:', 'release publication requires an explicit publish gate');
requireText(release, "inputs.publish_release && github.ref == 'refs/heads/main'", 'GitHub Release publication is main-only');
requirePattern(release, /desktop-update-\$env:SWIR_RELEASE_CHANNEL\.json/, 'release bundle contains the signed channel feed');
rejectPattern(release, /generateKeyPairSync|generateKeyPair\(/, 'production release must not synthesize a fallback signing key');

// Publication point must be derived only from a published immutable Desktop GitHub Release.
requireText(feed, 'release:', 'feed promotion is release-event driven');
requireText(feed, 'types: [published]', 'feed promotion waits for published releases');
requireText(feed, '^desktop-v([0-9]+\\.[0-9]+\\.[0-9]+)-(preview|stable)$', 'release tag is version/channel bound');
requireText(feed, 'SWIR_DESKTOP_UPDATE_KEY_ID', 'feed promotion pins the update key id');
requireText(feed, 'SWIR_DESKTOP_UPDATE_PUBLIC_KEY_PEM_B64', 'feed promotion pins the public verification key');
requireText(feed, 'gh release download "$RELEASE_TAG"', 'feed promotion downloads exact immutable release assets');
requireText(feed, 'node scripts/promote-desktop-update-feed.mjs', 'feed promotion passes through the cryptographic verifier');
requireText(feed, '--output "updates/${CHANNEL}/desktop-update-${CHANNEL}.json"', 'stable/preview feeds publish to repository-owned channel paths');

// Feed promotion independently verifies signature, immutable URL, package bytes and monotonicity.
requireText(promotion, "const ALGORITHM = 'RSA-PSS-SHA256';", 'feed envelope algorithm is RSA-PSS-SHA256');
requireText(promotion, 'verifyEnvelopeSignature(incoming, publicKeyPem, expectedKeyId);', 'feed signature is verified before publication');
requireText(promotion, 'verifyPackageArtifact(incoming.payload, packagePath);', 'release package is independently verified before publication');
requireText(promotion, 'https://github.com/Swir/SWIR_OS/releases/download/${tag}/', 'feed package URL is immutable and canonical');
requireText(promotion, 'Refusing feed downgrade', 'feed downgrade is rejected');
requireText(promotion, 'Refusing conflicting envelope', 'same-version conflicting envelope is rejected');

// Shipped policy binds clients to the same repository-owned stable/preview channel topology.
requireText(releasePolicy, 'normalizedChannel is not ("preview" or "stable")', 'client policy accepts only preview/stable channels');
requireText(releasePolicy, 'https://raw.githubusercontent.com/{Repo}/main/updates/{normalizedChannel}/desktop-update-{normalizedChannel}.json', 'client manifest URL matches repository-owned channel feed');
requireText(releasePolicy, 'PackageHosts = new[] { "github.com" }', 'client package source is restricted to GitHub');

// Runtime trust must fail closed before staging/mutation.
requireText(broker, 'rsa.VerifyData', 'manifest signature verification is present');
requireText(broker, 'RSASignaturePadding.Pss', 'runtime signature verification uses RSA-PSS');
requireText(broker, 'UPDATE_CHANNEL_MISMATCH', 'runtime rejects cross-channel manifests');
requireText(broker, 'UPDATE_DOWNGRADE_BLOCKED', 'runtime rejects downgrades');
requireText(broker, 'UPDATE_PACKAGE_HASH_MISMATCH', 'runtime rejects package hash mismatches');
requireText(downloader, 'OfficialReleasePrefix = "/Swir/SWIR_OS/releases/download/"', 'runtime downloads only immutable official release paths');
requireText(downloader, 'MaxTrustedRedirects = 1', 'runtime permits at most one trusted GitHub release redirect');
requireText(downloader, 'UPDATE_REDIRECT_TARGET_DENIED', 'runtime rejects untrusted redirect targets');

// User policy changes scheduling only; it must not bypass the trust path or force restarts.
requireText(userPolicy, 'Manual,', 'Manual update mode exists');
requireText(userPolicy, 'NotifyOnly,', 'Notify-only update mode exists');
requireText(userPolicy, 'Automatic', 'Automatic update mode exists');
requirePattern(userPolicy, /DesktopUpdateUserMode\.Automatic\s*=>\s*new\([\s\S]*?AutomaticPrepare:\s*true,[\s\S]*?AutomaticRestart:\s*false/, 'Automatic mode prepares verified updates but does not force restart');
requireText(userPolicy, 'weaken release provenance, signature, source-host, privilege or transaction gates.', 'user policy documents the non-bypass security invariant');

// CI must execute the dynamic cryptographic/runtime contracts in addition to this topology audit.
requireText(sourceWorkflow, 'SWIR.Desktop.Update.SelfTests.csproj', 'CI executes update signature/hash self-tests');
requireText(sourceWorkflow, 'SWIR.Desktop.GitHubUpdateSource.SelfTests.csproj', 'CI executes immutable GitHub source self-tests');
requireText(sourceWorkflow, 'SWIR.Desktop.UpdateUserPolicyIntegration.SelfTests.csproj', 'CI executes user-policy integration self-tests');
requireText(sourceWorkflow, 'test-desktop-update-feed-security.mjs', 'CI executes signed feed security tests');

console.log(JSON.stringify({
  schema: 'swir.desktop-update-production-contract/1.0',
  valid: true,
  checks,
  channels: ['preview', 'stable'],
  repository: 'Swir/SWIR_OS',
}));
