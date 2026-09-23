import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const BUNDLE_SCHEMA = 'swir.firmware-physical-qualification-evidence/0.1';
const PAYLOAD_SCHEMA = 'swir.firmware-physical-qualification-evidence-payload/0.1';
const SESSION_SCHEMA = 'swir.firmware-physical-qualification/0.1';
const DIGEST = /^[a-f0-9]{64}$/;
const DEVICE_ID = /^[A-Za-z0-9._:-]{8,160}$/;
const QUALIFICATION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$/;
const MAX_EVIDENCE_BYTES = 2 * 1024 * 1024;

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'FirmwarePhysicalQualificationEvidenceError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function object(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function clean(value, max = 512) {
  return String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, max);
}

function sha256(value) {
  return crypto.createHash('sha256').update(String(value), 'utf8').digest('hex');
}

function canonicalize(value) {
  if (Array.isArray(value)) return value.map(canonicalize);
  if (!object(value)) return value;
  const result = {};
  for (const key of Object.keys(value).sort()) result[key] = canonicalize(value[key]);
  return result;
}

export function canonicalEvidenceJson(value) {
  return JSON.stringify(canonicalize(value));
}

function assertDigest(value, code, message) {
  assert(typeof value === 'string' && DIGEST.test(value), code, message);
  return value;
}

function assertQualifiedSession(session) {
  assert(object(session) && session.schema === SESSION_SCHEMA, 'EVIDENCE_SESSION_SCHEMA_INVALID', 'qualified firmware session schema mismatch');
  assert(session.state === 'qualified', 'EVIDENCE_SESSION_NOT_QUALIFIED', 'firmware session is not finalized as qualified');
  assert(session.physicalHardwareQualification === true, 'EVIDENCE_PHYSICAL_QUALIFICATION_MISSING', 'firmware session does not carry finalized physical qualification');
  assert(typeof session.qualificationId === 'string' && QUALIFICATION_ID.test(session.qualificationId), 'EVIDENCE_QUALIFICATION_ID_INVALID', 'qualification id is invalid');
  assert(object(session.plan) && session.plan.schema === 'swir.firmware-update-plan/0.1', 'EVIDENCE_PLAN_INVALID', 'firmware plan is missing or invalid');
  assertDigest(session.planDigest, 'EVIDENCE_PLAN_DIGEST_INVALID', 'qualification plan digest is invalid');
  assert(session.plan.digest === session.planDigest, 'EVIDENCE_PLAN_DIGEST_MISMATCH', 'qualification plan digest does not match the reviewed plan');
  assert(session.plan.reviewRequired === true && session.plan.explicitDigestConfirmationRequired === true, 'EVIDENCE_PLAN_REVIEW_INVALID', 'qualified plan did not require explicit review and digest confirmation');
  assert(session.plan.automaticReboot === false && session.plan.automaticRollback === false, 'EVIDENCE_PLAN_AUTOMATION_UNSAFE', 'qualified plan enabled unsafe automatic reboot or rollback claims');

  const binding = session.plan.binding;
  assert(object(binding), 'EVIDENCE_BINDING_INVALID', 'firmware plan binding is missing');
  assert(typeof binding.deviceId === 'string' && DEVICE_ID.test(binding.deviceId), 'EVIDENCE_DEVICE_ID_INVALID', 'firmware device id is invalid');
  assert(binding.remoteId === 'lvfs', 'EVIDENCE_REMOTE_INVALID', 'physical qualification evidence accepts LVFS plans only');
  assert(typeof binding.targetVersion === 'string' && binding.targetVersion.length > 0, 'EVIDENCE_TARGET_VERSION_INVALID', 'target firmware version is missing');

  assert(typeof session.transactionId === 'string' && session.transactionId.length >= 8, 'EVIDENCE_TRANSACTION_ID_INVALID', 'firmware transaction id is invalid');
  assert(object(session.verification), 'EVIDENCE_VERIFICATION_MISSING', 'post-update verification is missing');
  assert(session.verification.verified === true && session.verification.status === 'verified', 'EVIDENCE_VERIFICATION_NOT_VERIFIED', 'post-update firmware verification is not successful');
  assert(session.verification.transactionId === session.transactionId, 'EVIDENCE_TRANSACTION_BINDING_MISMATCH', 'verification transaction binding mismatch');
  assert(session.verification.planDigest === session.planDigest, 'EVIDENCE_VERIFICATION_PLAN_MISMATCH', 'verification plan digest mismatch');
  assert(session.verification.currentVersion === binding.targetVersion, 'EVIDENCE_TARGET_VERSION_MISMATCH', 'verified firmware version does not match the reviewed target');

  const before = session.hostBefore;
  const after = session.hostAfter;
  assert(object(before) && object(after), 'EVIDENCE_HOST_MISSING', 'before/after host evidence is required');
  assert(before.evidenceSource === 'physical-host' && after.evidenceSource === 'physical-host', 'EVIDENCE_HOST_SOURCE_INVALID', 'fixture or CI host evidence cannot be exported as physical qualification');
  assertDigest(before.machineIdHash, 'EVIDENCE_MACHINE_ID_INVALID', 'before-host machine identity hash is invalid');
  assert(after.machineIdHash === before.machineIdHash, 'EVIDENCE_HOST_CHANGED', 'qualification host identity changed');
  assert(before.rawMachineIdPersisted === false && after.rawMachineIdPersisted === false, 'EVIDENCE_RAW_MACHINE_ID_FORBIDDEN', 'raw machine identity must not be persisted in qualification evidence');
  assert(before.virtualizationHintDetected !== true && after.virtualizationHintDetected !== true, 'EVIDENCE_VIRTUALIZATION_HINT', 'virtualization hint is incompatible with finalized physical qualification evidence');
  assert(typeof before.bootId === 'string' && before.bootId.length >= 16 && typeof after.bootId === 'string' && after.bootId.length >= 16, 'EVIDENCE_BOOT_ID_INVALID', 'host boot evidence is invalid');
  if (binding.requiresReboot === true) {
    assert(before.bootId !== after.bootId, 'EVIDENCE_REQUIRED_REBOOT_MISSING', 'required reboot/power-cycle evidence is missing');
  }

  const assessment = session.assessment;
  assert(object(assessment) && assessment.eligible === true, 'EVIDENCE_ASSESSMENT_INELIGIBLE', 'physical qualification assessment is not eligible');
  assert(assessment.sameHost === true && assessment.physicalSource === true && assessment.softwareVerified === true, 'EVIDENCE_ASSESSMENT_BINDING_INVALID', 'physical qualification assessment binding is incomplete');
  assert(assessment.requiredRebootObserved === true && assessment.noVirtualizationHint === true, 'EVIDENCE_ASSESSMENT_HOST_INVALID', 'physical qualification host/reboot assessment is incomplete');
  assert(assessment.transactionBound === true && assessment.exactPlanBound === true, 'EVIDENCE_ASSESSMENT_TRANSACTION_INVALID', 'physical qualification transaction/plan assessment is incomplete');
  assert(assessment.physicalityProvenBySoftware === false && assessment.operatorFinalizationRequired === true, 'EVIDENCE_ASSESSMENT_POLICY_INVALID', 'physical qualification assessment overclaims software proof');

  const attestation = session.operatorAttestation;
  assert(object(attestation), 'EVIDENCE_OPERATOR_ATTESTATION_MISSING', 'operator attestation is missing');
  assert(attestation.physicalHardwareObserved === true && attestation.dedicatedHardware === true && attestation.recoveryReviewed === true, 'EVIDENCE_OPERATOR_ATTESTATION_INVALID', 'operator physical/recovery attestation is incomplete');
  assert(typeof attestation.finalizedAt === 'string' && attestation.finalizedAt.length >= 10, 'EVIDENCE_FINALIZED_AT_INVALID', 'operator finalization timestamp is missing');

  assert(object(session.policy), 'EVIDENCE_POLICY_MISSING', 'qualification policy snapshot is missing');
  assert(session.policy.provider === 'fwupd-lvfs' && session.policy.trustedRemoteId === 'lvfs', 'EVIDENCE_POLICY_PROVIDER_INVALID', 'qualification policy provider mismatch');
  assert(session.policy.ciEvidenceCountsAsPhysicalQualification === false, 'EVIDENCE_POLICY_CI_UNSAFE', 'CI evidence must never count as physical qualification');
  assert(session.policy.physicalityProvenBySoftware === false, 'EVIDENCE_POLICY_PHYSICALITY_UNSAFE', 'software must not claim to prove physical hardware');
  assert(session.policy.autoReboot === false && session.policy.autoRollback === false, 'EVIDENCE_POLICY_AUTOMATION_UNSAFE', 'qualification policy enabled unsafe automatic behavior');
  return session;
}

function createPayload(session) {
  const binding = session.plan.binding;
  const before = session.hostBefore;
  const after = session.hostAfter;
  return {
    schema: PAYLOAD_SCHEMA,
    qualification: {
      qualificationId: session.qualificationId,
      finalizedAt: session.operatorAttestation.finalizedAt,
      state: 'qualified'
    },
    device: {
      deviceId: binding.deviceId,
      deviceName: clean(binding.deviceName ?? '', 256) || null,
      currentVersion: clean(binding.currentVersion ?? '', 128) || null,
      targetVersion: clean(binding.targetVersion, 128),
      releaseId: clean(binding.releaseId ?? '', 256) || null,
      remoteId: 'lvfs',
      sourceRef: clean(binding.sourceRef ?? '', 512) || null,
      requiresReboot: binding.requiresReboot === true
    },
    binding: {
      planDigest: session.planDigest,
      transactionId: session.transactionId,
      transactionStatus: clean(session.transactionStatus ?? '', 128) || null
    },
    host: {
      machineIdHash: before.machineIdHash,
      beforeBootIdHash: sha256(before.bootId),
      afterBootIdHash: sha256(after.bootId),
      bootChanged: before.bootId !== after.bootId,
      physicalEvidenceSource: true,
      virtualizationHintDetected: false,
      rawMachineIdPersisted: false
    },
    verification: {
      schema: clean(session.verification.schema ?? '', 128) || null,
      status: 'verified',
      verified: true,
      transactionId: session.verification.transactionId,
      planDigest: session.verification.planDigest,
      currentVersion: clean(session.verification.currentVersion, 128),
      checkedAt: clean(session.verification.checkedAt ?? '', 128) || null
    },
    assessment: {
      eligible: true,
      sameHost: true,
      physicalSource: true,
      softwareVerified: true,
      requiredRebootObserved: true,
      noVirtualizationHint: true,
      transactionBound: true,
      exactPlanBound: true,
      physicalityProvenBySoftware: false,
      operatorFinalizationRequired: true
    },
    operatorAttestation: {
      physicalHardwareObserved: true,
      dedicatedHardware: true,
      recoveryReviewed: true
    },
    safety: {
      provider: 'fwupd-lvfs',
      trustedRemoteId: 'lvfs',
      ciEvidenceCountsAsPhysicalQualification: false,
      physicalityProvenBySoftware: false,
      automaticReboot: false,
      automaticRollback: false,
      arbitraryFirmwareFileOrUrlAllowed: false,
      bundleAuthenticatesOrigin: false
    }
  };
}

function assertPayload(payload) {
  assert(object(payload) && payload.schema === PAYLOAD_SCHEMA, 'EVIDENCE_PAYLOAD_SCHEMA_INVALID', 'evidence payload schema mismatch');
  assert(object(payload.qualification) && payload.qualification.state === 'qualified', 'EVIDENCE_PAYLOAD_QUALIFICATION_INVALID', 'evidence payload qualification is invalid');
  assert(typeof payload.qualification.qualificationId === 'string' && QUALIFICATION_ID.test(payload.qualification.qualificationId), 'EVIDENCE_PAYLOAD_QUALIFICATION_ID_INVALID', 'evidence payload qualification id is invalid');
  assert(typeof payload.qualification.finalizedAt === 'string' && payload.qualification.finalizedAt.length >= 10, 'EVIDENCE_PAYLOAD_FINALIZED_AT_INVALID', 'evidence payload finalization timestamp is invalid');
  assert(object(payload.device) && typeof payload.device.deviceId === 'string' && DEVICE_ID.test(payload.device.deviceId), 'EVIDENCE_PAYLOAD_DEVICE_INVALID', 'evidence payload device binding is invalid');
  assert(payload.device.remoteId === 'lvfs', 'EVIDENCE_PAYLOAD_REMOTE_INVALID', 'evidence payload remote must be LVFS');
  assert(typeof payload.device.targetVersion === 'string' && payload.device.targetVersion.length > 0, 'EVIDENCE_PAYLOAD_TARGET_INVALID', 'evidence payload target version is missing');
  assert(object(payload.binding), 'EVIDENCE_PAYLOAD_BINDING_INVALID', 'evidence payload binding is missing');
  assertDigest(payload.binding.planDigest, 'EVIDENCE_PAYLOAD_PLAN_DIGEST_INVALID', 'evidence payload plan digest is invalid');
  assert(typeof payload.binding.transactionId === 'string' && payload.binding.transactionId.length >= 8, 'EVIDENCE_PAYLOAD_TRANSACTION_INVALID', 'evidence payload transaction id is invalid');
  assert(object(payload.host), 'EVIDENCE_PAYLOAD_HOST_INVALID', 'evidence payload host binding is missing');
  assertDigest(payload.host.machineIdHash, 'EVIDENCE_PAYLOAD_MACHINE_INVALID', 'evidence payload machine identity hash is invalid');
  assertDigest(payload.host.beforeBootIdHash, 'EVIDENCE_PAYLOAD_BOOT_INVALID', 'before-boot digest is invalid');
  assertDigest(payload.host.afterBootIdHash, 'EVIDENCE_PAYLOAD_BOOT_INVALID', 'after-boot digest is invalid');
  assert(payload.host.physicalEvidenceSource === true && payload.host.virtualizationHintDetected === false && payload.host.rawMachineIdPersisted === false, 'EVIDENCE_PAYLOAD_HOST_POLICY_INVALID', 'evidence payload host policy is unsafe');
  if (payload.device.requiresReboot === true) assert(payload.host.bootChanged === true, 'EVIDENCE_PAYLOAD_REBOOT_INVALID', 'required reboot evidence is missing');
  assert(object(payload.verification) && payload.verification.verified === true && payload.verification.status === 'verified', 'EVIDENCE_PAYLOAD_VERIFICATION_INVALID', 'evidence payload verification is not successful');
  assert(payload.verification.transactionId === payload.binding.transactionId, 'EVIDENCE_PAYLOAD_TRANSACTION_MISMATCH', 'evidence payload transaction binding mismatch');
  assert(payload.verification.planDigest === payload.binding.planDigest, 'EVIDENCE_PAYLOAD_PLAN_MISMATCH', 'evidence payload plan binding mismatch');
  assert(payload.verification.currentVersion === payload.device.targetVersion, 'EVIDENCE_PAYLOAD_VERSION_MISMATCH', 'evidence payload verified version mismatch');
  assert(object(payload.assessment) && payload.assessment.eligible === true && payload.assessment.sameHost === true && payload.assessment.physicalSource === true && payload.assessment.softwareVerified === true, 'EVIDENCE_PAYLOAD_ASSESSMENT_INVALID', 'evidence payload assessment is incomplete');
  assert(payload.assessment.requiredRebootObserved === true && payload.assessment.noVirtualizationHint === true && payload.assessment.transactionBound === true && payload.assessment.exactPlanBound === true, 'EVIDENCE_PAYLOAD_ASSESSMENT_BINDING_INVALID', 'evidence payload assessment bindings are incomplete');
  assert(payload.assessment.physicalityProvenBySoftware === false && payload.assessment.operatorFinalizationRequired === true, 'EVIDENCE_PAYLOAD_ASSESSMENT_POLICY_INVALID', 'evidence payload assessment overclaims software proof');
  assert(object(payload.operatorAttestation) && payload.operatorAttestation.physicalHardwareObserved === true && payload.operatorAttestation.dedicatedHardware === true && payload.operatorAttestation.recoveryReviewed === true, 'EVIDENCE_PAYLOAD_OPERATOR_INVALID', 'evidence payload operator attestation is incomplete');
  assert(object(payload.safety), 'EVIDENCE_PAYLOAD_SAFETY_INVALID', 'evidence payload safety policy is missing');
  assert(payload.safety.provider === 'fwupd-lvfs' && payload.safety.trustedRemoteId === 'lvfs', 'EVIDENCE_PAYLOAD_PROVIDER_INVALID', 'evidence payload provider is invalid');
  assert(payload.safety.ciEvidenceCountsAsPhysicalQualification === false && payload.safety.physicalityProvenBySoftware === false && payload.safety.bundleAuthenticatesOrigin === false, 'EVIDENCE_PAYLOAD_TRUST_OVERCLAIM', 'evidence payload overclaims trust or physicality');
  assert(payload.safety.automaticReboot === false && payload.safety.automaticRollback === false && payload.safety.arbitraryFirmwareFileOrUrlAllowed === false, 'EVIDENCE_PAYLOAD_AUTOMATION_UNSAFE', 'evidence payload safety policy is unsafe');
  return payload;
}

export function createPhysicalQualificationEvidenceBundle(session) {
  assertQualifiedSession(session);
  const payload = createPayload(session);
  assertPayload(payload);
  const payloadDigest = sha256(canonicalEvidenceJson(payload));
  return Object.freeze({
    schema: BUNDLE_SCHEMA,
    digestAlgorithm: 'sha256',
    payload,
    payloadDigest,
    verificationNotice: {
      integrityDigestOnly: true,
      cryptographicOriginAuthentication: false,
      physicalityProvenByBundle: false,
      trustedComparisonRequiredForProvenance: true
    }
  });
}

function assertExpected(expected, key, actual, code) {
  if (expected?.[key] == null) return;
  assert(String(expected[key]) === String(actual), code, `evidence ${key} does not match the expected binding`);
}

export function verifyPhysicalQualificationEvidenceBundle(bundle, expected = {}) {
  assert(object(bundle) && bundle.schema === BUNDLE_SCHEMA, 'EVIDENCE_BUNDLE_SCHEMA_INVALID', 'physical qualification evidence bundle schema mismatch');
  assert(bundle.digestAlgorithm === 'sha256', 'EVIDENCE_DIGEST_ALGORITHM_INVALID', 'physical qualification evidence digest algorithm mismatch');
  assertPayload(bundle.payload);
  assertDigest(bundle.payloadDigest, 'EVIDENCE_BUNDLE_DIGEST_INVALID', 'physical qualification evidence digest is invalid');
  const calculatedDigest = sha256(canonicalEvidenceJson(bundle.payload));
  assert(calculatedDigest === bundle.payloadDigest, 'EVIDENCE_BUNDLE_DIGEST_MISMATCH', 'physical qualification evidence payload digest mismatch');
  assert(object(bundle.verificationNotice), 'EVIDENCE_NOTICE_MISSING', 'physical qualification evidence verification notice is missing');
  assert(bundle.verificationNotice.integrityDigestOnly === true && bundle.verificationNotice.cryptographicOriginAuthentication === false && bundle.verificationNotice.physicalityProvenByBundle === false && bundle.verificationNotice.trustedComparisonRequiredForProvenance === true, 'EVIDENCE_NOTICE_TRUST_OVERCLAIM', 'physical qualification evidence notice overclaims origin or physicality');

  const payload = bundle.payload;
  assertExpected(expected, 'qualificationId', payload.qualification.qualificationId, 'EVIDENCE_EXPECTED_QUALIFICATION_MISMATCH');
  assertExpected(expected, 'deviceId', payload.device.deviceId, 'EVIDENCE_EXPECTED_DEVICE_MISMATCH');
  assertExpected(expected, 'targetVersion', payload.device.targetVersion, 'EVIDENCE_EXPECTED_TARGET_MISMATCH');
  assertExpected(expected, 'planDigest', payload.binding.planDigest, 'EVIDENCE_EXPECTED_PLAN_MISMATCH');
  assertExpected(expected, 'transactionId', payload.binding.transactionId, 'EVIDENCE_EXPECTED_TRANSACTION_MISMATCH');
  assertExpected(expected, 'machineIdHash', payload.host.machineIdHash, 'EVIDENCE_EXPECTED_MACHINE_MISMATCH');

  return Object.freeze({
    schema: 'swir.firmware-physical-qualification-evidence-verification/0.1',
    integrityVerified: true,
    expectedBindingsSatisfied: true,
    qualificationId: payload.qualification.qualificationId,
    deviceId: payload.device.deviceId,
    targetVersion: payload.device.targetVersion,
    planDigest: payload.binding.planDigest,
    transactionId: payload.binding.transactionId,
    machineIdHash: payload.host.machineIdHash,
    payloadDigest: bundle.payloadDigest,
    cryptographicOriginAuthentication: false,
    physicalityProvenByBundle: false,
    trustedComparisonRequiredForProvenance: true
  });
}

function assertSafeEvidenceFile(file) {
  assert(typeof file === 'string' && path.isAbsolute(file), 'EVIDENCE_PATH_INVALID', 'evidence file path must be absolute');
  const resolved = path.resolve(file);
  const parent = path.dirname(resolved);
  const parentStat = fs.lstatSync(parent);
  assert(parentStat.isDirectory() && !parentStat.isSymbolicLink(), 'EVIDENCE_PARENT_UNSAFE', 'evidence parent must be a real directory');
  assert(fs.realpathSync(parent) === parent, 'EVIDENCE_PARENT_SYMLINKED', 'evidence parent path must not traverse symbolic links');
  return resolved;
}

export function writePhysicalQualificationEvidenceFile(file, bundle) {
  verifyPhysicalQualificationEvidenceBundle(bundle);
  const target = assertSafeEvidenceFile(file);
  assert(!fs.existsSync(target), 'EVIDENCE_OUTPUT_EXISTS', 'refusing to overwrite an existing evidence file');
  const serialized = `${JSON.stringify(bundle, null, 2)}\n`;
  assert(Buffer.byteLength(serialized) <= MAX_EVIDENCE_BYTES, 'EVIDENCE_FILE_TOO_LARGE', 'physical qualification evidence exceeds maximum size');
  const fd = fs.openSync(target, fs.constants.O_WRONLY | fs.constants.O_CREAT | fs.constants.O_EXCL | (fs.constants.O_NOFOLLOW ?? 0), 0o600);
  try {
    fs.writeFileSync(fd, serialized, 'utf8');
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  fs.chmodSync(target, 0o600);
  return target;
}

export function readPhysicalQualificationEvidenceFile(file) {
  const target = assertSafeEvidenceFile(file);
  const flags = fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0);
  const fd = fs.openSync(target, flags);
  try {
    const stat = fs.fstatSync(fd);
    assert(stat.isFile() && !stat.isSymbolicLink() && (stat.mode & 0o077) === 0 && stat.size > 0 && stat.size <= MAX_EVIDENCE_BYTES, 'EVIDENCE_FILE_UNSAFE', 'physical qualification evidence file is unsafe');
    const bundle = JSON.parse(fs.readFileSync(fd, 'utf8'));
    verifyPhysicalQualificationEvidenceBundle(bundle);
    return bundle;
  } catch (error) {
    if (error?.name === 'SyntaxError') fail('EVIDENCE_FILE_JSON_INVALID', 'physical qualification evidence file is not valid JSON', error);
    throw error;
  } finally {
    fs.closeSync(fd);
  }
}

export const FirmwarePhysicalQualificationEvidencePolicy = Object.freeze({
  schema: 'swir.firmware-physical-qualification-evidence-policy/0.1',
  qualifiedSessionRequired: true,
  ciEvidenceCountsAsPhysicalQualification: false,
  rawMachineIdPersisted: false,
  bootIdsPersistedAsHashesOnly: true,
  integrityDigestAlgorithm: 'sha256',
  cryptographicOriginAuthentication: false,
  trustedComparisonRequiredForProvenance: true,
  evidenceFileOverwriteAllowed: false,
  arbitraryFirmwareFileOrUrlAllowed: false,
  automaticReboot: false,
  automaticRollback: false
});
