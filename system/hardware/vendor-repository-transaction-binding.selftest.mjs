import assert from 'node:assert/strict';
import {
  bindVendorRepositoryTransaction,
  assertVendorRepositoryTransactionBinding,
  VendorRepositoryTransactionBindingPolicy
} from './vendor-repository-transaction-binding.mjs';

const fingerprint = '02182E60104FCDC26EAE1B8597A5D4CB8793F200';
const review = {
  schema: 'swir.vendor-official-repository-review/0.1',
  repositoryId: 'nvidia-cuda-debian13-x86_64',
  vendor: 'NVIDIA',
  source: { class: 'vendor-official-repository', ref: 'vendor-repo:nvidia-cuda-debian13-x86_64' },
  packageManager: 'apt',
  baseUrl: 'https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/',
  suites: ['./'],
  components: [],
  packages: ['cuda-keyring', 'nvidia-open'],
  keyring: { path: '/usr/share/keyrings/nvidia-cuda-archive-keyring.gpg', fingerprint },
  hardwareVendor: '10de',
  distribution: { id: 'debian', versionId: '13', architecture: 'x86_64' },
  trustedSource: true,
  directBinaryDownloads: false,
  mutationAuthorized: false,
  automaticEnable: false
};
const evidence = {
  schema: 'swir.vendor-repository-evidence/0.1',
  qualificationOnly: true,
  authorizesMutation: false,
  authorizesRepositoryEnablement: false,
  profileId: 'nvidia-debian13-amd64',
  repositoryId: review.repositoryId,
  vendor: 'NVIDIA',
  hardwareVendor: '10de',
  distribution: { id: 'debian', versionId: '13', architecture: 'x86_64' },
  source: { origin: 'https://developer.download.nvidia.com', basePath: '/compute/cuda/repos/debian13/x86_64/' },
  key: { fingerprint, expectedFingerprint: fingerprint, sha256: 'a'.repeat(64) },
  inRelease: {
    validSignaturePrimaryFingerprint: fingerprint,
    freshnessVerified: true,
    signedAt: '2026-09-18T00:00:00.000Z',
    effectiveValidUntil: '2026-09-30T00:00:00.000Z',
    checkedAt: '2026-09-19T00:00:00.000Z',
    sha256: 'b'.repeat(64)
  },
  packages: { verified: ['cuda-keyring', 'nvidia-open'], indexSha256: 'c'.repeat(64) }
};
const now = new Date('2026-09-19T01:00:00.000Z');
const bind = (changes = {}) => bindVendorRepositoryTransaction({
  review: structuredClone(review),
  evidence: structuredClone(evidence),
  requestedPackages: ['nvidia-open'],
  now,
  ...changes
});

const first = bind();
assert.equal(assertVendorRepositoryTransactionBinding(first), true);
assert.equal(first.transactionRoute.repositoryActivationImplementedHere, false);
assert.equal(first.packagePlanInputs[0].trust.vendorRepositoryBindingDigest, first.bindingDigest);
assert.equal(first.packagePlanInputs[0].trust.sourceClass, 'distribution-repository');
assert.equal(first.packagePlanInputs[0].trust.upstreamSourceClass, 'vendor-official-repository');
assert.equal(first.mutationAuthorized, false);
assert.equal(first.repositoryEnablementAuthorized, false);
assert.equal(bind().bindingDigest, first.bindingDigest, 'binding digest must be deterministic');

const changedScope = structuredClone(review);
changedScope.suites = ['stable'];
assert.notEqual(bind({ review: changedScope }).bindingDigest, first.bindingDigest, 'changing bound repository scope must change digest');

function rejects(code, changes) {
  assert.throws(() => bind(changes), error => error?.code === code, `expected ${code}`);
}

const badFingerprint = structuredClone(review);
badFingerprint.keyring.fingerprint = 'F'.repeat(40);
rejects('BINDING_FINGERPRINT_MISMATCH', { review: badFingerprint });

const badUrl = structuredClone(review);
badUrl.baseUrl = 'https://developer.download.nvidia.com/compute/cuda/repos/debian12/x86_64/';
rejects('BINDING_BASE_URL_MISMATCH', { review: badUrl });

const badPlatform = structuredClone(review);
badPlatform.distribution.versionId = '12';
rejects('BINDING_PLATFORM_MISMATCH', { review: badPlatform });

rejects('BINDING_PACKAGE_NOT_ALLOWLISTED', { requestedPackages: ['evil-driver'] });

const missingEvidencePackage = structuredClone(evidence);
missingEvidencePackage.packages.verified = ['cuda-keyring'];
rejects('BINDING_PACKAGE_NOT_QUALIFIED', { evidence: missingEvidencePackage });

const expired = structuredClone(evidence);
expired.inRelease.effectiveValidUntil = '2026-09-18T00:00:00.000Z';
rejects('BINDING_EVIDENCE_EXPIRED', { evidence: expired });

const preauthorized = structuredClone(evidence);
preauthorized.authorizesMutation = true;
rejects('BINDING_EVIDENCE_PREAUTHORIZED', { evidence: preauthorized });

const signatureMismatch = structuredClone(evidence);
signatureMismatch.inRelease.validSignaturePrimaryFingerprint = 'D'.repeat(40);
rejects('BINDING_SIGNATURE_MISMATCH', { evidence: signatureMismatch });

assert.equal(VendorRepositoryTransactionBindingPolicy.sideEffectFree, true);
assert.equal(VendorRepositoryTransactionBindingPolicy.existingJournaledPackageBrokerRequired, true);
assert.equal(VendorRepositoryTransactionBindingPolicy.directAptMutationAllowed, false);
assert.equal(VendorRepositoryTransactionBindingPolicy.directPkexecAllowed, false);
console.log(`vendor repository transaction binding self-test passed digest=${first.bindingDigest}`);
