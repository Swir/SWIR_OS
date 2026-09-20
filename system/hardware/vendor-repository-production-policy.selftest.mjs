import assert from 'node:assert/strict';
import fs from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import {
  parseVendorOfficialRepositoryPolicy,
  resolveVendorOfficialRepositories,
  assertSafeVendorRepositoryReview,
  VendorOfficialRepositoryPolicy
} from './vendor-official-repository-service.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const policyPath = path.join(here, 'vendor-repositories.debian13.json');
const document = JSON.parse(fs.readFileSync(policyPath, 'utf8'));
const policy = parseVendorOfficialRepositoryPolicy(document);
assert.equal(policy.entries.length, 1);
assert.equal(policy.defaultEnabled, false);
assert.equal(policy.allowDirectBinaryDownloads, false);

const reviews = resolveVendorOfficialRepositories(policy, {
  hardwareVendor: '10de', distributionId: 'debian', versionId: '13', architecture: 'x86_64'
});
assert.equal(reviews.length, 1);
const review = reviews[0];
assert.equal(assertSafeVendorRepositoryReview(review), true);
assert.equal(review.repositoryId, 'nvidia-cuda-debian13-x86_64');
assert.equal(review.source.ref, 'vendor-repo:nvidia-cuda-debian13-x86_64');
assert.deepEqual(review.suites, ['./']);
assert.deepEqual(review.components, []);
assert.ok(review.packages.includes('nvidia-driver'));
assert.ok(review.packages.includes('nvidia-open'));
assert.equal(review.keyring.path, '/usr/share/keyrings/nvidia-cuda-archive-keyring.gpg');
assert.equal(review.keyring.fingerprint, '02182E60104FCDC26EAE1B8597A5D4CB8793F200');
assert.equal(review.trustedSource, true);
assert.equal(review.mutationAuthorized, false);
assert.equal(review.automaticEnable, false);
assert.equal(VendorOfficialRepositoryPolicy.flatRepositorySuitesValidated, true);

const clone = () => structuredClone(document);
for (const maliciousSuite of ['../evil', 'stable/../evil', './\nTrusted: yes', 'stable//main', '/absolute']) {
  const attacked = clone();
  attacked.entries[0].suites = [maliciousSuite];
  assert.throws(() => parseVendorOfficialRepositoryPolicy(attacked));
}
const duplicateSuite = clone();
duplicateSuite.entries[0].suites = ['./', './'];
assert.throws(() => parseVendorOfficialRepositoryPolicy(duplicateSuite), error => error?.code === 'POLICY_TOKEN_DUPLICATE');
const badHost = clone();
badHost.entries[0].baseUrl = 'https://example.invalid/compute/cuda/';
assert.throws(() => parseVendorOfficialRepositoryPolicy(badHost), error => error?.code === 'POLICY_URL_HOST_NOT_ALLOWLISTED');
const shortFingerprint = clone();
shortFingerprint.entries[0].keyring.fingerprint = '8793F200';
assert.throws(() => parseVendorOfficialRepositoryPolicy(shortFingerprint), error => error?.code === 'POLICY_KEY_FINGERPRINT_INVALID');
const keyDownload = clone();
keyDownload.entries[0].keyring.downloadUrl = 'https://developer.download.nvidia.com/key';
assert.throws(() => parseVendorOfficialRepositoryPolicy(keyDownload), error => error?.code === 'POLICY_KEY_DOWNLOAD_FORBIDDEN');

console.log(`production vendor policy self-test passed repository=${review.repositoryId} suite=${review.suites[0]} packages=${review.packages.join(',')}`);
