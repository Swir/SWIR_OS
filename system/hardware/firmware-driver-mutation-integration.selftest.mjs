import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  DriverMutationTransactionService,
  FileDriverMutationJournal
} from './driver-mutation-transaction-service.mjs';
import {
  FileFirmwareUpdateJournal,
  FirmwareUpdateTransactionService
} from './firmware-update-transaction-service.mjs';

const candidate = {
  deviceId: '0123456789abcdef0123456789abcdef01234567',
  deviceName: 'Test System Firmware',
  currentVersion: '1.0.0',
  version: '1.2.0',
  releaseId: 'lvfs-release-42',
  remoteId: 'lvfs',
  checksums: ['a'.repeat(64)],
  requiresReboot: true,
  source: { class: 'fwupd-lvfs', repositoryId: 'lvfs', ref: 'fwupd:test:42' },
  trustedSource: true,
  directDownloadUrlExposed: false,
  mutationAuthorized: false
};

const inventory = {
  schema: 'swir.fwupd-lvfs-inventory/0.1',
  available: true,
  readOnly: true,
  mutationCapable: false,
  provider: 'fwupd-lvfs',
  trustedRemoteId: 'lvfs',
  devices: [],
  candidates: [candidate],
  history: [],
  ignoredNonLvfsCandidates: 0,
  probe: { available: true, trustedBinary: true }
};

const inventoryService = { async inventory() { return structuredClone(inventory); } };
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-fwupd-driver-integration-'));
const firmwareJournal = new FileFirmwareUpdateJournal({ root: path.join(temp, 'firmware'), expectedOwnerUid: null, enforceOwnership: false });
const driverJournal = new FileDriverMutationJournal({ root: path.join(temp, 'driver'), expectedOwnerUid: null, enforceOwnership: false });
const commands = [];
const firmwareTransactions = new FirmwareUpdateTransactionService({
  inventoryService,
  journal: firmwareJournal,
  runner: async (binary, args, options) => {
    commands.push({ binary, args: [...args], shell: options.shell });
    return { code: 0, stdout: '{}', stderr: '' };
  },
  idFactory: () => 'firmware-child-0001',
  clock: () => '2026-09-19T08:40:00.000Z',
  enforceBinaryTrust: false
});

const firmwarePlan = await firmwareTransactions.plan(candidate);
const sources = [{ class: 'fwupd-lvfs', ref: 'lvfs', rollback: true }];
const driverPlan = {
  schema: 'swir.driver-plan/0.1',
  generatedAt: '2026-09-19T08:39:00.000Z',
  mode: 'preview',
  readOnly: true,
  autoExecutable: false,
  host: {
    distribution: { id: 'debian', versionId: '13', family: 'debian' },
    fwupdAvailable: true,
    lvfsMetadataPresent: true,
    packageManagers: ['apt'],
    repositoryManagers: ['apt']
  },
  summary: { devices: 1, matched: 1, healthy: 0, attention: 1, operations: 1 },
  operations: [{
    id: 'pci-0000:00:02.0:review-fwupd:1',
    deviceKey: 'pci:0000:00:02.0',
    kind: 'review-fwupd',
    state: 'proposed',
    requiresPrivilege: true,
    reason: 'fwupd candidate',
    sources,
    rollback: 'source-supported',
    capability: 'available'
  }]
};

const parent = new DriverMutationTransactionService({
  packageTransactions: { async execute() { throw new Error('package path must not run'); } },
  firmwareTransactions,
  journal: driverJournal,
  idFactory: () => 'driver-parent-0001',
  clock: () => '2026-09-19T08:41:00.000Z'
});

const result = await parent.execute(
  { driverPlan, operationId: driverPlan.operations[0].id, firmwareCandidate: candidate },
  { actorId: 'uid:1000', plan: firmwarePlan, confirmationDigest: firmwarePlan.digest }
);

assert.equal(result.state, 'staged-reboot-required');
assert.equal(result.child.class, 'firmware');
assert.equal(result.child.transactionId, 'firmware-child-0001');
assert.equal(commands.length, 1);
assert.equal(commands[0].binary, '/usr/bin/fwupdmgr');
assert.equal(commands[0].shell, false);
assert.deepEqual(commands[0].args, ['update', candidate.deviceId, '--assume-yes', '--no-reboot-check', '--no-unreported-check', '--json']);
assert.equal(firmwareJournal.read('firmware-child-0001').state, 'staged-reboot-required');
assert.equal(driverJournal.read('driver-parent-0001').child.transactionId, 'firmware-child-0001');
assert.equal(parent.inspectRecovery()[0].childRecoveryRequired, true);

fs.rmSync(temp, { recursive: true, force: true });
console.log('firmware driver mutation integration self-test: ok');
