import assert from 'node:assert/strict';
import zlib from 'node:zlib';
import {
  collectVendorRepositoryEvidence,
  getVendorRepositoryEvidenceProfile,
  parseGpgPrimaryFingerprint,
  parsePackagesIndex,
  parseValidSignatures,
  VendorRepositoryEvidencePolicy
} from './vendor-repository-trust-evidence.mjs';

const fingerprint = '0123456789ABCDEF0123456789ABCDEF8793F200';
const signerFingerprint = 'AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA';
const profile = getVendorRepositoryEvidenceProfile('nvidia-debian13-amd64');
assert.equal(profile.hardwareVendor, '10de');
assert.equal(profile.distribution.id, 'debian');
assert.equal(profile.distribution.versionId, '13');
assert.equal(profile.distribution.architecture, 'x86_64');
assert.equal(profile.expectedKeyId, '8793F200');
assert.deepEqual(profile.requiredPackages, ['cuda-keyring', 'nvidia-open']);

assert.equal(
  parseGpgPrimaryFingerprint(`pub:-:4096:1:DEADBEEF:0:0::::\nfpr:::::::::${fingerprint}:\nsub:-:2048:1:BEEF:0:0::::\nfpr:::::::::BBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBBB:\n`),
  fingerprint
);
assert.deepEqual(
  parseValidSignatures(`[GNUPG:] NEWSIG\n[GNUPG:] VALIDSIG ${signerFingerprint} 2026-09-18 0 4 0 1 10 01 00 ${fingerprint}\n`),
  [{ signerFingerprint, primaryFingerprint: fingerprint }]
);
assert.deepEqual([...parsePackagesIndex('Package: cuda-keyring\nVersion: 1\n\nPackage: nvidia-open\nVersion: 2\n')], ['cuda-keyring', 'nvidia-open']);

const resources = new Map([
  [new URL(profile.keyPath, profile.origin).toString(), Buffer.from('FAKE KEY')],
  [new URL(profile.inReleasePath, profile.origin).toString(), Buffer.from('FAKE INRELEASE')],
  [new URL(profile.packagesPath, profile.origin).toString(), zlib.gzipSync(Buffer.from('Package: cuda-keyring\nVersion: 1\n\nPackage: nvidia-open\nVersion: 2\n'))]
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
  if (command === 'gpg' && args.includes('show-only')) {
    return { stdout: `pub:-:4096:1:DEADBEEF:0:0::::\nfpr:::::::::${fingerprint}:\n`, stderr: '', status: 0 };
  }
  if (command === 'gpg' && args.includes('--dearmor')) return { stdout: '', stderr: '', status: 0 };
  if (command === 'gpgv') {
    return { stdout: `[GNUPG:] VALIDSIG ${signerFingerprint} 2026-09-18 0 4 0 1 10 01 00 ${fingerprint}\n`, stderr: '', status: 0 };
  }
  throw new Error(`unexpected tool invocation: ${command} ${args.join(' ')}`);
}

const evidence = await collectVendorRepositoryEvidence(profile.id, { fetchImpl: mockFetch, toolRunner: mockTool });
assert.equal(evidence.schema, 'swir.vendor-repository-evidence/0.1');
assert.equal(evidence.qualificationOnly, true);
assert.equal(evidence.authorizesMutation, false);
assert.equal(evidence.authorizesRepositoryEnablement, false);
assert.equal(evidence.key.fingerprint, fingerprint);
assert.equal(evidence.inRelease.validSignatureFingerprint, signerFingerprint);
assert.equal(evidence.inRelease.validSignaturePrimaryFingerprint, fingerprint);
assert.deepEqual(evidence.packages.verified, ['cuda-keyring', 'nvidia-open']);
assert.equal(VendorRepositoryEvidencePolicy.arbitraryUrls, false);

await assert.rejects(
  collectVendorRepositoryEvidence(profile.id, {
    fetchImpl: async () => ({
      status: 302,
      headers: { get: name => name.toLowerCase() === 'location' ? 'https://evil.example/' : null },
      arrayBuffer: async () => Buffer.from('redirect')
    }),
    toolRunner: mockTool
  }),
  error => error.code === 'FETCH_STATUS_INVALID' || error.code === 'FETCH_REDIRECT_FORBIDDEN'
);

await assert.rejects(
  collectVendorRepositoryEvidence(profile.id, {
    fetchImpl: mockFetch,
    toolRunner(command, args) {
      if (command === 'gpg' && args.includes('show-only')) {
        return { stdout: 'pub:-:4096:1:DEADBEEF:0:0::::\nfpr:::::::::FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFDEADBEEF:\n', stderr: '', status: 0 };
      }
      return mockTool(command, args);
    }
  }),
  error => error.code === 'KEY_ID_MISMATCH'
);

const missingPackageResources = new Map(resources);
missingPackageResources.set(new URL(profile.packagesPath, profile.origin).toString(), zlib.gzipSync(Buffer.from('Package: cuda-keyring\nVersion: 1\n')));
await assert.rejects(
  collectVendorRepositoryEvidence(profile.id, {
    fetchImpl: async url => {
      const body = missingPackageResources.get(url);
      return {
        status: 200,
        headers: { get: name => name.toLowerCase() === 'content-length' ? String(body.length) : null },
        arrayBuffer: async () => body
      };
    },
    toolRunner: mockTool
  }),
  error => error.code === 'REQUIRED_PACKAGE_MISSING'
);

console.log('vendor-repository-trust-evidence selftest: ok');
