import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { execFile } from 'node:child_process';
import { FwupdLvfsService, assertSafeFwupdLvfsInventory } from './fwupd-lvfs-service.mjs';

const DEFAULT_BINARY = '/usr/bin/fwupdmgr';
const DEFAULT_JOURNAL_ROOT = '/var/lib/swir/transactions/firmware';
const PLAN_SCHEMA = 'swir.firmware-update-plan/0.1';
const RESULT_SCHEMA = 'swir.firmware-transaction-result/0.1';
const JOURNAL_SCHEMA = 'swir.firmware-update-transaction/0.1';
const DEVICE_ID = /^[A-Za-z0-9._:-]{8,160}$/;
const TRANSACTION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$/;
const DIGEST = /^[a-f0-9]{64}$/;
const MAX_JOURNAL_BYTES = 1024 * 1024;
const MAX_OUTPUT_BYTES = 4 * 1024 * 1024;
const ACTIVE_STATES = new Set(['prepared', 'executing']);

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'FirmwareUpdateTransactionError';
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

function stableStringify(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(',')}}`;
}

function digest(value) {
  return crypto.createHash('sha256').update(stableStringify(value), 'utf8').digest('hex');
}

function normalizeChecksums(values) {
  return [...new Set((Array.isArray(values) ? values : [])
    .map(value => String(value ?? '').trim().toLowerCase())
    .filter(value => /^[a-f0-9]{40}$|^[a-f0-9]{64}$/.test(value)))].sort();
}

function safeError(error) {
  return {
    code: typeof error?.code === 'string' ? error.code.slice(0, 128) : 'FIRMWARE_UPDATE_FAILED',
    message: typeof error?.message === 'string' ? error.message.slice(0, 1000) : 'firmware update failed'
  };
}

function candidateBinding(candidate) {
  assert(object(candidate), 'FIRMWARE_CANDIDATE_INVALID', 'firmware candidate is required');
  assert(candidate.remoteId === 'lvfs', 'FIRMWARE_REMOTE_UNTRUSTED', 'firmware candidate must come from LVFS');
  assert(candidate?.source?.class === 'fwupd-lvfs' && candidate?.source?.repositoryId === 'lvfs', 'FIRMWARE_SOURCE_UNTRUSTED', 'firmware candidate source is not trusted fwupd/LVFS');
  assert(candidate.trustedSource === true && candidate.directDownloadUrlExposed === false && candidate.mutationAuthorized === false, 'FIRMWARE_DISCOVERY_BOUNDARY_INVALID', 'firmware discovery trust boundary is invalid');
  assert(typeof candidate.deviceId === 'string' && DEVICE_ID.test(candidate.deviceId), 'FIRMWARE_DEVICE_ID_INVALID', 'firmware device id is invalid');
  assert(typeof candidate.version === 'string' && candidate.version.length > 0 && candidate.version.length <= 128, 'FIRMWARE_TARGET_VERSION_INVALID', 'firmware target version is required');
  const checksums = normalizeChecksums(candidate.checksums);
  assert(checksums.length > 0, 'FIRMWARE_CHECKSUM_REQUIRED', 'firmware update requires a signed metadata checksum binding');
  const binding = {
    deviceId: candidate.deviceId,
    deviceName: String(candidate.deviceName ?? 'Unknown device').slice(0, 256),
    currentVersion: candidate.currentVersion == null ? null : String(candidate.currentVersion).slice(0, 128),
    targetVersion: candidate.version,
    releaseId: candidate.releaseId == null ? null : String(candidate.releaseId).slice(0, 128),
    remoteId: 'lvfs',
    checksums,
    requiresReboot: candidate.requiresReboot === true,
    sourceRef: String(candidate?.source?.ref ?? '').slice(0, 512)
  };
  assert(binding.sourceRef.startsWith('fwupd:'), 'FIRMWARE_SOURCE_REF_INVALID', 'firmware source ref must be a fwupd binding');
  return binding;
}

function candidatesForDevice(inventory, deviceId) {
  assertSafeFwupdLvfsInventory(inventory);
  return (inventory.candidates || []).filter(candidate => candidate?.deviceId === deviceId);
}

function assertPlan(plan) {
  assert(object(plan) && plan.schema === PLAN_SCHEMA, 'FIRMWARE_PLAN_INVALID', 'firmware update plan schema mismatch');
  assert(typeof plan.generatedAt === 'string' && plan.generatedAt.length > 0, 'FIRMWARE_PLAN_TIME_INVALID', 'firmware plan generation time is missing');
  assert(plan.provider === 'fwupd-lvfs' && plan.remoteId === 'lvfs', 'FIRMWARE_PLAN_SOURCE_INVALID', 'firmware plan must be bound to fwupd/LVFS');
  assert(plan.reviewRequired === true && plan.explicitDigestConfirmationRequired === true, 'FIRMWARE_PLAN_CONFIRMATION_POLICY_INVALID', 'firmware plan must require explicit digest confirmation');
  assert(plan.automaticReboot === false && plan.automaticRollback === false, 'FIRMWARE_PLAN_RECOVERY_POLICY_INVALID', 'firmware plan must not promise automatic reboot or firmware rollback');
  const binding = candidateBinding({
    ...plan.binding,
    version: plan.binding?.targetVersion,
    remoteId: plan.binding?.remoteId,
    source: { class: 'fwupd-lvfs', repositoryId: 'lvfs', ref: plan.binding?.sourceRef },
    trustedSource: true,
    directDownloadUrlExposed: false,
    mutationAuthorized: false
  });
  const core = { ...clone(plan) };
  delete core.digest;
  assert(typeof plan.digest === 'string' && DIGEST.test(plan.digest) && digest(core) === plan.digest, 'FIRMWARE_PLAN_DIGEST_MISMATCH', 'firmware plan digest mismatch');
  return binding;
}

function defaultRunner(binary, args, options) {
  return new Promise((resolve, reject) => {
    execFile(binary, args, options, (error, stdout, stderr) => {
      if (error) {
        error.stdout = stdout;
        error.stderr = stderr;
        reject(error);
        return;
      }
      resolve({ stdout, stderr, code: 0 });
    });
  });
}

export class FileFirmwareUpdateJournal {
  #root;
  #expectedOwnerUid;
  #enforceOwnership;

  constructor({ root = DEFAULT_JOURNAL_ROOT, expectedOwnerUid = 0, enforceOwnership = true } = {}) {
    assert(typeof root === 'string' && path.isAbsolute(root), 'FIRMWARE_JOURNAL_ROOT_INVALID', 'firmware journal root must be absolute');
    this.#root = path.resolve(root);
    this.#expectedOwnerUid = expectedOwnerUid;
    this.#enforceOwnership = enforceOwnership;
  }

  #ensureRoot() {
    fs.mkdirSync(this.#root, { recursive: true, mode: 0o700 });
    const stat = fs.lstatSync(this.#root);
    assert(stat.isDirectory() && !stat.isSymbolicLink(), 'FIRMWARE_JOURNAL_ROOT_UNSAFE', 'firmware journal root must be a real directory');
    assert((stat.mode & 0o077) === 0, 'FIRMWARE_JOURNAL_ROOT_MODE_UNSAFE', 'firmware journal root must not be accessible to group/world');
    if (this.#enforceOwnership && this.#expectedOwnerUid !== null && typeof stat.uid === 'number') {
      assert(stat.uid === this.#expectedOwnerUid, 'FIRMWARE_JOURNAL_OWNER_INVALID', 'firmware journal root owner is not trusted');
    }
  }

  #file(transactionId) {
    assert(typeof transactionId === 'string' && TRANSACTION_ID.test(transactionId), 'FIRMWARE_TRANSACTION_ID_INVALID', 'firmware transaction id is invalid');
    const file = path.resolve(this.#root, `${transactionId}.json`);
    assert(path.dirname(file) === this.#root, 'FIRMWARE_JOURNAL_PATH_ESCAPE', 'firmware journal path escaped its root');
    return file;
  }

  write(entry) {
    assert(object(entry) && entry.schema === JOURNAL_SCHEMA, 'FIRMWARE_JOURNAL_ENTRY_INVALID', 'firmware journal entry is invalid');
    this.#ensureRoot();
    const target = this.#file(entry.transactionId);
    const temporary = `${target}.${crypto.randomUUID()}.tmp`;
    const serialized = `${JSON.stringify(entry, null, 2)}\n`;
    assert(Buffer.byteLength(serialized) <= MAX_JOURNAL_BYTES, 'FIRMWARE_JOURNAL_TOO_LARGE', 'firmware journal entry exceeds maximum size');
    fs.writeFileSync(temporary, serialized, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
    fs.chmodSync(temporary, 0o600);
    const fd = fs.openSync(temporary, 'r');
    try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temporary, target);
    return target;
  }

  read(transactionId) {
    this.#ensureRoot();
    const file = this.#file(transactionId);
    const stat = fs.lstatSync(file);
    assert(stat.isFile() && !stat.isSymbolicLink() && (stat.mode & 0o077) === 0 && stat.size <= MAX_JOURNAL_BYTES, 'FIRMWARE_JOURNAL_FILE_UNSAFE', 'firmware journal file is unsafe');
    const entry = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert(entry?.schema === JOURNAL_SCHEMA && entry.transactionId === transactionId, 'FIRMWARE_JOURNAL_BINDING_INVALID', 'firmware journal identity mismatch');
    assert(entry.planDigest === entry.plan?.digest, 'FIRMWARE_JOURNAL_DIGEST_MISMATCH', 'firmware journal plan digest mismatch');
    assertPlan(entry.plan);
    return entry;
  }

  list() {
    this.#ensureRoot();
    return fs.readdirSync(this.#root)
      .filter(name => /^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}\.json$/.test(name))
      .sort()
      .map(name => this.read(name.slice(0, -5)));
  }
}

export class FirmwareUpdateTransactionService {
  #inventory;
  #binary;
  #runner;
  #journal;
  #clock;
  #idFactory;
  #expectedOwnerUid;
  #enforceBinaryTrust;

  constructor({
    inventoryService = new FwupdLvfsService(),
    binary = DEFAULT_BINARY,
    runner = defaultRunner,
    journal = new FileFirmwareUpdateJournal(),
    clock = () => new Date().toISOString(),
    idFactory = () => crypto.randomUUID(),
    expectedOwnerUid = 0,
    enforceBinaryTrust = true
  } = {}) {
    assert(typeof inventoryService?.inventory === 'function', 'FIRMWARE_INVENTORY_SERVICE_REQUIRED', 'fwupd/LVFS inventory service is required');
    assert(binary === DEFAULT_BINARY, 'FIRMWARE_BINARY_NOT_ALLOWLISTED', 'firmware mutation is pinned to /usr/bin/fwupdmgr');
    assert(typeof runner === 'function', 'FIRMWARE_RUNNER_REQUIRED', 'firmware runner must be a function');
    assert(typeof journal?.write === 'function' && typeof journal?.read === 'function' && typeof journal?.list === 'function', 'FIRMWARE_JOURNAL_REQUIRED', 'firmware journal is required');
    this.#inventory = inventoryService;
    this.#binary = binary;
    this.#runner = runner;
    this.#journal = journal;
    this.#clock = clock;
    this.#idFactory = idFactory;
    this.#expectedOwnerUid = expectedOwnerUid;
    this.#enforceBinaryTrust = enforceBinaryTrust;
  }

  async #assertBinaryTrust() {
    if (!this.#enforceBinaryTrust) return true;
    const stat = await fs.promises.stat(this.#binary);
    const real = await fs.promises.realpath(this.#binary);
    assert(real === this.#binary, 'FIRMWARE_BINARY_SYMLINKED', 'fwupdmgr must resolve exactly to the allowlisted distro binary');
    assert(stat.isFile(), 'FIRMWARE_BINARY_INVALID', 'fwupdmgr must be a regular file');
    assert((stat.mode & 0o111) !== 0, 'FIRMWARE_BINARY_NOT_EXECUTABLE', 'fwupdmgr must be executable');
    assert((stat.mode & 0o022) === 0, 'FIRMWARE_BINARY_WRITABLE', 'fwupdmgr must not be writable by group or others');
    if (this.#expectedOwnerUid !== null && typeof stat.uid === 'number') {
      assert(stat.uid === this.#expectedOwnerUid, 'FIRMWARE_BINARY_OWNER_INVALID', 'fwupdmgr owner does not match the trusted UID');
    }
    return true;
  }

  async plan(candidate) {
    const requested = candidateBinding(candidate);
    const inventory = await this.#inventory.inventory();
    assertSafeFwupdLvfsInventory(inventory);
    assert(inventory.available === true, 'FIRMWARE_PROVIDER_UNAVAILABLE', 'fwupd/LVFS is unavailable');
    assert(inventory.probe?.trustedBinary === true, 'FIRMWARE_INVENTORY_BINARY_UNTRUSTED', 'fwupd inventory was not produced by a trusted binary');
    const matches = candidatesForDevice(inventory, requested.deviceId);
    assert(matches.length === 1, 'FIRMWARE_UPDATE_AMBIGUOUS', 'firmware update is allowed only when exactly one LVFS update candidate exists for the device');
    const live = candidateBinding(matches[0]);
    assert(stableStringify(live) === stableStringify(requested), 'FIRMWARE_CANDIDATE_STALE', 'selected firmware candidate no longer matches live fwupd/LVFS metadata');

    const core = {
      schema: PLAN_SCHEMA,
      generatedAt: this.#clock(),
      provider: 'fwupd-lvfs',
      remoteId: 'lvfs',
      binding: live,
      execution: {
        binary: DEFAULT_BINARY,
        argv: ['update', live.deviceId, '--assume-yes', '--no-reboot-check', '--no-unreported-check', '--json'],
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
      recovery: 'operator-review-after-ambiguous-failure'
    };
    return Object.freeze({ ...core, digest: digest(core) });
  }

  async update(candidate, context = {}) {
    const plan = context?.plan ?? await this.plan(candidate);
    const binding = assertPlan(plan);
    const confirmationDigest = context?.confirmationDigest;
    assert(typeof confirmationDigest === 'string' && confirmationDigest === plan.digest, 'FIRMWARE_CONFIRMATION_REQUIRED', 'exact firmware plan digest confirmation is required');
    const active = this.#journal.list().filter(entry => ACTIVE_STATES.has(entry.state));
    assert(active.length === 0, 'FIRMWARE_TRANSACTION_BUSY', 'another firmware mutation transaction is active');

    const liveInventory = await this.#inventory.inventory();
    assertSafeFwupdLvfsInventory(liveInventory);
    assert(liveInventory.available === true, 'FIRMWARE_PROVIDER_UNAVAILABLE', 'fwupd/LVFS became unavailable before mutation');
    assert(liveInventory.probe?.trustedBinary === true, 'FIRMWARE_INVENTORY_BINARY_UNTRUSTED', 'fwupd inventory binary trust was lost before mutation');
    const matches = candidatesForDevice(liveInventory, binding.deviceId);
    assert(matches.length === 1, 'FIRMWARE_UPDATE_AMBIGUOUS', 'live firmware candidate set changed before mutation');
    const liveBinding = candidateBinding(matches[0]);
    assert(stableStringify(liveBinding) === stableStringify(binding), 'FIRMWARE_PLAN_STALE', 'firmware metadata changed after review; regenerate the plan');

    await this.#assertBinaryTrust();

    const transactionId = this.#idFactory();
    assert(typeof transactionId === 'string' && TRANSACTION_ID.test(transactionId), 'FIRMWARE_TRANSACTION_ID_INVALID', 'firmware transaction id is invalid');
    const now = this.#clock();
    let entry = {
      schema: JOURNAL_SCHEMA,
      transactionId,
      state: 'prepared',
      createdAt: now,
      updatedAt: now,
      actorId: context?.actorId ?? null,
      plan: clone(plan),
      planDigest: plan.digest,
      recovery: {
        automaticRollback: false,
        rebootPerformed: false,
        operatorReviewRequired: false,
        note: 'Firmware downgrade/rollback is device-specific and is never promised automatically.'
      },
      error: null
    };
    this.#journal.write(entry);

    try {
      entry = { ...entry, state: 'executing', updatedAt: this.#clock() };
      this.#journal.write(entry);
      const result = await this.#runner(this.#binary, plan.execution.argv, {
        shell: false,
        timeout: 30 * 60 * 1000,
        maxBuffer: MAX_OUTPUT_BYTES,
        windowsHide: true,
        env: { PATH: '/usr/sbin:/usr/bin:/sbin:/bin', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' }
      });
      assert(Number(result?.code ?? 0) === 0, 'FIRMWARE_UPDATE_COMMAND_FAILED', 'fwupdmgr update did not complete successfully');
      const status = binding.requiresReboot ? 'staged-reboot-required' : 'committed';
      entry = {
        ...entry,
        state: status,
        updatedAt: this.#clock(),
        recovery: {
          ...entry.recovery,
          operatorReviewRequired: status === 'staged-reboot-required',
          note: status === 'staged-reboot-required'
            ? 'Firmware was staged by fwupd. Reboot/power-cycle remains a separate explicit operator action and post-boot result must be verified.'
            : 'Firmware command completed without an LVFS reboot flag; post-update inventory/history should still be verified.'
        }
      };
      this.#journal.write(entry);
      return Object.freeze({
        schema: RESULT_SCHEMA,
        transactionId,
        status,
        deviceId: binding.deviceId,
        fromVersion: binding.currentVersion,
        targetVersion: binding.targetVersion,
        planDigest: plan.digest,
        rebootRequired: binding.requiresReboot,
        rebootPerformed: false,
        automaticRollback: false,
        verificationRequired: true
      });
    } catch (error) {
      entry = {
        ...entry,
        state: 'failed-needs-recovery',
        updatedAt: this.#clock(),
        error: safeError(error),
        recovery: { ...entry.recovery, operatorReviewRequired: true }
      };
      this.#journal.write(entry);
      throw error;
    }
  }

  inspectRecovery() {
    return this.#journal.list()
      .filter(entry => ['prepared', 'executing', 'failed-needs-recovery', 'staged-reboot-required'].includes(entry.state))
      .map(entry => ({
        schema: 'swir.firmware-recovery-assessment/0.1',
        transactionId: entry.transactionId,
        state: entry.state,
        deviceId: entry.plan?.binding?.deviceId ?? null,
        targetVersion: entry.plan?.binding?.targetVersion ?? null,
        planDigest: entry.planDigest,
        automaticRollback: false,
        rebootPerformed: false,
        operatorReviewRequired: entry.state !== 'prepared'
      }));
  }
}

export const FirmwareUpdateTransactionPolicy = Object.freeze({
  schema: 'swir.firmware-update-transaction-policy/0.1',
  provider: 'fwupd-lvfs',
  trustedRemoteId: 'lvfs',
  binary: DEFAULT_BINARY,
  commands: Object.freeze(['update']),
  exactDeviceBinding: true,
  exactPlanDigestConfirmation: true,
  liveMetadataRevalidation: true,
  exactlyOneCandidateRequired: true,
  arbitraryFirmwareUrlOrFile: false,
  force: false,
  allowOlder: false,
  allowReinstall: false,
  noSafetyCheck: false,
  noRebootCheck: true,
  automaticReboot: false,
  automaticRollback: false,
  durableJournalBeforeMutation: true,
  shell: false
});
