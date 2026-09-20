import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  FileFirmwarePhysicalQualificationJournal,
  FirmwarePhysicalQualificationPolicy,
  FirmwarePhysicalQualificationService,
  evaluatePhysicalQualificationEvidence
} from './firmware-physical-qualification-service.mjs';

const PLAN_DIGEST = 'a'.repeat(64);
const MACHINE_HASH = 'b'.repeat(64);
const BOOT_A = '11111111-1111-4111-8111-111111111111';
const BOOT_B = '22222222-2222-4222-8222-222222222222';
const DEVICE_ID = 'device-0001';

const candidate = Object.freeze({
  deviceId: DEVICE_ID,
  deviceName: 'Fixture firmware device',
  currentVersion: '1.0.0',
  version: '1.1.0',
  releaseId: 'release-1',
  remoteId: 'lvfs',
  checksums: ['c'.repeat(64)],
  requiresReboot: true,
  source: { class: 'fwupd-lvfs', repositoryId: 'lvfs', ref: `fwupd:${DEVICE_ID}:release-1` },
  trustedSource: true,
  directDownloadUrlExposed: false,
  mutationAuthorized: false
});

const plan = Object.freeze({
  schema: 'swir.firmware-update-plan/0.1',
  generatedAt: '2026-09-20T00:00:00.000Z',
  provider: 'fwupd-lvfs',
  remoteId: 'lvfs',
  binding: {
    deviceId: DEVICE_ID,
    deviceName: candidate.deviceName,
    currentVersion: candidate.currentVersion,
    targetVersion: candidate.version,
    releaseId: candidate.releaseId,
    remoteId: 'lvfs',
    checksums: candidate.checksums,
    requiresReboot: true,
    sourceRef: candidate.source.ref
  },
  execution: {
    binary: '/usr/bin/fwupdmgr',
    argv: ['update', DEVICE_ID, '--assume-yes', '--no-reboot-check', '--no-unreported-check', '--json'],
    shell: false,
    arbitraryFileOrUrlAccepted: false,
    allowReinstall: false,
    allowOlder: false,
    force: false
  },
  reviewRequired: true,
  explicitDigestConfirmationRequired: true,
  revalidateImmediatelyBeforeMutation: true,
  journalRequired: true,
  automaticReboot: false,
  automaticRollback: false,
  recovery: 'operator-review-after-ambiguous-failure',
  digest: PLAN_DIGEST
});

function host(bootId = BOOT_A, evidenceSource = 'physical-host', virtualizationHintDetected = false) {
  return {
    schema: 'swir.firmware-qualification-host/0.1',
    capturedAt: '2026-09-20T00:00:00.000Z',
    evidenceSource,
    machineIdHash: MACHINE_HASH,
    bootId,
    virtualizationHint: virtualizationHintDetected ? 'qemu' : null,
    virtualizationHintDetected,
    physicalityProvenBySoftware: false,
    rawMachineIdPersisted: false
  };
}

class MemoryJournal {
  constructor() { this.entries = new Map(); }
  write(entry) { this.entries.set(entry.qualificationId, structuredClone(entry)); }
  read(id) {
    const value = this.entries.get(id);
    if (!value) throw new Error(`missing fixture ${id}`);
    return structuredClone(value);
  }
  list() { return [...this.entries.values()].map(structuredClone); }
  force(id, mutator) {
    const current = this.read(id);
    const next = mutator(current);
    this.write(next);
    return next;
  }
}

class MutableHostProbe {
  constructor(initial = host()) { this.value = structuredClone(initial); }
  set(value) { this.value = structuredClone(value); }
  async capture() { return structuredClone(this.value); }
}

class FakeTransactionService {
  constructor() { this.updateCalls = []; }
  async plan(received) {
    assert.equal(received.deviceId, DEVICE_ID);
    return structuredClone(plan);
  }
  async update(received, context) {
    this.updateCalls.push({ received: structuredClone(received), context: structuredClone(context) });
    return {
      schema: 'swir.firmware-transaction-result/0.1',
      transactionId: 'transaction-0001',
      status: 'staged-reboot-required',
      deviceId: DEVICE_ID,
      fromVersion: '1.0.0',
      targetVersion: '1.1.0',
      planDigest: PLAN_DIGEST,
      rebootRequired: true,
      rebootPerformed: false,
      automaticRollback: false,
      verificationRequired: true
    };
  }
}

class FakeVerificationService {
  constructor() { this.calls = []; }
  async verify(transactionId) {
    this.calls.push(transactionId);
    return {
      schema: 'swir.firmware-update-verification/0.1',
      transactionId,
      checkedAt: '2026-09-20T00:10:00.000Z',
      status: 'verified',
      verified: true,
      devicePresent: true,
      historyPresent: true,
      historyRequired: true,
      deviceId: DEVICE_ID,
      fromVersion: '1.0.0',
      targetVersion: '1.1.0',
      currentVersion: '1.1.0',
      deviceUpdateState: 2,
      deviceUpdateError: null,
      historyUpdateState: 2,
      historyUpdateError: null,
      planDigest: PLAN_DIGEST,
      sourceTransactionState: 'verified',
      automaticRollback: false,
      rebootOrPowerCycleProven: false,
      physicalHardwareQualification: false,
      operatorReviewRequired: false
    };
  }
}

function makeService({ probe = new MutableHostProbe(), journal = new MemoryJournal() } = {}) {
  const transactions = new FakeTransactionService();
  const verification = new FakeVerificationService();
  let id = 0;
  const service = new FirmwarePhysicalQualificationService({
    transactionService: transactions,
    verificationService: verification,
    hostProbe: probe,
    journal,
    clock: () => '2026-09-20T00:00:00.000Z',
    idFactory: () => `qualification-${String(++id).padStart(4, '0')}`
  });
  return { service, probe, journal, transactions, verification };
}

async function expectReject(promise, code) {
  await assert.rejects(promise, error => {
    assert.equal(error?.code, code);
    return true;
  });
}

assert.equal(FirmwarePhysicalQualificationPolicy.ciEvidenceCountsAsPhysicalQualification, false);
assert.equal(FirmwarePhysicalQualificationPolicy.interactiveApplyRequired, true);
assert.equal(FirmwarePhysicalQualificationPolicy.interactiveFinalizeRequired, true);
assert.equal(FirmwarePhysicalQualificationPolicy.autoReboot, false);
assert.equal(FirmwarePhysicalQualificationPolicy.autoRollback, false);

const fixture = makeService();
const prepared = await fixture.service.prepare(candidate, { actorId: 'tester' });
assert.equal(prepared.state, 'prepared');
assert.equal(prepared.physicalHardwareQualification, false);
assert.equal(prepared.planDigest, PLAN_DIGEST);
assert.equal(prepared.hostBefore.machineIdHash, MACHINE_HASH);
assert.equal(prepared.expectedApplyPhrase, `APPLY ${DEVICE_ID} ${PLAN_DIGEST}`);
assert.equal(prepared.policy.ciEvidenceCountsAsPhysicalQualification, false);

await expectReject(fixture.service.apply(prepared.qualificationId, {
  interactive: false,
  operatorPresent: true,
  physicalDedicatedHardware: true,
  confirmationDigest: PLAN_DIGEST,
  typedPhrase: prepared.expectedApplyPhrase
}), 'QUALIFICATION_INTERACTIVE_APPLY_REQUIRED');
await expectReject(fixture.service.apply(prepared.qualificationId, {
  interactive: true,
  operatorPresent: false,
  physicalDedicatedHardware: true,
  confirmationDigest: PLAN_DIGEST,
  typedPhrase: prepared.expectedApplyPhrase
}), 'QUALIFICATION_OPERATOR_REQUIRED');
await expectReject(fixture.service.apply(prepared.qualificationId, {
  interactive: true,
  operatorPresent: true,
  physicalDedicatedHardware: false,
  confirmationDigest: PLAN_DIGEST,
  typedPhrase: prepared.expectedApplyPhrase
}), 'QUALIFICATION_DEDICATED_HARDWARE_REQUIRED');
await expectReject(fixture.service.apply(prepared.qualificationId, {
  interactive: true,
  operatorPresent: true,
  physicalDedicatedHardware: true,
  confirmationDigest: 'd'.repeat(64),
  typedPhrase: prepared.expectedApplyPhrase
}), 'QUALIFICATION_CONFIRMATION_DIGEST_INVALID');
await expectReject(fixture.service.apply(prepared.qualificationId, {
  interactive: true,
  operatorPresent: true,
  physicalDedicatedHardware: true,
  confirmationDigest: PLAN_DIGEST,
  typedPhrase: 'WRONG'
}), 'QUALIFICATION_APPLY_PHRASE_INVALID');
assert.equal(fixture.transactions.updateCalls.length, 0);

const rebootedBeforeApply = makeService();
const stalePrepared = await rebootedBeforeApply.service.prepare(candidate);
rebootedBeforeApply.probe.set(host(BOOT_B));
await expectReject(rebootedBeforeApply.service.apply(stalePrepared.qualificationId, {
  interactive: true,
  operatorPresent: true,
  physicalDedicatedHardware: true,
  confirmationDigest: PLAN_DIGEST,
  typedPhrase: stalePrepared.expectedApplyPhrase
}), 'QUALIFICATION_BOOT_CHANGED_BEFORE_APPLY');
assert.equal(rebootedBeforeApply.transactions.updateCalls.length, 0);

const virtualized = makeService();
const virtualPrepared = await virtualized.service.prepare(candidate);
virtualized.probe.set(host(BOOT_A, 'physical-host', true));
await expectReject(virtualized.service.apply(virtualPrepared.qualificationId, {
  interactive: true,
  operatorPresent: true,
  physicalDedicatedHardware: true,
  confirmationDigest: PLAN_DIGEST,
  typedPhrase: virtualPrepared.expectedApplyPhrase
}), 'QUALIFICATION_VIRTUALIZATION_HINT');
assert.equal(virtualized.transactions.updateCalls.length, 0);

const applied = await fixture.service.apply(prepared.qualificationId, {
  interactive: true,
  operatorPresent: true,
  physicalDedicatedHardware: true,
  confirmationDigest: PLAN_DIGEST,
  typedPhrase: prepared.expectedApplyPhrase,
  actorId: 'tester'
});
assert.equal(applied.state, 'applied-verification-required');
assert.equal(applied.transactionId, 'transaction-0001');
assert.equal(applied.physicalHardwareQualification, false);
assert.equal(fixture.transactions.updateCalls.length, 1);
assert.equal(fixture.transactions.updateCalls[0].context.confirmationDigest, PLAN_DIGEST);

const sameBootVerification = await fixture.service.verify(prepared.qualificationId);
assert.equal(sameBootVerification.verification.verified, true);
assert.equal(sameBootVerification.assessment.requiredRebootObserved, false);
assert.equal(sameBootVerification.assessment.eligible, false);
assert.equal(sameBootVerification.state, 'verification-pending');
assert.equal(sameBootVerification.physicalHardwareQualification, false);

fixture.probe.set(host(BOOT_B));
const postReboot = await fixture.service.verify(prepared.qualificationId);
assert.equal(postReboot.assessment.requiredRebootObserved, true);
assert.equal(postReboot.assessment.eligible, true);
assert.equal(postReboot.state, 'ready-for-finalize');
assert.equal(postReboot.physicalHardwareQualification, false);

const directAssessment = evaluatePhysicalQualificationEvidence(postReboot);
assert.equal(directAssessment.softwareVerified, true);
assert.equal(directAssessment.physicalityProvenBySoftware, false);
assert.equal(directAssessment.operatorFinalizationRequired, true);

fixture.journal.force(prepared.qualificationId, current => ({
  ...current,
  hostBefore: { ...current.hostBefore, evidenceSource: 'ci-fixture' }
}));
await expectReject(fixture.service.finalize(prepared.qualificationId, {
  interactive: true,
  operatorPresent: true,
  physicalHardwareObserved: true,
  dedicatedHardware: true,
  recoveryReviewed: true,
  typedPhrase: postReboot.expectedFinalizePhrase,
  actorId: 'tester'
}), 'QUALIFICATION_FIXTURE_EVIDENCE_FORBIDDEN');
assert.equal(fixture.journal.read(prepared.qualificationId).physicalHardwareQualification, false);

fixture.journal.force(prepared.qualificationId, current => ({
  ...current,
  hostBefore: host(BOOT_A),
  hostAfter: host(BOOT_B),
  assessment: evaluatePhysicalQualificationEvidence({ ...current, hostBefore: host(BOOT_A), hostAfter: host(BOOT_B) })
}));
const restored = fixture.service.status(prepared.qualificationId);
const finalized = await fixture.service.finalize(prepared.qualificationId, {
  interactive: true,
  operatorPresent: true,
  physicalHardwareObserved: true,
  dedicatedHardware: true,
  recoveryReviewed: true,
  typedPhrase: restored.expectedFinalizePhrase,
  actorId: 'tester'
});
assert.equal(finalized.state, 'qualified');
assert.equal(finalized.physicalHardwareQualification, true);
assert.equal(finalized.operatorAttestation.physicalHardwareObserved, true);

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-firmware-qualification-'));
try {
  const root = path.join(temp, 'journal');
  const fileJournal = new FileFirmwarePhysicalQualificationJournal({ root, expectedOwnerUid: null, enforceOwnership: false });
  fileJournal.write(finalized);
  const persisted = fileJournal.read(finalized.qualificationId);
  assert.equal(persisted.physicalHardwareQualification, true);
  assert.equal(fs.statSync(root).mode & 0o777, 0o700);
  const persistedFile = path.join(root, `${finalized.qualificationId}.json`);
  assert.equal(fs.statSync(persistedFile).mode & 0o777, 0o600);
  fs.chmodSync(persistedFile, 0o644);
  assert.throws(() => fileJournal.read(finalized.qualificationId), error => error?.code === 'QUALIFICATION_FILE_UNSAFE');
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}

console.log('firmware physical qualification self-test: ok');