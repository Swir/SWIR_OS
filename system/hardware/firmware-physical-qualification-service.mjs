import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const QUALIFICATION_SCHEMA = 'swir.firmware-physical-qualification/0.1';
const POLICY_SCHEMA = 'swir.firmware-physical-qualification-policy/0.1';
const DEFAULT_ROOT = '/var/lib/swir/qualification/firmware';
const QUALIFICATION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$/;
const DEVICE_ID = /^[A-Za-z0-9._:-]{8,160}$/;
const DIGEST = /^[a-f0-9]{64}$/;
const MAX_EVIDENCE_BYTES = 2 * 1024 * 1024;

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'FirmwarePhysicalQualificationError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function object(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function clean(value, max = 512) {
  return String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, max);
}

function safeError(error) {
  return {
    code: clean(error?.code || 'PHYSICAL_QUALIFICATION_FAILED', 128),
    message: clean(error?.message || 'physical qualification failed', 1000)
  };
}

function sha256(value) {
  return crypto.createHash('sha256').update(String(value), 'utf8').digest('hex');
}

function readTrimmedFile(file, maxBytes = 4096) {
  const stat = fs.lstatSync(file);
  assert(stat.isFile() && !stat.isSymbolicLink() && stat.size <= maxBytes, 'HOST_EVIDENCE_FILE_UNSAFE', `${file} is not a safe host-evidence file`);
  return fs.readFileSync(file, 'utf8').trim();
}

function optionalTrimmedFile(file, maxBytes = 4096) {
  try {
    return clean(readTrimmedFile(file, maxBytes), 512) || null;
  } catch (error) {
    if (error?.code === 'ENOENT' || error?.code === 'EACCES') return null;
    throw error;
  }
}

function virtualizationHint(productName, sysVendor) {
  const text = `${productName ?? ''} ${sysVendor ?? ''}`.toLowerCase();
  const markers = ['qemu', 'kvm', 'vmware', 'virtualbox', 'hyper-v', 'microsoft corporation virtual machine', 'xen', 'bochs', 'parallels'];
  return markers.find(marker => text.includes(marker)) ?? null;
}

function assertHostEvidence(host) {
  assert(object(host), 'HOST_EVIDENCE_INVALID', 'host evidence is required');
  assert(host.schema === 'swir.firmware-qualification-host/0.1', 'HOST_EVIDENCE_SCHEMA_INVALID', 'host evidence schema mismatch');
  assert(host.evidenceSource === 'physical-host', 'HOST_EVIDENCE_SOURCE_INVALID', 'only live physical-host evidence may be used for qualification');
  assert(typeof host.machineIdHash === 'string' && DIGEST.test(host.machineIdHash), 'HOST_MACHINE_ID_INVALID', 'hashed machine identity is invalid');
  assert(typeof host.bootId === 'string' && /^[A-Fa-f0-9-]{16,80}$/.test(host.bootId), 'HOST_BOOT_ID_INVALID', 'boot identity is invalid');
  return host;
}

function assertPlan(plan) {
  assert(object(plan) && plan.schema === 'swir.firmware-update-plan/0.1', 'QUALIFICATION_PLAN_INVALID', 'firmware plan schema mismatch');
  assert(typeof plan.digest === 'string' && DIGEST.test(plan.digest), 'QUALIFICATION_PLAN_DIGEST_INVALID', 'firmware plan digest is invalid');
  assert(plan.reviewRequired === true && plan.explicitDigestConfirmationRequired === true, 'QUALIFICATION_PLAN_REVIEW_REQUIRED', 'firmware plan must require explicit review and digest confirmation');
  assert(plan.automaticReboot === false && plan.automaticRollback === false, 'QUALIFICATION_PLAN_AUTOMATION_UNSAFE', 'firmware plan must not auto-reboot or promise automatic rollback');
  assert(typeof plan?.binding?.deviceId === 'string' && DEVICE_ID.test(plan.binding.deviceId), 'QUALIFICATION_DEVICE_ID_INVALID', 'firmware plan device id is invalid');
  assert(typeof plan?.binding?.targetVersion === 'string' && plan.binding.targetVersion.length > 0, 'QUALIFICATION_TARGET_VERSION_INVALID', 'firmware plan target version is missing');
  assert(plan.binding.remoteId === 'lvfs', 'QUALIFICATION_REMOTE_INVALID', 'physical qualification accepts LVFS firmware plans only');
  return plan;
}

function sameMachine(before, after) {
  return before?.machineIdHash === after?.machineIdHash;
}

function expectedApplyPhrase(session) {
  return `APPLY ${session.plan.binding.deviceId} ${session.plan.digest}`;
}

function expectedFinalizePhrase(session) {
  return `QUALIFY ${session.plan.binding.deviceId} ${session.plan.binding.targetVersion} ${session.plan.digest}`;
}

export class PhysicalFirmwareHostProbe {
  constructor({
    machineIdFile = '/etc/machine-id',
    bootIdFile = '/proc/sys/kernel/random/boot_id',
    productNameFile = '/sys/class/dmi/id/product_name',
    sysVendorFile = '/sys/class/dmi/id/sys_vendor',
    clock = () => new Date().toISOString()
  } = {}) {
    this.machineIdFile = machineIdFile;
    this.bootIdFile = bootIdFile;
    this.productNameFile = productNameFile;
    this.sysVendorFile = sysVendorFile;
    this.clock = clock;
  }

  capture() {
    const machineId = readTrimmedFile(this.machineIdFile);
    const bootId = readTrimmedFile(this.bootIdFile);
    assert(machineId.length >= 16 && machineId.length <= 256, 'HOST_MACHINE_ID_INVALID', 'machine id is missing or invalid');
    assert(/^[A-Fa-f0-9-]{16,80}$/.test(bootId), 'HOST_BOOT_ID_INVALID', 'boot id is missing or invalid');
    const productName = optionalTrimmedFile(this.productNameFile);
    const sysVendor = optionalTrimmedFile(this.sysVendorFile);
    const hint = virtualizationHint(productName, sysVendor);
    return Object.freeze({
      schema: 'swir.firmware-qualification-host/0.1',
      capturedAt: this.clock(),
      evidenceSource: 'physical-host',
      machineIdHash: sha256(machineId),
      bootId,
      virtualizationHint: hint,
      virtualizationHintDetected: Boolean(hint),
      physicalityProvenBySoftware: false,
      rawMachineIdPersisted: false
    });
  }
}

export class FileFirmwarePhysicalQualificationJournal {
  constructor({ root = DEFAULT_ROOT, expectedOwnerUid = 0, enforceOwnership = true } = {}) {
    assert(typeof root === 'string' && path.isAbsolute(root), 'QUALIFICATION_ROOT_INVALID', 'qualification journal root must be absolute');
    this.root = path.resolve(root);
    this.expectedOwnerUid = expectedOwnerUid;
    this.enforceOwnership = enforceOwnership;
  }

  ensureRoot() {
    fs.mkdirSync(this.root, { recursive: true, mode: 0o700 });
    let stat = fs.lstatSync(this.root);
    assert(stat.isDirectory() && !stat.isSymbolicLink(), 'QUALIFICATION_ROOT_UNSAFE', 'qualification journal root must be a real directory');
    fs.chmodSync(this.root, 0o700);
    stat = fs.lstatSync(this.root);
    assert((stat.mode & 0o077) === 0, 'QUALIFICATION_ROOT_MODE_UNSAFE', 'qualification journal root must not be group/world accessible');
    if (this.enforceOwnership && this.expectedOwnerUid !== null && typeof stat.uid === 'number') {
      assert(stat.uid === this.expectedOwnerUid, 'QUALIFICATION_ROOT_OWNER_INVALID', 'qualification journal root owner is not trusted');
    }
  }

  file(qualificationId) {
    assert(typeof qualificationId === 'string' && QUALIFICATION_ID.test(qualificationId), 'QUALIFICATION_ID_INVALID', 'qualification id is invalid');
    const file = path.resolve(this.root, `${qualificationId}.json`);
    assert(path.dirname(file) === this.root, 'QUALIFICATION_PATH_ESCAPE', 'qualification path escaped its root');
    return file;
  }

  write(entry) {
    assert(object(entry) && entry.schema === QUALIFICATION_SCHEMA, 'QUALIFICATION_ENTRY_INVALID', 'qualification journal entry is invalid');
    assert(entry.qualificationId && QUALIFICATION_ID.test(entry.qualificationId), 'QUALIFICATION_ID_INVALID', 'qualification id is invalid');
    this.ensureRoot();
    const target = this.file(entry.qualificationId);
    const temporary = `${target}.${crypto.randomUUID()}.tmp`;
    const serialized = `${JSON.stringify(entry, null, 2)}\n`;
    assert(Buffer.byteLength(serialized) <= MAX_EVIDENCE_BYTES, 'QUALIFICATION_ENTRY_TOO_LARGE', 'qualification evidence exceeds maximum size');
    fs.writeFileSync(temporary, serialized, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
    fs.chmodSync(temporary, 0o600);
    const fd = fs.openSync(temporary, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0));
    try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temporary, target);
    try {
      const dirFd = fs.openSync(this.root, fs.constants.O_RDONLY);
      try { fs.fsyncSync(dirFd); } finally { fs.closeSync(dirFd); }
    } catch (error) {
      if (!['EINVAL', 'ENOTSUP'].includes(error?.code)) throw error;
    }
    return target;
  }

  read(qualificationId) {
    this.ensureRoot();
    const file = this.file(qualificationId);
    const flags = fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW ?? 0);
    const fd = fs.openSync(file, flags);
    try {
      const stat = fs.fstatSync(fd);
      assert(stat.isFile() && (stat.mode & 0o077) === 0 && stat.size <= MAX_EVIDENCE_BYTES, 'QUALIFICATION_FILE_UNSAFE', 'qualification evidence file is unsafe');
      const content = fs.readFileSync(fd, 'utf8');
      const entry = JSON.parse(content);
      assert(entry?.schema === QUALIFICATION_SCHEMA && entry.qualificationId === qualificationId, 'QUALIFICATION_BINDING_INVALID', 'qualification evidence identity mismatch');
      assertPlan(entry.plan);
      assert(entry.planDigest === entry.plan.digest, 'QUALIFICATION_DIGEST_MISMATCH', 'qualification plan digest mismatch');
      return entry;
    } finally {
      fs.closeSync(fd);
    }
  }

  list() {
    this.ensureRoot();
    return fs.readdirSync(this.root)
      .filter(name => /^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}\.json$/.test(name))
      .sort()
      .map(name => this.read(name.slice(0, -5)));
  }
}

export function evaluatePhysicalQualificationEvidence(session) {
  assert(object(session) && session.schema === QUALIFICATION_SCHEMA, 'QUALIFICATION_SESSION_INVALID', 'qualification session is invalid');
  const before = session.hostBefore;
  const after = session.hostAfter;
  const verification = session.verification;
  const sameHost = Boolean(before && after && before.machineIdHash === after.machineIdHash);
  const physicalSource = before?.evidenceSource === 'physical-host' && after?.evidenceSource === 'physical-host';
  const softwareVerified = verification?.verified === true && verification?.status === 'verified';
  const rebootRequired = session?.plan?.binding?.requiresReboot === true;
  const bootChanged = Boolean(before?.bootId && after?.bootId && before.bootId !== after.bootId);
  const requiredRebootObserved = !rebootRequired || bootChanged;
  const noVirtualizationHint = before?.virtualizationHintDetected !== true && after?.virtualizationHintDetected !== true;
  const transactionBound = typeof session.transactionId === 'string' && session.transactionId.length >= 8 && verification?.transactionId === session.transactionId;
  const exactPlanBound = verification?.planDigest === session.planDigest;
  const eligible = sameHost && physicalSource && softwareVerified && requiredRebootObserved && noVirtualizationHint && transactionBound && exactPlanBound;
  return Object.freeze({
    schema: 'swir.firmware-physical-qualification-assessment/0.1',
    eligible,
    sameHost,
    physicalSource,
    softwareVerified,
    rebootRequired,
    bootChanged,
    requiredRebootObserved,
    noVirtualizationHint,
    virtualizationHintIsAdvisoryOnly: true,
    transactionBound,
    exactPlanBound,
    physicalityProvenBySoftware: false,
    operatorFinalizationRequired: true
  });
}

export class FirmwarePhysicalQualificationService {
  constructor({
    transactionService,
    verificationService,
    hostProbe = new PhysicalFirmwareHostProbe(),
    journal = new FileFirmwarePhysicalQualificationJournal(),
    clock = () => new Date().toISOString(),
    idFactory = () => `qualification-${crypto.randomUUID()}`
  } = {}) {
    assert(typeof transactionService?.plan === 'function' && typeof transactionService?.update === 'function', 'QUALIFICATION_TRANSACTION_SERVICE_REQUIRED', 'firmware transaction service is required');
    assert(typeof verificationService?.verify === 'function', 'QUALIFICATION_VERIFICATION_SERVICE_REQUIRED', 'firmware verification service is required');
    assert(typeof hostProbe?.capture === 'function', 'QUALIFICATION_HOST_PROBE_REQUIRED', 'physical host probe is required');
    assert(typeof journal?.read === 'function' && typeof journal?.write === 'function' && typeof journal?.list === 'function', 'QUALIFICATION_JOURNAL_REQUIRED', 'qualification journal is required');
    this.transactionService = transactionService;
    this.verificationService = verificationService;
    this.hostProbe = hostProbe;
    this.journal = journal;
    this.clock = clock;
    this.idFactory = idFactory;
  }

  async prepare(candidate, { actorId = null } = {}) {
    const plan = assertPlan(await this.transactionService.plan(candidate));
    const hostBefore = assertHostEvidence(await this.hostProbe.capture());
    const qualificationId = this.idFactory();
    assert(typeof qualificationId === 'string' && QUALIFICATION_ID.test(qualificationId), 'QUALIFICATION_ID_INVALID', 'qualification id is invalid');
    const now = this.clock();
    const session = {
      schema: QUALIFICATION_SCHEMA,
      qualificationId,
      state: 'prepared',
      createdAt: now,
      updatedAt: now,
      actorId: actorId == null ? null : clean(actorId, 128),
      candidate: clone(candidate),
      plan: clone(plan),
      planDigest: plan.digest,
      hostBefore: clone(hostBefore),
      hostAfter: null,
      transactionId: null,
      transactionStatus: null,
      verification: null,
      assessment: null,
      operatorAttestation: null,
      physicalHardwareQualification: false,
      policy: clone(FirmwarePhysicalQualificationPolicy),
      expectedApplyPhrase: expectedApplyPhrase({ plan }),
      expectedFinalizePhrase: expectedFinalizePhrase({ plan }),
      error: null
    };
    this.journal.write(session);
    return Object.freeze(clone(session));
  }

  status(qualificationId) {
    const session = this.journal.read(qualificationId);
    return Object.freeze({ ...clone(session), assessment: clone(session.assessment ?? evaluatePhysicalQualificationEvidence(session)) });
  }

  async apply(qualificationId, context = {}) {
    const session = this.journal.read(qualificationId);
    assert(session.state === 'prepared', 'QUALIFICATION_APPLY_STATE_INVALID', 'firmware qualification apply is allowed only from prepared state');
    assert(context.interactive === true, 'QUALIFICATION_INTERACTIVE_APPLY_REQUIRED', 'interactive operator confirmation is required before firmware mutation');
    assert(context.operatorPresent === true, 'QUALIFICATION_OPERATOR_REQUIRED', 'an operator must be present for physical firmware mutation');
    assert(context.physicalDedicatedHardware === true, 'QUALIFICATION_DEDICATED_HARDWARE_REQUIRED', 'firmware qualification is restricted to dedicated physical lab hardware');
    assert(context.confirmationDigest === session.planDigest, 'QUALIFICATION_CONFIRMATION_DIGEST_INVALID', 'exact reviewed firmware plan digest is required');
    assert(context.typedPhrase === expectedApplyPhrase(session), 'QUALIFICATION_APPLY_PHRASE_INVALID', 'typed firmware apply confirmation does not match the reviewed plan');

    const liveHost = assertHostEvidence(await this.hostProbe.capture());
    assert(sameMachine(session.hostBefore, liveHost), 'QUALIFICATION_HOST_CHANGED', 'qualification session moved to a different machine before mutation');
    assert(session.hostBefore.bootId === liveHost.bootId, 'QUALIFICATION_BOOT_CHANGED_BEFORE_APPLY', 'host rebooted after preflight; prepare a fresh firmware qualification session');
    assert(session.hostBefore.virtualizationHintDetected !== true && liveHost.virtualizationHintDetected !== true, 'QUALIFICATION_VIRTUALIZATION_HINT', 'software detected a virtualization hint; physical qualification cannot proceed');

    try {
      const result = await this.transactionService.update(session.candidate, {
        plan: session.plan,
        confirmationDigest: context.confirmationDigest,
        actorId: context.actorId == null ? session.actorId : clean(context.actorId, 128)
      });
      const updated = {
        ...session,
        state: 'applied-verification-required',
        updatedAt: this.clock(),
        transactionId: result.transactionId,
        transactionStatus: result.status,
        physicalHardwareQualification: false,
        error: null
      };
      this.journal.write(updated);
      return Object.freeze(clone(updated));
    } catch (error) {
      this.journal.write({
        ...session,
        state: 'apply-failed-needs-review',
        updatedAt: this.clock(),
        physicalHardwareQualification: false,
        error: safeError(error)
      });
      throw error;
    }
  }

  async verify(qualificationId) {
    const session = this.journal.read(qualificationId);
    assert(['applied-verification-required', 'verification-pending', 'ready-for-finalize'].includes(session.state), 'QUALIFICATION_VERIFY_STATE_INVALID', 'qualification session is not ready for post-update verification');
    assert(typeof session.transactionId === 'string' && session.transactionId.length >= 8, 'QUALIFICATION_TRANSACTION_ID_MISSING', 'qualification session has no firmware transaction id');
    const hostAfter = assertHostEvidence(await this.hostProbe.capture());
    assert(sameMachine(session.hostBefore, hostAfter), 'QUALIFICATION_HOST_CHANGED', 'post-update verification is running on a different machine');
    const verification = await this.verificationService.verify(session.transactionId);
    const provisional = {
      ...session,
      updatedAt: this.clock(),
      hostAfter: clone(hostAfter),
      verification: clone(verification),
      physicalHardwareQualification: false,
      error: null
    };
    const assessment = evaluatePhysicalQualificationEvidence(provisional);
    const updated = {
      ...provisional,
      assessment: clone(assessment),
      state: assessment.eligible ? 'ready-for-finalize' : 'verification-pending'
    };
    this.journal.write(updated);
    return Object.freeze(clone(updated));
  }

  async finalize(qualificationId, context = {}) {
    const session = this.journal.read(qualificationId);
    assert(session.state === 'ready-for-finalize', 'QUALIFICATION_FINALIZE_STATE_INVALID', 'qualification evidence is not ready for final operator review');
    assert(context.interactive === true, 'QUALIFICATION_INTERACTIVE_FINALIZE_REQUIRED', 'interactive final operator confirmation is required');
    assert(context.operatorPresent === true, 'QUALIFICATION_OPERATOR_REQUIRED', 'an operator must be present for final qualification');
    assert(context.physicalHardwareObserved === true, 'QUALIFICATION_PHYSICAL_OBSERVATION_REQUIRED', 'operator must explicitly attest physical hardware observation');
    assert(context.dedicatedHardware === true, 'QUALIFICATION_DEDICATED_HARDWARE_REQUIRED', 'operator must attest this is dedicated qualification hardware');
    assert(context.recoveryReviewed === true, 'QUALIFICATION_RECOVERY_REVIEW_REQUIRED', 'operator must review device-specific recovery guidance before final qualification');
    assert(context.typedPhrase === expectedFinalizePhrase(session), 'QUALIFICATION_FINALIZE_PHRASE_INVALID', 'typed final qualification phrase does not match the verified plan');
    assert(session.hostBefore?.evidenceSource === 'physical-host' && session.hostAfter?.evidenceSource === 'physical-host', 'QUALIFICATION_FIXTURE_EVIDENCE_FORBIDDEN', 'fixture/CI evidence can never count as physical hardware qualification');

    const liveHost = assertHostEvidence(await this.hostProbe.capture());
    assert(sameMachine(session.hostBefore, liveHost), 'QUALIFICATION_HOST_CHANGED', 'final qualification is running on a different machine');
    assert(session.hostAfter?.bootId === liveHost.bootId, 'QUALIFICATION_BOOT_CHANGED_AFTER_VERIFY', 'host boot identity changed after verification; verify again before finalizing');
    assert(liveHost.virtualizationHintDetected !== true, 'QUALIFICATION_VIRTUALIZATION_HINT', 'software detected a virtualization hint; physical qualification cannot be finalized');
    const assessment = evaluatePhysicalQualificationEvidence({ ...session, hostAfter: liveHost });
    assert(assessment.eligible === true, 'QUALIFICATION_EVIDENCE_INCOMPLETE', 'physical qualification evidence is incomplete');

    const updated = {
      ...session,
      state: 'qualified',
      updatedAt: this.clock(),
      hostAfter: clone(liveHost),
      assessment: clone(assessment),
      operatorAttestation: {
        physicalHardwareObserved: true,
        dedicatedHardware: true,
        recoveryReviewed: true,
        finalizedAt: this.clock(),
        actorId: context.actorId == null ? session.actorId : clean(context.actorId, 128)
      },
      physicalHardwareQualification: true,
      error: null
    };
    this.journal.write(updated);
    return Object.freeze(clone(updated));
  }
}

export const FirmwarePhysicalQualificationPolicy = Object.freeze({
  schema: POLICY_SCHEMA,
  provider: 'fwupd-lvfs',
  trustedRemoteId: 'lvfs',
  dedicatedLabHardwareOnly: true,
  ciEvidenceCountsAsPhysicalQualification: false,
  interactiveApplyRequired: true,
  interactiveFinalizeRequired: true,
  exactPlanDigestConfirmationRequired: true,
  sameHostBindingRequired: true,
  sameBootRequiredBetweenPreflightAndApply: true,
  requiredRebootMustChangeBootId: true,
  operatorPhysicalObservationRequired: true,
  virtualizationHintIsAdvisoryOnly: true,
  physicalityProvenBySoftware: false,
  arbitraryFirmwareUrlOrFile: false,
  autoReboot: false,
  autoRollback: false,
  automaticQualification: false
});