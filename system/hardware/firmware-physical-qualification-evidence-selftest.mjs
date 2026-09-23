import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  FirmwarePhysicalQualificationEvidencePolicy,
  canonicalEvidenceJson,
  createPhysicalQualificationEvidenceBundle,
  readPhysicalQualificationEvidenceFile,
  verifyPhysicalQualificationEvidenceBundle,
  writePhysicalQualificationEvidenceFile
} from './firmware-physical-qualification-evidence.mjs';

const PLAN_DIGEST = 'a'.repeat(64);
const MACHINE_HASH = 'b'.repeat(64);
const DEVICE_ID = 'device-0001';
const TRANSACTION_ID = 'transaction-0001';
const QUALIFICATION_ID = 'qualification-0001';
const BOOT_A = '11111111-1111-4111-8111-111111111111';
const BOOT_B = '22222222-2222-4222-8222-222222222222';

function sha256(value) {
  return crypto.createHash('sha256').update(String(value), 'utf8').digest('hex');
}

function qualifiedSession() {
  return {
    schema: 'swir.firmware-physical-qualification/0.1',
    qualificationId: QUALIFICATION_ID,
    state: 'qualified',
    createdAt: '2026-09-20T00:00:00.000Z',
    updatedAt: '2026-09-20T00:10:00.000Z',
    plan: {
      schema: 'swir.firmware-update-plan/0.1',
      binding: {
        deviceId: DEVICE_ID,
        deviceName: 'Fixture firmware device',
        currentVersion: '1.0.0',
        targetVersion: '1.1.0',
        releaseId: 'release-1',
        remoteId: 'lvfs',
        checksums: ['c'.repeat(64)],
        requiresReboot: true,
        sourceRef: `fwupd:${DEVICE_ID}:release-1`
      },
      reviewRequired: true,
      explicitDigestConfirmationRequired: true,
      automaticReboot: false,
      automaticRollback: false,
      digest: PLAN_DIGEST
    },
    planDigest: PLAN_DIGEST,
    hostBefore: {
      schema: 'swir.firmware-qualification-host/0.1',
      evidenceSource: 'physical-host',
      machineIdHash: MACHINE_HASH,
      bootId: BOOT_A,
      virtualizationHint: null,
      virtualizationHintDetected: false,
      physicalityProvenBySoftware: false,
      rawMachineIdPersisted: false
    },
    hostAfter: {
      schema: 'swir.firmware-qualification-host/0.1',
      evidenceSource: 'physical-host',
      machineIdHash: MACHINE_HASH,
      bootId: BOOT_B,
      virtualizationHint: null,
      virtualizationHintDetected: false,
      physicalityProvenBySoftware: false,
      rawMachineIdPersisted: false
    },
    transactionId: TRANSACTION_ID,
    transactionStatus: 'staged-reboot-required',
    verification: {
      schema: 'swir.firmware-update-verification/0.1',
      transactionId: TRANSACTION_ID,
      checkedAt: '2026-09-20T00:09:00.000Z',
      status: 'verified',
      verified: true,
      currentVersion: '1.1.0',
      planDigest: PLAN_DIGEST
    },
    assessment: {
      schema: 'swir.firmware-physical-qualification-assessment/0.1',
      eligible: true,
      sameHost: true,
      physicalSource: true,
      softwareVerified: true,
      rebootRequired: true,
      bootChanged: true,
      requiredRebootObserved: true,
      noVirtualizationHint: true,
      virtualizationHintIsAdvisoryOnly: true,
      transactionBound: true,
      exactPlanBound: true,
      physicalityProvenBySoftware: false,
      operatorFinalizationRequired: true
    },
    operatorAttestation: {
      physicalHardwareObserved: true,
      dedicatedHardware: true,
      recoveryReviewed: true,
      finalizedAt: '2026-09-20T00:10:00.000Z',
      actorId: 'tester'
    },
    physicalHardwareQualification: true,
    policy: {
      schema: 'swir.firmware-physical-qualification-policy/0.1',
      provider: 'fwupd-lvfs',
      trustedRemoteId: 'lvfs',
      dedicatedLabHardwareOnly: true,
      ciEvidenceCountsAsPhysicalQualification: false,
      physicalityProvenBySoftware: false,
      autoReboot: false,
      autoRollback: false
    }
  };
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function reseal(bundle) {
  const changed = clone(bundle);
  changed.payloadDigest = sha256(canonicalEvidenceJson(changed.payload));
  return changed;
}

function expectCode(fn, code) {
  assert.throws(fn, error => {
    assert.equal(error?.code, code);
    return true;
  });
}

assert.equal(FirmwarePhysicalQualificationEvidencePolicy.qualifiedSessionRequired, true);
assert.equal(FirmwarePhysicalQualificationEvidencePolicy.ciEvidenceCountsAsPhysicalQualification, false);
assert.equal(FirmwarePhysicalQualificationEvidencePolicy.rawMachineIdPersisted, false);
assert.equal(FirmwarePhysicalQualificationEvidencePolicy.bootIdsPersistedAsHashesOnly, true);
assert.equal(FirmwarePhysicalQualificationEvidencePolicy.cryptographicOriginAuthentication, false);
assert.equal(FirmwarePhysicalQualificationEvidencePolicy.trustedComparisonRequiredForProvenance, true);
assert.equal(FirmwarePhysicalQualificationEvidencePolicy.automaticReboot, false);
assert.equal(FirmwarePhysicalQualificationEvidencePolicy.automaticRollback, false);

const session = qualifiedSession();
const bundle = createPhysicalQualificationEvidenceBundle(session);
assert.equal(bundle.schema, 'swir.firmware-physical-qualification-evidence/0.1');
assert.equal(bundle.payload.qualification.qualificationId, QUALIFICATION_ID);
assert.equal(bundle.payload.device.deviceId, DEVICE_ID);
assert.equal(bundle.payload.device.targetVersion, '1.1.0');
assert.equal(bundle.payload.binding.planDigest, PLAN_DIGEST);
assert.equal(bundle.payload.binding.transactionId, TRANSACTION_ID);
assert.equal(bundle.payload.host.machineIdHash, MACHINE_HASH);
assert.equal(bundle.payload.host.beforeBootIdHash, sha256(BOOT_A));
assert.equal(bundle.payload.host.afterBootIdHash, sha256(BOOT_B));
assert.equal(bundle.payload.host.bootChanged, true);
assert.equal(bundle.payload.safety.bundleAuthenticatesOrigin, false);
assert.equal(bundle.verificationNotice.cryptographicOriginAuthentication, false);
assert.equal(bundle.verificationNotice.physicalityProvenByBundle, false);
assert.equal(bundle.payloadDigest, sha256(canonicalEvidenceJson(bundle.payload)));

const verified = verifyPhysicalQualificationEvidenceBundle(bundle, {
  qualificationId: QUALIFICATION_ID,
  deviceId: DEVICE_ID,
  targetVersion: '1.1.0',
  planDigest: PLAN_DIGEST,
  transactionId: TRANSACTION_ID,
  machineIdHash: MACHINE_HASH
});
assert.equal(verified.integrityVerified, true);
assert.equal(verified.expectedBindingsSatisfied, true);
assert.equal(verified.cryptographicOriginAuthentication, false);
assert.equal(verified.physicalityProvenByBundle, false);

const secondBundle = createPhysicalQualificationEvidenceBundle(qualifiedSession());
assert.equal(secondBundle.payloadDigest, bundle.payloadDigest, 'same finalized session must produce deterministic evidence payload');
assert.equal(canonicalEvidenceJson(secondBundle.payload), canonicalEvidenceJson(bundle.payload));

const rawTamper = clone(bundle);
rawTamper.payload.device.targetVersion = '9.9.9';
expectCode(() => verifyPhysicalQualificationEvidenceBundle(rawTamper), 'EVIDENCE_PAYLOAD_VERSION_MISMATCH');

const resealedTargetTamper = clone(bundle);
resealedTargetTamper.payload.device.targetVersion = '9.9.9';
resealedTargetTamper.payload.verification.currentVersion = '9.9.9';
const resealedTarget = reseal(resealedTargetTamper);
expectCode(() => verifyPhysicalQualificationEvidenceBundle(resealedTarget, { targetVersion: '1.1.0' }), 'EVIDENCE_EXPECTED_TARGET_MISMATCH');

const resealedDeviceTamper = clone(bundle);
resealedDeviceTamper.payload.device.deviceId = 'device-9999';
const resealedDevice = reseal(resealedDeviceTamper);
expectCode(() => verifyPhysicalQualificationEvidenceBundle(resealedDevice, { deviceId: DEVICE_ID }), 'EVIDENCE_EXPECTED_DEVICE_MISMATCH');

const resealedMachineTamper = clone(bundle);
resealedMachineTamper.payload.host.machineIdHash = 'd'.repeat(64);
const resealedMachine = reseal(resealedMachineTamper);
expectCode(() => verifyPhysicalQualificationEvidenceBundle(resealedMachine, { machineIdHash: MACHINE_HASH }), 'EVIDENCE_EXPECTED_MACHINE_MISMATCH');

const resealedPlanTamper = clone(bundle);
resealedPlanTamper.payload.binding.planDigest = 'e'.repeat(64);
resealedPlanTamper.payload.verification.planDigest = 'e'.repeat(64);
const resealedPlan = reseal(resealedPlanTamper);
expectCode(() => verifyPhysicalQualificationEvidenceBundle(resealedPlan, { planDigest: PLAN_DIGEST }), 'EVIDENCE_EXPECTED_PLAN_MISMATCH');

const resealedTransactionTamper = clone(bundle);
resealedTransactionTamper.payload.binding.transactionId = 'transaction-9999';
resealedTransactionTamper.payload.verification.transactionId = 'transaction-9999';
const resealedTransaction = reseal(resealedTransactionTamper);
expectCode(() => verifyPhysicalQualificationEvidenceBundle(resealedTransaction, { transactionId: TRANSACTION_ID }), 'EVIDENCE_EXPECTED_TRANSACTION_MISMATCH');

const notQualified = qualifiedSession();
notQualified.state = 'ready-for-finalize';
notQualified.physicalHardwareQualification = false;
expectCode(() => createPhysicalQualificationEvidenceBundle(notQualified), 'EVIDENCE_SESSION_NOT_QUALIFIED');

const ciFixture = qualifiedSession();
ciFixture.hostBefore.evidenceSource = 'ci-fixture';
expectCode(() => createPhysicalQualificationEvidenceBundle(ciFixture), 'EVIDENCE_HOST_SOURCE_INVALID');

const virtualized = qualifiedSession();
virtualized.hostAfter.virtualizationHintDetected = true;
expectCode(() => createPhysicalQualificationEvidenceBundle(virtualized), 'EVIDENCE_VIRTUALIZATION_HINT');

const wrongVerification = qualifiedSession();
wrongVerification.verification.transactionId = 'transaction-9999';
expectCode(() => createPhysicalQualificationEvidenceBundle(wrongVerification), 'EVIDENCE_TRANSACTION_BINDING_MISMATCH');

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-firmware-evidence-'));
try {
  const file = path.join(temp, 'qualification.json');
  writePhysicalQualificationEvidenceFile(file, bundle);
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  const persisted = readPhysicalQualificationEvidenceFile(file);
  assert.equal(persisted.payloadDigest, bundle.payloadDigest);
  expectCode(() => writePhysicalQualificationEvidenceFile(file, bundle), 'EVIDENCE_OUTPUT_EXISTS');

  fs.chmodSync(file, 0o644);
  expectCode(() => readPhysicalQualificationEvidenceFile(file), 'EVIDENCE_FILE_UNSAFE');

  const symlinkTarget = path.join(temp, 'real-parent');
  const symlinkParent = path.join(temp, 'linked-parent');
  fs.mkdirSync(symlinkTarget);
  fs.symlinkSync(symlinkTarget, symlinkParent, 'dir');
  expectCode(() => writePhysicalQualificationEvidenceFile(path.join(symlinkParent, 'unsafe.json'), bundle), 'EVIDENCE_PARENT_UNSAFE');
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}

console.log('firmware physical qualification evidence self-test: ok');
