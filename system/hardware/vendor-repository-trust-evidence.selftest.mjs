import assert from 'node:assert/strict';
import zlib from 'node:zlib';
import {
  collectVendorRepositoryEvidence,
  getVendorRepositoryEvidenceProfile,
  parseGpgPrimaryFingerprint,
  parsePackagesIndex,
  parseValidSignatures,
  verifyInReleaseFreshness,
  VendorRepositoryEvidencePolicy
} from './vendor-repository-trust-evidence.mjs';

const NOW = new Date('2026-09-19T00:00:00.000Z');
const profile = getVendorRepositoryEvidenceProfile('nvidia-debian13-amd64');
const fingerprint = profile.expectedFingerprint;
const signerFingerprint = fingerprint;

assert.equal(profile.hardwareVendor, '10de');
assert.equal(profile.distribution.id, 'debian');
assert.equal(profile.distribution.versionId, '13');
assert.equal(profile.distribution.architecture, 'x86_64');
assert.equal(profile.expectedKeyId, '8793F200');
assert.equal(profile.expectedFingerprint, '02182E60104FCDC26EAE1B8597A5D4CB8793F200');
assert.deepEqual(profile.requiredPackages, ['cuda-keyring', 'nvidia-open']);

assert.equal(
  parseGpgPrimaryFingerprint(`pub:-:4096:1:DEADBEEF:0:0::::\nfpr:::::::::${fingerprint}:\nsub:-:2048:1:BEEF:0:0::::\nfpr:::::::::BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB:\n`),
  fingerprint
);
assert.deepEqual(
  parseValidSignatures(`[GNUPG:] NEWSIG\n[GNUPG:] VALIDSIG ${signerFingerprint} 2026-09-18 0 4 0 1 10 01 00 ${fingerprint}\n`),
  [{ signerFingerprint, primaryFingerprint: fingerprint }]
);
assert.deepEqual(
  [...parsePackagesIndex('Package: cuda-keyring\nVersion: 1\n\nPackage: nvidia-open\nVersion: 2\n')],
  ['cuda-keyring', 'nvidia-open']
);

const freshInRelease = Buffer.from(
  '-----BEGIN PGP SIGNED MESSAGE-----\n' +
  'Hash: SHA256\n\n' +
  'Origin: NVIDIA\n' +
  'Date: Thu, 10 Sep 2026 19:12:59 +0000\n' +
  'SHA256:\n deadbeef 1 Packages.gz\n' +
  '-----BEGIN PGP SIGNATURE-----\nFAKE\n-----END PGP SIGNATURE-----\n'
);
const freshWithValidUntil = Buffer.from(
  '-----BEGIN PGP SIGNED MESSAGE-----\nHash: SHA256\n\n' +
  'Date: Fri, 18 Sep 2026 00:00:00 +0000\n' +
  'Valid-Until: Sun, 20 Sep 2026 00:00:00 +0000\n' +
  '-----BEGIN PGP SIGNATURE-----\nFAKE\n-----END PGP SIGNATURE-----\n'
);

const fallbackFreshness = verifyInReleaseFreshness(freshInRelease, { now: NOW });
assert.equal(fallbackFreshness.freshnessVerified, true);
assert.equal(fallbackFreshness.signedAt, '2026-09-10T19:12:59.000Z');
assert.equal(fallbackFreshness.validUntil, null);
assert.equal(fallbackFreshness.expirySource, 'max-age-fallback');
assert.equal(fallbackFreshness.maxAgeSeconds, 14 * 24 * 60 * 60);
assert.equal(fallbackFreshness.maxFutureSkewSeconds, 24 * 60 * 60);
assert.equal(fallbackFreshness.effectiveValidUntil, '2026-09-24T19:12:59.000Z');

const explicitFreshness = verifyInReleaseFreshness(freshWithValidUntil, { now: NOW });
assert.equal(explicitFreshness.validUntil, '2026-09-20T00:00:00.000Z');
assert.equal(explicitFreshness.effectiveValidUntil, '2026-09-20T00:00:00.000Z');
assert.equal(explicitFreshness.expirySource, 'valid-until');

for (const [body, code] of [
  ['Origin: NVIDIA\n', 'INRELEASE_DATE_MISSING'],
  ['Date: nonsense\n', 'INRELEASE_DATE_INVALID'],
  ['Date: Thu, 03 Sep 2026 00:00:00 +0000\n', 'INRELEASE_TOO_OLD'],
  ['Date: Mon, 21 Sep 2026 00:00:01 +0000\n', 'INRELEASE_DATE_IN_FUTURE'],
  ['Date: Fri, 18 Sep 2026 00:00:00 +0000\nValid-Until: Fri, 18 Sep 2026 00:00:00 +0000\n', 'INRELEASE_VALIDITY_WINDOW_INVALID'],
  ['Date: Fri, 18 Sep 2026 00:00:00 +0000\nValid-Until: Fri, 18 Sep 2026 12:00:00 +0000\n', 'INRELEASE_EXPIRED']
]) {
  assert.throws(
    () => verifyInReleaseFreshness(Buffer.from(body), { now: NOW }),
    error => error.code === code,
    `expected ${code}`
  );
}

const resources = new Map([
  [new URL(profile.keyPath, profile.origin).toString(), Buffer.from('FAKE KEY')],
  [new URL(profile.inReleasePath, profile.origin).toString(), freshInRelease],
  [new URL(profile.packagesPath, profile.origin).toString(),
    zlib.gzipSync(Buffer.from('Package: cuda-keyring\nVersion: 1\n\nPackage: nvidia-open\nVersion: 2\n'))]
]);

function mockFetch(url, options = {}) {
  assert.equal(options.redirect, 'manual');
  assert.equal(new URL(url).origin, profile.origin);
  const body = resources.get(url);
  if (!body) return Promise.resolve({ status: 404, headers: { get: () => null }, arrayBuffer: async () => Buffer.alloc(0) });
  return Promise.resolve({
    status: 200,
    headers: { get: name => name.toLowerCase() === 'content-length' ? String(body.length) : null },
    arrayBuffer: async () => body
  });
}

function mockTool(command, args) {
  if (command === 'gpg' && args.includes('--show-keys')) {
    return { stdout: `pub:-:4096:1:DEADBEEF:0:0::::\nfpr:::::::::${fingerprint}:\n`, stderr: '', status: 0 };
  }
  if (command === 'gpg' && args.includes('--dearmor')) return { stdout: '', stderr: '', status: 0 };
  if (command === 'gpgv') {
    return { stdout: `[GNUPG:] VALIDSIG ${signerFingerprint} 2026-09-18 0 4 0 1 10 01 00 ${fingerprint}\n`, stderr: '', status: 0 };
  }
  throw new Error(`unexpected tool invocation: ${command} ${args.join(' ')}`);
}

const evidence = await collectVendorRepositoryEvidence(profile.id, {
  fetchImpl: mockFetch,
  toolRunner: mockTool,
  now: NOW
});
assert.equal(evidence.schema, 'swir.vendor-repository-evidence/0.1');
assert.equal(evidence.qualificationOnly, true);
assert.equal(evidence.authorizesMutation, false);
assert.equal(evidence.authorizesRepositoryEnablement, false);
assert.equal(evidence.key.fingerprint, fingerprint);
assert.equal(evidence.key.expectedFingerprint, fingerprint);
assert.equal(evidence.inRelease.validSignatureFingerprint, signerFingerprint);
assert.equal(evidence.inRelease.validSignaturePrimaryFingerprint, fingerprint);
assert.equal(evidence.inRelease.freshnessVerified, true);
assert.equal(evidence.inRelease.expirySource, 'max-age-fallback');
assert.deepEqual(evidence.packages.verified, ['cuda-keyring', 'nvidia-open']);
assert.equal(VendorRepositoryEvidencePolicy.arbitraryUrls, false);
assert.equal(VendorRepositoryEvidencePolicy.fullFingerprintPinning, true);
assert.equal(VendorRepositoryEvidencePolicy.signedMetadataFreshnessRequired, true);

await assert.rejects(
  collectVendorRepositoryEvidence(profile.id, {
    fetchImpl: async () => ({
      status: 302,
      headers: { get: name => name.toLowerCase() === 'location' ? 'https://evil.example/' : null },
      arrayBuffer: async () => Buffer.from('redirect')
    }),
    toolRunner: mockTool,
    now: NOW
  }),
  error => error.code === 'FETCH_STATUS_INVALID' || error.code === 'FETCH_REDIRECT_FORBIDDEN'
);

await assert.rejects(
  collectVendorRepositoryEvidence(profile.id, {
    fetchImpl: mockFetch,
    toolRunner(command, args) {
      if (command === 'gpg' && args.includes('--show-keys')) {
        return { stdout: 'pub:-:4096:1:DEADBEEF:0:0::::\nfpr:::::::::FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFDEADBEEF:\n', stderr: '', status: 0 };
      }
      return mockTool(command, args);
    },
    now: NOW
  }),
  error => error.code === 'KEY_FINGERPRINT_MISMATCH'
);

const missingPackageResources = new Map(resources);
missingPackageResources.set(
  new URL(profile.packagesPath, profile.origin).toString(),
  zlib.gzipSync(Buffer.from('Package: cuda-keyring\nVersion: 1\n'))
);
await assert.rejects(
  collectVendorRepositoryEvidence(profile.id, {
    fetchImpl: async (url, options = {}) => {
      assert.equal(options.redirect, 'manual');
      const body = missingPackageResources.get(url);
      return {
        status: 200,
        headers: { get: name => name.toLowerCase() === 'content-length' ? String(body.length) : null },
        arrayBuffer: async () => body
      };
    },
    toolRunner: mockTool,
    now: NOW
  }),
  error => error.code === 'REQUIRED_PACKAGE_MISSING'
);

const staleResources = new Map(resources);
staleResources.set(
  new URL(profile.inReleasePath, profile.origin).toString(),
  Buffer.from('Date: Thu, 03 Sep 2026 00:00:00 +0000\n')
);
await assert.rejects(
  collectVendorRepositoryEvidence(profile.id, {
    fetchImpl: async (url, options = {}) => {
      assert.equal(options.redirect, 'manual');
      const body = staleResources.get(url);
      return {
        status: 200,
        headers: { get: name => name.toLowerCase() === 'content-length' ? String(body.length) : null },
        arrayBuffer: async () => body
      };
    },
    toolRunner: mockTool,
    now: NOW
  }),
  error => error.code === 'INRELEASE_TOO_OLD'
);

console.log('vendor-repository-trust-evidence selftest: ok');
