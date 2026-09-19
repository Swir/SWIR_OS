import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  FileFirmwareUpdateJournal,
  FirmwareUpdateTransactionPolicy,
  FirmwareUpdateTransactionService
} from './firmware-update-transaction-service.mjs';

const candidate = Object.freeze({
  deviceId: '0123456789abcdef0123456789abcdef01234567',
  deviceName: 'Test System Firmware',
  currentVersion: '1.0.0',
  version: '1.2.0',
  releaseId: 'com.example.firmware-1.2.0',
  remoteId: 'lvfs',
  checksums: ['a'.repeat(64)],
  requiresReboot: true,
  source: { class: 'fwupd-lvfs', repositoryId: 'lvfs', ref: 'fwupd:0123456789abcdef0123456789abcdef01234567:com.example.firmware-1.2.0' },
  trustedSource: true,
  directDownloadUrlExposed: false,
  mutationAuthorized: false
});

function inventoryFor(item = candidate, extras = []) {
  return {
    schema: 'swir.fwupd-lvfs-inventory/0.1',
    available: true,
    readOnly: true,
    mutationCapable: false,
    provider: 'fwupd-lvfs',
    trustedRemoteId: 'lvfs',
    devices: [],
    candidates: [item, ...extras],
    history: [],
    ignoredNonLvfsCandidates: 0,
    probe: { available: true, trustedBinary: true }
  };
}

class SequenceInventory {
  constructor(sequence) { this.sequence = sequence; this.index = 0; }
  async inventory() { return structuredClone(this.sequence[Math.min(this.index++, this.sequence.length - 1)]); }
}

const journalRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-fwupd-journal-'));
const journal = new FileFirmwareUpdateJournal({ root: journalRoot, expectedOwnerUid: null, enforceOwnership: false });
const commands = [];
const runner = async (binary, args, options) => {
  commands.push({ binary, args: [...args], options: { shell: options.shell } });
  return { code: 0, stdout: JSON.stringify({}), stderr: '' };
};
let clockTick = 0;
const clock = () => `2026-09-19T08:2${clockTick++}:00.000Z`;
const service = new FirmwareUpdateTransactionService({
  inventoryService: new SequenceInventory([inventoryFor(), inventoryFor()]),
  runner,
  journal,
  clock,
  idFactory: () => 'fwtx-test-0001',
  enforceBinaryTrust: false
});

const plan = await service.plan(candidate);
assert.equal(plan.schema, 'swir.firmware-update-plan/0.1');
assert.match(plan.digest, /^[a-f0-9]{64}$/);
assert.deepEqual(plan.execution.argv, ['update', candidate.deviceId, '--assume-yes', '--no-reboot-check', '--no-unreported-check', '--json']);
assert.equal(plan.execution.shell, false);
assert.equal(plan.execution.arbitraryFileOrUrlAccepted, false);
assert.equal(plan.automaticReboot, false);
assert.equal(plan.automaticRollback, false);

await assert.rejects(
  service.update(candidate, { plan, confirmationDigest: '0'.repeat(64) }),
  error => error?.code === 'FIRMWARE_CONFIRMATION_REQUIRED'
);
assert.equal(commands.length, 0, 'wrong digest must not invoke fwupdmgr');

const result = await service.update(candidate, { plan, confirmationDigest: plan.digest, actorId: 'selftest' });
assert.equal(result.schema, 'swir.firmware-transaction-result/0.1');
assert.equal(result.status, 'staged-reboot-required');
assert.equal(result.rebootPerformed, false);
assert.equal(commands.length, 1);
assert.equal(commands[0].binary, '/usr/bin/fwupdmgr');
assert.equal(commands[0].options.shell, false);
assert(!commands[0].args.includes('--force'));
assert(!commands[0].args.includes('--allow-older'));
assert(!commands[0].args.includes('--allow-reinstall'));
assert(!commands[0].args.includes('--no-safety-check'));
const persisted = journal.read('fwtx-test-0001');
assert.equal(persisted.state, 'staged-reboot-required');
assert.equal(persisted.planDigest, plan.digest);
assert.equal(persisted.recovery.automaticRollback, false);

const staleCandidate = { ...candidate, version: '1.3.0', checksums: ['b'.repeat(64)] };
const staleService = new FirmwareUpdateTransactionService({
  inventoryService: new SequenceInventory([inventoryFor(candidate), inventoryFor(staleCandidate)]),
  runner: async () => { throw new Error('must not run'); },
  journal: new FileFirmwareUpdateJournal({ root: fs.mkdtempSync(path.join(os.tmpdir(), 'swir-fwupd-stale-')), expectedOwnerUid: null, enforceOwnership: false }),
  clock: () => '2026-09-19T08:30:00.000Z',
  idFactory: () => 'fwtx-stale-0001',
  enforceBinaryTrust: false
});
const stalePlan = await staleService.plan(candidate);
await assert.rejects(
  staleService.update(candidate, { plan: stalePlan, confirmationDigest: stalePlan.digest }),
  error => error?.code === 'FIRMWARE_PLAN_STALE'
);

const ambiguousService = new FirmwareUpdateTransactionService({
  inventoryService: new SequenceInventory([inventoryFor(candidate, [{ ...candidate, releaseId: 'second' }])]),
  runner: async () => ({ code: 0, stdout: '{}', stderr: '' }),
  journal: new FileFirmwareUpdateJournal({ root: fs.mkdtempSync(path.join(os.tmpdir(), 'swir-fwupd-ambiguous-')), expectedOwnerUid: null, enforceOwnership: false }),
  enforceBinaryTrust: false
});
await assert.rejects(ambiguousService.plan(candidate), error => error?.code === 'FIRMWARE_UPDATE_AMBIGUOUS');

assert.equal(FirmwareUpdateTransactionPolicy.arbitraryFirmwareUrlOrFile, false);
assert.equal(FirmwareUpdateTransactionPolicy.noSafetyCheck, false);
assert.equal(FirmwareUpdateTransactionPolicy.automaticReboot, false);
assert.equal(FirmwareUpdateTransactionPolicy.durableJournalBeforeMutation, true);

fs.rmSync(journalRoot, { recursive: true, force: true });
console.log('firmware update transaction self-test: ok');
