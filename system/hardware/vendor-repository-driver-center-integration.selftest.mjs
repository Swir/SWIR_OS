import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { bindVendorRepositoryTransaction } from './vendor-repository-transaction-binding.mjs';
import {
  FileVendorRepositoryActivationJournal,
  FileVendorRepositorySourceStore,
  VendorRepositoryActivationTransactionService
} from './vendor-repository-activation-transaction-service.mjs';
import {
  createVendorRepositoryActivationReview,
  assertVendorRepositoryActivationReview,
  DriverCenterVendorRepositoryCoordinator,
  DriverCenterVendorRepositoryPolicy
} from './vendor-repository-driver-center-integration.mjs';

const fingerprint = '02182E60104FCDC26EAE1B8597A5D4CB8793F200';
const repositoryId = 'nvidia-cuda-debian13-x86_64';
const review = {
  schema: 'swir.vendor-official-repository-review/0.1', repositoryId, vendor: 'NVIDIA',
  source: { class: 'vendor-official-repository', ref: `vendor-repo:${repositoryId}` }, packageManager: 'apt',
  baseUrl: 'https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/', suites: ['./'], components: [],
  packages: ['cuda-keyring', 'nvidia-open'], keyring: { path: '/usr/share/keyrings/nvidia-cuda-archive-keyring.gpg', fingerprint },
  hardwareVendor: '10de', distribution: { id: 'debian', versionId: '13', architecture: 'x86_64' }, trustedSource: true,
  directBinaryDownloads: false, mutationAuthorized: false, automaticEnable: false
};
const evidence = {
  schema: 'swir.vendor-repository-evidence/0.1', qualificationOnly: true, authorizesMutation: false, authorizesRepositoryEnablement: false,
  profileId: 'nvidia-debian13-amd64', repositoryId, vendor: 'NVIDIA', hardwareVendor: '10de',
  distribution: { id: 'debian', versionId: '13', architecture: 'x86_64' },
  source: { origin: 'https://developer.download.nvidia.com', basePath: '/compute/cuda/repos/debian13/x86_64/' },
  key: { fingerprint, expectedFingerprint: fingerprint, sha256: 'a'.repeat(64) },
  inRelease: { validSignaturePrimaryFingerprint: fingerprint, freshnessVerified: true, signedAt: '2026-09-18T00:00:00.000Z', effectiveValidUntil: '2026-09-30T00:00:00.000Z', checkedAt: '2026-09-19T00:00:00.000Z', sha256: 'b'.repeat(64) },
  packages: { verified: ['cuda-keyring', 'nvidia-open'], indexSha256: 'c'.repeat(64) }
};
const binding = bindVendorRepositoryTransaction({ review, evidence, requestedPackages: ['nvidia-open'], now: new Date('2026-09-19T01:00:00.000Z') });

const operationId = 'pci:0000:01:00.0:review-package:1';
const driverPlan = {
  schema: 'swir.driver-plan/0.1', generatedAt: '2026-09-19T02:00:00.000Z', mode: 'preview', readOnly: true, autoExecutable: false,
  host: { distribution: { id: 'debian', versionId: '13', family: 'debian' }, fwupdAvailable: true, lvfsMetadataPresent: true, packageManagers: ['apt'], repositoryManagers: ['apt'] },
  summary: { devices: 1, matched: 1, healthy: 0, attention: 1, operations: 1 },
  operations: [{
    id: operationId, deviceKey: 'pci:0000:01:00.0', kind: 'review-package', state: 'proposed', requiresPrivilege: true,
    reason: 'Verified NVIDIA package candidate requires explicit vendor repository activation review.',
    sources: [{
      class: 'vendor-official-repository', ref: `vendor:${repositoryId}`, repositoryId, rollback: true,
      verification: { schema: binding.schema, bindingDigest: binding.bindingDigest, evidenceValidUntil: binding.bound.metadata.effectiveValidUntil, packages: [...binding.bound.packages] }
    }],
    rollback: 'source-supported', packageManager: 'apt', packageCandidates: ['nvidia-driver', 'nvidia-open']
  }]
};

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-driver-center-vendor-'));
const sourceRoot = path.join(root, 'sources.list.d');
const journalRoot = path.join(root, 'journal');
fs.mkdirSync(sourceRoot, { recursive: true, mode: 0o755 });
const driverReview = createVendorRepositoryActivationReview({
  driverPlan, operationId, vendorRepositoryBindings: [binding], sourceRoot, now: new Date('2026-09-19T02:00:00.000Z')
});
assert.equal(assertVendorRepositoryActivationReview(driverReview, { sourceRoot, now: new Date('2026-09-19T02:00:00.000Z') }), true);
assert.equal(driverReview.vendor.bindingDigest, binding.bindingDigest);
assert.equal(driverReview.vendor.repositoryId, repositoryId);
assert.deepEqual(driverReview.operation.packages, ['nvidia-open']);
assert.equal(driverReview.packageMutationDeferred, true);
assert.equal(driverReview.directAptMutationAllowed, false);
assert.equal(driverReview.activationPlan.repositoryEnablementAuthorized, false);

const calls = [];
const activationService = new VendorRepositoryActivationTransactionService({
  journal: new FileVendorRepositoryActivationJournal({ root: journalRoot, enforceOwnership: false }),
  sourceStore: new FileVendorRepositorySourceStore({ root: sourceRoot, enforceOwnership: false }),
  allowedSourceRoot: sourceRoot,
  enforceRoot: false,
  keyringVerifier: { verify(keyring) { assert.equal(keyring.fingerprint, fingerprint); return { verified: true, fingerprint }; } },
  authorizationBroker: { async authorize(request) { calls.push(request.schema); return { authorized: true, authorizationId: `auth-${calls.length}` }; } },
  executor: { async run(argv) { calls.push(argv[0]); return { exitCode: 0, signal: null }; } },
  clock: () => '2026-09-19T03:00:00.000Z',
  idFactory: () => 'vendor-dc-0001'
});
const coordinator = new DriverCenterVendorRepositoryCoordinator({ activationService });
await assert.rejects(
  () => coordinator.activate(driverReview, { sourceRoot, now: new Date('2026-09-19T02:00:00.000Z'), confirmationDigest: '0'.repeat(64) }),
  error => error?.code === 'VENDOR_CONFIRMATION_MISMATCH'
);
const committed = await coordinator.activate(driverReview, {
  sourceRoot, now: new Date('2026-09-19T02:00:00.000Z'), actorId: 'driver-center-test', confirmationDigest: driverReview.activationPlan.activationDigest
});
assert.equal(committed.state, 'committed');
assert.equal(fs.readFileSync(driverReview.activationPlan.source.path, 'utf8'), driverReview.activationPlan.source.content);
assert.equal(activationService.inspectRecovery().length, 0);

const deactivated = await coordinator.deactivate('vendor-dc-0001', driverReview, {
  sourceRoot, now: new Date('2026-09-19T02:00:00.000Z'), actorId: 'driver-center-test', confirmationDigest: driverReview.activationPlan.activationDigest
});
assert.equal(deactivated.state, 'rolled-back');
assert.equal(deactivated.result.explicitDeactivation, true);
assert.equal(fs.existsSync(driverReview.activationPlan.source.path), false);
assert.equal(activationService.inspectRecovery().length, 0);
assert.ok(calls.includes('swir.vendor-repository-activation-authorization-request/0.1'));
assert.ok(calls.includes('swir.vendor-repository-deactivation-authorization-request/0.1'));
assert.ok(calls.includes('apt-get'));

const tamperedPlan = structuredClone(driverPlan);
tamperedPlan.operations[0].sources[0].verification.bindingDigest = 'f'.repeat(64);
assert.throws(
  () => createVendorRepositoryActivationReview({ driverPlan: tamperedPlan, operationId, vendorRepositoryBindings: [binding], sourceRoot, now: new Date('2026-09-19T02:00:00.000Z') }),
  error => error?.code === 'VENDOR_BINDING_NOT_UNIQUE'
);
const wrongOperation = structuredClone(driverPlan);
wrongOperation.operations[0].kind = 'review-module';
assert.throws(
  () => createVendorRepositoryActivationReview({ driverPlan: wrongOperation, operationId, vendorRepositoryBindings: [binding], sourceRoot, now: new Date('2026-09-19T02:00:00.000Z') }),
  error => error?.code === 'VENDOR_OPERATION_KIND_INVALID'
);
assert.equal(DriverCenterVendorRepositoryPolicy.exactFreshBindingRequired, true);
assert.equal(DriverCenterVendorRepositoryPolicy.existingJournaledActivationServiceRequired, true);
assert.equal(DriverCenterVendorRepositoryPolicy.directAptMutationAllowed, false);
assert.equal(DriverCenterVendorRepositoryPolicy.automaticEnablement, false);
console.log(`driver-center vendor repository integration self-test passed binding=${binding.bindingDigest}`);
