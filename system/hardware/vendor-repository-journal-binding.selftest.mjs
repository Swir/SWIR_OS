import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { bindVendorRepositoryTransaction } from './vendor-repository-transaction-binding.mjs';
import { buildDistributionPackagePlan } from '../packages/distribution-package-provider.mjs';
import {
  SystemPackageTransactionService,
  digestPackagePlan
} from '../packages/package-transaction-service.mjs';

const fingerprint = '02182E60104FCDC26EAE1B8597A5D4CB8793F200';
const repositoryId = 'nvidia-cuda-debian13-x86_64';
const review = {
  schema: 'swir.vendor-official-repository-review/0.1',
  repositoryId,
  vendor: 'NVIDIA',
  source: { class: 'vendor-official-repository', ref: `vendor-repo:${repositoryId}` },
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
  repositoryId,
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

const binding = bindVendorRepositoryTransaction({
  review,
  evidence,
  requestedPackages: ['nvidia-open'],
  now: new Date('2026-09-19T01:00:00.000Z')
});
const manifest = binding.packagePlanInputs[0];
const plan = buildDistributionPackagePlan('install', manifest, {
  host: {
    distribution: { id: 'debian', family: 'debian', versionId: '13', architecture: 'x86_64' },
    capabilities: { packageManagers: ['apt'] }
  },
  allowlistedRepositories: [repositoryId]
});

assert.equal(plan.source.repositoryId, repositoryId);
assert.equal(plan.source.upstreamClass, 'vendor-official-repository');
assert.equal(plan.trust.upstreamSourceClass, 'vendor-official-repository');
assert.equal(plan.trust.vendorRepositoryBindingDigest, binding.bindingDigest);
assert.match(plan.trust.vendorRepositoryBindingDigest, /^[a-f0-9]{64}$/);

const events = [];
const dependencies = {
  trustVerifier: {
    async verifyRepository(input) {
      events.push(['trust', input.repositoryId]);
      return { verified: true, proofId: 'vendor-repository-proof-selftest' };
    }
  },
  authorizationBroker: {
    async authorize(input) {
      events.push(['authorize', input.scope, input.planDigest]);
      return { authorized: true, grantId: 'vendor-grant-selftest', actorId: 'user:1000' };
    }
  },
  snapshotProvider: {
    async capture(input) {
      events.push(['snapshot', input.packageName]);
      return {
        schema: 'swir.package-snapshot/0.1',
        capturedAt: '2026-09-19T01:01:00.000Z',
        packageId: input.packageId,
        manager: input.manager,
        packageName: input.packageName,
        installed: false,
        version: null,
        query: { source: 'dpkg-query', exitCode: 1, signal: null }
      };
    }
  },
  executor: {
    async execute(input) {
      events.push(['execute', input.operation, input.planDigest]);
      return { schema: 'swir.package-executor-result/0.1', ok: true, exitCode: 0, operation: input.operation };
    }
  },
  healthVerifier: {
    async verify(input) {
      events.push(['health', input.packageName]);
      return {
        schema: 'swir.package-health/0.1',
        packageId: input.packageId,
        packageName: input.packageName,
        healthy: true,
        checks: [{ id: 'package-present', ok: true }]
      };
    }
  }
};

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-vendor-journal-binding-'));
try {
  let clockTick = 0;
  const service = new SystemPackageTransactionService({
    journalDirectory: root,
    executor: dependencies.executor,
    authorizationBroker: dependencies.authorizationBroker,
    trustVerifier: dependencies.trustVerifier,
    snapshotProvider: dependencies.snapshotProvider,
    healthVerifier: dependencies.healthVerifier,
    allowlistedRepositories: [repositoryId],
    idFactory: () => 'vendor-tx-0001',
    clock: () => `2026-09-19T01:02:${String(clockTick++).padStart(2, '0')}.000Z`
  });

  const result = await service.execute(plan, { reason: 'vendor binding journal self-test' });
  assert.equal(result.state, 'committed');
  assert.equal(result.plan.trust.vendorRepositoryBindingDigest, binding.bindingDigest);
  assert.equal(result.plan.source.upstreamClass, 'vendor-official-repository');
  assert.equal(result.planDigest, digestPackagePlan(result.plan));
  assert.equal(result.trust.repositoryId, repositoryId);
  assert.deepEqual(events.map(event => event[0]), ['trust', 'authorize', 'snapshot', 'execute', 'health']);
  assert.equal(events.find(event => event[0] === 'authorize')[2], result.planDigest);
  assert.equal(events.find(event => event[0] === 'execute')[2], result.planDigest);

  const stored = service.readJournal('vendor-tx-0001');
  assert.equal(stored.plan.trust.vendorRepositoryBindingDigest, binding.bindingDigest);
  assert.equal(stored.planDigest, digestPackagePlan(stored.plan));
  assert.equal(fs.statSync(path.join(root, 'vendor-tx-0001.json')).mode & 0o077, 0);

  const journalPath = path.join(root, 'vendor-tx-0001.json');
  const tampered = JSON.parse(fs.readFileSync(journalPath, 'utf8'));
  tampered.plan.trust.vendorRepositoryBindingDigest = 'd'.repeat(64);
  fs.writeFileSync(journalPath, `${JSON.stringify(tampered, null, 2)}\n`, { mode: 0o600 });
  assert.throws(
    () => service.readJournal('vendor-tx-0001'),
    error => error?.code === 'JOURNAL_PLAN_DIGEST_MISMATCH',
    'tampering with the journaled vendor binding digest must fail closed'
  );
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}

console.log(`vendor repository binding reached package journal digest=${binding.bindingDigest}`);
