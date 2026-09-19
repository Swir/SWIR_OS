import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  FileFirmwareUpdateJournal,
  FirmwareUpdateTransactionService
} from './firmware-update-transaction-service.mjs';
import {
  FirmwareUpdateVerificationPolicy,
  FirmwareUpdateVerificationService
} from './firmware-update-verification-service.mjs';

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

function inventory({
  version = '1.0.0',
  updateError = null,
  includeDevice = true,
  includeCandidate = true,
  includeHistory = false,
  historyState = 2,
  historyError = null,
  historyModified = 1789800000
} = {}) {
  return {
    schema: 'swir.fwupd-lvfs-inventory/0.1',
    available: true,
    readOnly: true,
    mutationCapable: false,
    provider: 'fwupd-lvfs',
    trustedRemoteId: 'lvfs',
    devices: includeDevice ? [{
      deviceId: candidate.deviceId,
      name: candidate.deviceName,
      version,
      updateState: 0,
      updateError
    }] : [],
    candidates: includeCandidate ? [candidate] : [],
    history: includeHistory ? [{
      deviceId: candidate.deviceId,
      name: candidate.deviceName,
      version,
      updateState: historyState,
      updateError: historyError,
      modified: historyModified
    }] : [],
    ignoredNonLvfsCandidates: 0,
    probe: { available: true, trustedBinary: true }
  };
}

class SequenceInventory {
  constructor(sequence) { this.sequence = sequence; this.index = 0; }
  async inventory() { return structuredClone(this.sequence[Math.min(this.index++, this.sequence.length - 1)]); }
}

async function createStagedTransaction({ root, transactionId, verificationInventory }) {
  const journal = new FileFirmwareUpdateJournal({ root, expectedOwnerUid: null, enforceOwnership: false });
  const inventoryService = new SequenceInventory([
    inventory({ version: '1.0.0' }),
    inventory({ version: '1.0.0' }),
    verificationInventory
  ]);
  const transactions = new FirmwareUpdateTransactionService({
    inventoryService,
    journal,
    runner: async () => ({ code: 0, stdout: '{}', stderr: '' }),
    clock: () => '2026-09-19T09:30:00.000Z',
    idFactory: () => transactionId,
    enforceBinaryTrust: false
  });
  const plan = await transactions.plan(candidate);
  const result = await transactions.update(candidate, { plan, confirmationDigest: plan.digest, actorId: 'verification-selftest' });
  assert.equal(result.status, 'staged-reboot-required');
  return { journal, inventoryService, plan };
}

const verifiedRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-fwupd-verify-ok-'));
const verifiedFixture = await createStagedTransaction({
  root: verifiedRoot,
  transactionId: 'fwtx-verify-0001',
  verificationInventory: inventory({ version: '1.2.0', includeCandidate: false, includeHistory: true, historyState: 2 })
});
const verifier = new FirmwareUpdateVerificationService({
  inventoryService: verifiedFixture.inventoryService,
  journal: verifiedFixture.journal,
  clock: () => '2026-09-19T09:31:00.000Z'
});
const verified = await verifier.verify('fwtx-verify-0001');
assert.equal(verified.schema, 'swir.firmware-update-verification/0.1');
assert.equal(verified.status, 'verified');
assert.equal(verified.verified, true);
assert.equal(verified.currentVersion, '1.2.0');
assert.equal(verified.targetVersion, '1.2.0');
assert.equal(verified.historyUpdateState, 2);
assert.equal(verified.historyUpdateError, null);
assert.equal(verified.physicalHardwareQualification, false);
assert.equal(verified.rebootOrPowerCycleProven, false);
const verifiedJournal = verifiedFixture.journal.read('fwtx-verify-0001');
assert.equal(verifiedJournal.state, 'verified');
assert.equal(verifiedJournal.verification.verified, true);
assert.equal(verifiedJournal.recovery.operatorReviewRequired, false);

const pendingRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-fwupd-verify-pending-'));
const pendingFixture = await createStagedTransaction({
  root: pendingRoot,
  transactionId: 'fwtx-pending-0001',
  verificationInventory: inventory({ version: '1.0.0', includeCandidate: false, includeHistory: true, historyState: 2 })
});
const pendingVerifier = new FirmwareUpdateVerificationService({
  inventoryService: pendingFixture.inventoryService,
  journal: pendingFixture.journal,
  clock: () => '2026-09-19T09:32:00.000Z'
});
const pending = await pendingVerifier.verify('fwtx-pending-0001');
assert.equal(pending.status, 'pending-reboot-or-power-cycle');
assert.equal(pending.verified, false);
assert.equal(pending.operatorReviewRequired, true);
assert.equal(pendingFixture.journal.read('fwtx-pending-0001').state, 'staged-reboot-required');

const historyMissingRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-fwupd-verify-history-'));
const historyMissingFixture = await createStagedTransaction({
  root: historyMissingRoot,
  transactionId: 'fwtx-history-0001',
  verificationInventory: inventory({ version: '1.2.0', includeCandidate: false, includeHistory: false })
});
const historyMissingVerifier = new FirmwareUpdateVerificationService({
  inventoryService: historyMissingFixture.inventoryService,
  journal: historyMissingFixture.journal,
  clock: () => '2026-09-19T09:33:00.000Z'
});
const historyPending = await historyMissingVerifier.verify('fwtx-history-0001');
assert.equal(historyPending.status, 'pending-history-verification');
assert.equal(historyPending.verified, false);
assert.equal(historyPending.historyRequired, true);
assert.equal(historyPending.historyPresent, false);

const errorRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-fwupd-verify-error-'));
const errorFixture = await createStagedTransaction({
  root: errorRoot,
  transactionId: 'fwtx-review-0001',
  verificationInventory: inventory({
    version: '1.2.0',
    updateError: null,
    includeCandidate: false,
    includeHistory: true,
    historyState: 3,
    historyError: 'failed to run update on reboot: expected 1.2.0 and got 1.0.0'
  })
});
const errorVerifier = new FirmwareUpdateVerificationService({
  inventoryService: errorFixture.inventoryService,
  journal: errorFixture.journal,
  clock: () => '2026-09-19T09:34:00.000Z'
});
const review = await errorVerifier.verify('fwtx-review-0001');
assert.equal(review.status, 'needs-review');
assert.equal(review.verified, false);
assert.equal(review.deviceUpdateError, null, 'device view intentionally simulates fwupd get-devices hiding the failure');
assert.equal(review.historyUpdateState, 3);
assert.match(review.historyUpdateError, /failed to run update on reboot/);
assert.equal(errorFixture.journal.read('fwtx-review-0001').state, 'staged-reboot-required');

assert.equal(FirmwareUpdateVerificationPolicy.readOnlyHardwareInspection, true);
assert.equal(FirmwareUpdateVerificationPolicy.getDevicesAloneSufficientAfterReboot, false);
assert.equal(FirmwareUpdateVerificationPolicy.historyRequiredForRebootedUpdate, true);
assert.equal(FirmwareUpdateVerificationPolicy.historyFailureBlocksVerification, true);
assert.equal(FirmwareUpdateVerificationPolicy.failedTransactionAutoPromotion, false);
assert.equal(FirmwareUpdateVerificationPolicy.automaticRetry, false);
assert.equal(FirmwareUpdateVerificationPolicy.automaticRollback, false);
assert.equal(FirmwareUpdateVerificationPolicy.physicalHardwareQualification, false);

for (const root of [verifiedRoot, pendingRoot, historyMissingRoot, errorRoot]) fs.rmSync(root, { recursive: true, force: true });
console.log('firmware update verification self-test: ok');
