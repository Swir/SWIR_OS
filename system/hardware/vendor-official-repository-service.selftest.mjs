import assert from 'node:assert/strict';
import {
  VendorOfficialRepositoryPolicy,
  assertSafeVendorRepositoryReview,
  parseVendorOfficialRepositoryPolicy,
  resolveVendorOfficialRepositories
} from './vendor-official-repository-service.mjs';

function fixture(overrides = {}) {
  return {
    schema: 'swir.vendor-official-repository-policy/0.1',
    failClosed: true,
    defaultEnabled: false,
    allowDirectBinaryDownloads: false,
    entries: [{
      id: 'fixture-vendor',
      vendor: 'Fixture Vendor',
      enabled: true,
      sourceClass: 'vendor-official-repository',
      packageManager: 'apt',
      officialHosts: ['packages.vendor.example'],
      baseUrl: 'https://packages.vendor.example/debian/',
      distributions: [{ id: 'debian', versions: ['13'], architectures: ['amd64'] }],
      suites: ['stable'],
      components: ['main'],
      packages: ['fixture-driver'],
      hardwareVendors: ['10DE'],
      keyring: { path: '/usr/share/keyrings/fixture-vendor.gpg', fingerprint: '0123456789ABCDEF0123456789ABCDEF01234567' },
      directBinaryDownloads: false,
      automaticEnable: false,
      arbitraryPackages: false,
      ...overrides
    }]
  };
}

const policy = parseVendorOfficialRepositoryPolicy(fixture());
assert.equal(policy.entries.length, 1);
assert.equal(policy.entries[0].hardwareVendors[0], '10de');
assert.equal(VendorOfficialRepositoryPolicy.productionNetworkFetchImplemented, false);

const matches = resolveVendorOfficialRepositories(policy, {
  hardwareVendor: '10de', distributionId: 'debian', versionId: '13', architecture: 'amd64'
});
assert.equal(matches.length, 1);
assertSafeVendorRepositoryReview(matches[0]);
assert.equal(matches[0].mutationAuthorized, false);
assert.equal(matches[0].directBinaryDownloads, false);
assert.deepEqual(matches[0].packages, ['fixture-driver']);

assert.equal(resolveVendorOfficialRepositories(policy, {
  hardwareVendor: '1002', distributionId: 'debian', versionId: '13', architecture: 'amd64'
}).length, 0);
assert.equal(resolveVendorOfficialRepositories(policy, {
  hardwareVendor: '10de', distributionId: 'debian', versionId: '12', architecture: 'amd64'
}).length, 0);

for (const [name, override] of [
  ['http URL', { baseUrl: 'http://packages.vendor.example/debian/' }],
  ['foreign host', { baseUrl: 'https://evil.example/debian/' }],
  ['direct downloads', { directBinaryDownloads: true }],
  ['automatic enable', { automaticEnable: true }],
  ['arbitrary packages', { arbitraryPackages: true }],
  ['key download', { keyring: { path: '/usr/share/keyrings/fixture-vendor.gpg', fingerprint: '0123456789ABCDEF0123456789ABCDEF01234567', keyUrl: 'https://packages.vendor.example/key.gpg' } }],
  ['unsafe keyring', { keyring: { path: '/tmp/vendor.gpg', fingerprint: '0123456789ABCDEF0123456789ABCDEF01234567' } }],
  ['wildcard package', { packages: ['*'] }]
]) {
  assert.throws(() => parseVendorOfficialRepositoryPolicy(fixture(override)), undefined, name);
}

const duplicate = fixture();
duplicate.entries.push(structuredClone(duplicate.entries[0]));
assert.throws(() => parseVendorOfficialRepositoryPolicy(duplicate));

console.log('SWIR vendor official repository policy self-test: OK');
