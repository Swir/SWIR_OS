import assert from 'node:assert/strict';
import fs from 'node:fs/promises';
import os from 'node:os';
import path from 'node:path';
import {
  DriverMutationTransactionPolicy,
  DriverMutationTransactionService,
  FileDriverMutationJournal
} from './driver-mutation-transaction-service.mjs';

const temp = await fs.mkdtemp(path.join(os.tmpdir(), 'swir-driver-mutation-'));
const journal = new FileDriverMutationJournal({ root: path.join(temp, 'journal'), expectedOwnerUid: null, enforceOwnership: false });

const sources = [
  { class: 'distribution-repository', ref: 'debian:main', rollback: false },
  { class: 'fwupd-lvfs', ref: 'lvfs', rollback: true }
];
const driverPlan = {
  schema: 'swir.driver-plan/0.1', generatedAt: '2026-09-17T17:30:00.000Z', mode: 'preview', readOnly: true, autoExecutable: false,
  host: { distribution: { id: 'debian', versionId: '13', family: 'debian' }, fwupdAvailable: true, lvfsMetadataPresent: true, packageManagers: ['apt'], repositoryManagers: ['apt'] },
  summary: { devices: 1, matched: 1, healthy: 0, attention: 1, operations: 3 },
  operations: [
    { id: 'pci-0000:00:02.0:review-package:1', deviceKey: 'pci:0000:00:02.0', kind: 'review-package', state: 'proposed', requiresPrivilege: true, reason: 'driver package candidate', sources, rollback: 'source-supported', packageManager: 'apt', packageCandidates: ['firmware-linux'] },
    { id: 'pci-0000:00:02.0:review-fwupd:2', deviceKey: 'pci:0000:00:02.0', kind: 'review-fwupd', state: 'proposed', requiresPrivilege: true, reason: 'fwupd candidate', sources, rollback: 'source-supported', capability: 'available' },
    { id: 'pci-0000:00:02.0:review-module:3', deviceKey: 'pci:0000:00:02.0', kind: 'review-module', state: 'proposed', requiresPrivilege: true, reason: 'module review only', sources, rollback: 'source-supported', moduleCandidates: ['i915'] }
  ]
};

const packagePlan = {
  schema: 'swir.system-package-plan/0.1', mode: 'preview', readOnly: true, autoExecutable: false, provider: 'swir.package.system', executionClass: 'linux-native', operation: 'install',
  package: { id: 'org.swir.driver.intel', sourceRef: 'firmware-linux', nativeEntryPoint: null },
  host: { packageManager: 'apt', availablePackageManagers: ['apt'], distribution: { id: 'debian', versionId: '13' } },
  source: { class: 'distribution-repository', repositoryId: 'debian-main' },
  trust: { signatureVerificationRequired: true, arbitraryRepositoryUrlAllowed: false },
  transaction: { requiresPrivilege: true, journalRequired: true, healthCheckRequired: false, rollback: { supported: false, mechanism: 'manual-package-recovery' } },
  commandPreview: ['apt-get', 'install', '--', 'firmware-linux']
};

const firmwareCandidate = {
  deviceId: '0123456789abcdef0123456789abcdef01234567', currentVersion: '1.0.0', version: '2.0.0', releaseId: 'lvfs-release-42', remoteId: 'lvfs',
  checksums: ['a'.repeat(64)], requiresReboot: true, source: { class: 'fwupd-lvfs', repositoryId: 'lvfs', ref: 'fwupd:test:42' },
  trustedSource: true, directDownloadUrlExposed: false, mutationAuthorized: false
};

const packageCalls = [];
const firmwareCalls = [];
const packageTransactions = {
  async execute(plan, context) {
    packageCalls.push({ plan, context });
    return { schema: 'swir.system-package-transaction/0.1', id: 'package-child-0001', state: 'committed' };
  }
};
const firmwareTransactions = {
  async update(candidate, context) {
    firmwareCalls.push({ candidate, context });
    return { schema: 'swir.firmware-transaction-result/0.1', transactionId: 'firmware-child-0001', status: 'staged-reboot-required' };
  }
};

let id = 0;
const service = new DriverMutationTransactionService({
  packageTransactions, firmwareTransactions, journal,
  idFactory: () => `driver-tx-000${++id}`,
  clock: (() => { let tick = 0; return () => `2026-09-17T17:31:${String(tick++).padStart(2, '0')}.000Z`; })()
});

const packageResult = await service.execute({ driverPlan, operationId: driverPlan.operations[0].id, packagePlan }, { actorId: 'uid:1000' });
assert.equal(packageResult.state, 'committed');
assert.equal(packageResult.child.class, 'package');
assert.equal(packageResult.child.transactionId, 'package-child-0001');
assert.equal(packageCalls.length, 1);
assert.equal(journal.read(packageResult.transactionId).request.binding.packageName, 'firmware-linux');

const firmwareResult = await service.execute({ driverPlan, operationId: driverPlan.operations[1].id, firmwareCandidate }, { actorId: 'uid:1000' });
assert.equal(firmwareResult.state, 'staged-reboot-required');
assert.equal(firmwareResult.child.class, 'firmware');
assert.equal(firmwareCalls.length, 1);
const assessments = service.inspectRecovery();
assert.equal(assessments.length, 1);
assert.equal(assessments[0].transactionId, firmwareResult.transactionId);
assert.equal(assessments[0].childRecoveryRequired, true);
assert.equal(assessments[0].automaticMutation, false);

await assert.rejects(
  () => service.execute({ driverPlan, operationId: driverPlan.operations[2].id }, { actorId: 'uid:1000' }),
  error => error.code === 'DRIVER_OPERATION_UNSUPPORTED'
);
await assert.rejects(
  () => service.execute({ driverPlan, operationId: driverPlan.operations[0].id, packagePlan: { ...packagePlan, package: { ...packagePlan.package, sourceRef: 'evil-driver' }, commandPreview: ['apt-get', 'install', '--', 'evil-driver'] } }),
  error => error.code === 'DRIVER_PACKAGE_BINDING_MISMATCH'
);
await assert.rejects(
  () => service.execute({ driverPlan, operationId: driverPlan.operations[1].id, firmwareCandidate: { ...firmwareCandidate, remoteId: 'random-site' } }),
  error => error.code === 'DRIVER_FIRMWARE_SOURCE_UNTRUSTED'
);

const failedJournal = new FileDriverMutationJournal({ root: path.join(temp, 'failed'), expectedOwnerUid: null, enforceOwnership: false });
const failing = new DriverMutationTransactionService({
  packageTransactions: { async execute() { const error = new Error('mutation failed'); error.code = 'PACKAGE_MUTATION_FAILED'; throw error; } },
  firmwareTransactions,
  journal: failedJournal,
  idFactory: () => 'driver-tx-failed',
  clock: () => '2026-09-17T17:40:00.000Z'
});
await assert.rejects(() => failing.execute({ driverPlan, operationId: driverPlan.operations[0].id, packagePlan }), error => error.code === 'PACKAGE_MUTATION_FAILED');
const failed = failedJournal.read('driver-tx-failed');
assert.equal(failed.state, 'failed-needs-recovery');
assert.equal(failed.recovery.operatorReviewRequired, true);
assert.equal(failing.inspectRecovery()[0].route, 'system-package-transaction');

const fileMode = (await fs.stat(path.join(temp, 'journal', `${packageResult.transactionId}.json`))).mode;
assert.equal(fileMode & 0o077, 0);
assert.equal(DriverMutationTransactionPolicy.directKernelModuleMutation, false);
assert.equal(DriverMutationTransactionPolicy.arbitraryDriverDownloads, false);
assert.equal(DriverMutationTransactionPolicy.windowsKernelDriversAsLinuxDrivers, false);
assert.equal(DriverMutationTransactionPolicy.parentJournalBeforeDelegation, true);
assert.equal(DriverMutationTransactionPolicy.childJournalRequired, true);
assert.equal(DriverMutationTransactionPolicy.automaticMutation, false);

await fs.rm(temp, { recursive: true, force: true });
console.log('driver mutation transaction service self-test: OK');
