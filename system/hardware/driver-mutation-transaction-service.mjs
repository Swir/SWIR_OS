import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { assertSafeDriverPlan } from './driver-resolver.mjs';

const DEFAULT_JOURNAL_ROOT = '/var/lib/swir/transactions/drivers';
const JOURNAL_SCHEMA = 'swir.driver-mutation-transaction/0.1';
const TXID = /^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}$/;
const OPERATION_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
const PACKAGE_NAME = /^[A-Za-z0-9][A-Za-z0-9+._:@-]{0,127}$/;
const MAX_JOURNAL_BYTES = 1024 * 1024;
const TERMINAL_STATES = new Set(['committed', 'staged-reboot-required', 'failed-needs-recovery']);
const SUPPORTED_KINDS = new Set(['review-package', 'review-fwupd']);

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'DriverMutationTransactionError';
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

function safeError(error) {
  return {
    code: typeof error?.code === 'string' ? error.code.slice(0, 128) : 'DRIVER_MUTATION_FAILED',
    message: typeof error?.message === 'string' ? error.message.slice(0, 1000) : 'driver mutation failed'
  };
}

function sourceClasses(operation) {
  return new Set((Array.isArray(operation?.sources) ? operation.sources : []).map(source => source?.class).filter(Boolean));
}

function findOperation(driverPlan, operationId) {
  assertSafeDriverPlan(driverPlan);
  assert(typeof operationId === 'string' && OPERATION_ID.test(operationId), 'INVALID_DRIVER_OPERATION_ID', 'driver operation id is invalid');
  const operation = (driverPlan.operations || []).find(item => item?.id === operationId);
  assert(operation, 'DRIVER_OPERATION_NOT_FOUND', 'driver operation was not found in the trusted preview plan');
  assert(operation.state === 'proposed', 'DRIVER_OPERATION_STATE_INVALID', 'driver operation must remain proposed before mutation');
  assert(operation.requiresPrivilege === true, 'DRIVER_OPERATION_NOT_PRIVILEGED', 'selected driver operation is not a privileged mutation');
  assert(SUPPORTED_KINDS.has(operation.kind), 'DRIVER_OPERATION_UNSUPPORTED', 'direct kernel-module mutation is not supported by this transaction service');
  assert(operation.rollback !== 'not-required', 'DRIVER_ROLLBACK_POLICY_REQUIRED', 'privileged driver mutation requires rollback/recovery handling');
  return operation;
}

function validatePackageBinding(operation, packagePlan) {
  assert(operation.kind === 'review-package', 'DRIVER_OPERATION_KIND_MISMATCH', 'selected operation is not a package-backed driver action');
  assert(object(packagePlan) && packagePlan.schema === 'swir.system-package-plan/0.1', 'DRIVER_PACKAGE_PLAN_INVALID', 'driver package mutation requires a system package plan');
  assert(packagePlan.provider === 'swir.package.system' && packagePlan.executionClass === 'linux-native', 'DRIVER_PACKAGE_PROVIDER_INVALID', 'driver package mutation must use the System package provider');
  const packageName = packagePlan.package?.sourceRef;
  assert(typeof packageName === 'string' && PACKAGE_NAME.test(packageName), 'DRIVER_PACKAGE_NAME_INVALID', 'driver package name is invalid');
  assert((operation.packageCandidates || []).includes(packageName), 'DRIVER_PACKAGE_BINDING_MISMATCH', 'package plan is not bound to a package candidate from the selected driver operation');
  const classes = sourceClasses(operation);
  assert(classes.has('distribution-repository') || classes.has('vendor-official-repository'), 'DRIVER_PACKAGE_SOURCE_UNTRUSTED', 'driver package operation has no approved repository source class');
  assert(packagePlan.transaction?.journalRequired === true, 'DRIVER_CHILD_JOURNAL_REQUIRED', 'package child transaction must require its own durable journal');
  return { packageName };
}

function validateFirmwareBinding(operation, candidate) {
  assert(operation.kind === 'review-fwupd', 'DRIVER_OPERATION_KIND_MISMATCH', 'selected operation is not an fwupd-backed driver action');
  assert(object(candidate), 'DRIVER_FIRMWARE_CANDIDATE_INVALID', 'firmware candidate is required');
  assert(candidate.remoteId === 'lvfs' && candidate?.source?.class === 'fwupd-lvfs' && candidate?.source?.repositoryId === 'lvfs', 'DRIVER_FIRMWARE_SOURCE_UNTRUSTED', 'firmware candidate must be sourced from LVFS through fwupd');
  assert(candidate.trustedSource === true && candidate.directDownloadUrlExposed === false && candidate.mutationAuthorized === false, 'DRIVER_FIRMWARE_TRUST_INVALID', 'firmware candidate does not satisfy trusted discovery boundaries');
  assert(sourceClasses(operation).has('fwupd-lvfs'), 'DRIVER_FIRMWARE_PLAN_SOURCE_MISMATCH', 'driver operation does not authorize the fwupd/LVFS source class');
  assert(typeof candidate.deviceId === 'string' && candidate.deviceId.length > 0, 'DRIVER_FIRMWARE_DEVICE_INVALID', 'firmware candidate device id is required');
  return { deviceId: candidate.deviceId, targetVersion: candidate.version ?? null };
}

export class FileDriverMutationJournal {
  #root;
  #expectedOwnerUid;
  #enforceOwnership;

  constructor({ root = DEFAULT_JOURNAL_ROOT, expectedOwnerUid = 0, enforceOwnership = true } = {}) {
    assert(typeof root === 'string' && path.isAbsolute(root), 'DRIVER_JOURNAL_ROOT_INVALID', 'driver journal root must be absolute');
    this.#root = path.resolve(root);
    this.#expectedOwnerUid = expectedOwnerUid;
    this.#enforceOwnership = enforceOwnership;
  }

  get root() { return this.#root; }

  #file(transactionId) {
    assert(typeof transactionId === 'string' && TXID.test(transactionId), 'DRIVER_TRANSACTION_ID_INVALID', 'driver transaction id is invalid');
    const file = path.resolve(this.#root, `${transactionId}.json`);
    assert(path.dirname(file) === this.#root, 'DRIVER_JOURNAL_PATH_ESCAPE', 'driver journal path escaped its root');
    return file;
  }

  #ensureRoot() {
    fs.mkdirSync(this.#root, { recursive: true, mode: 0o700 });
    const stat = fs.lstatSync(this.#root);
    assert(stat.isDirectory() && !stat.isSymbolicLink(), 'DRIVER_JOURNAL_ROOT_UNSAFE', 'driver journal root must be a real directory');
    assert((stat.mode & 0o077) === 0, 'DRIVER_JOURNAL_ROOT_MODE_UNSAFE', 'driver journal root must not be accessible to group/world');
    if (this.#enforceOwnership && this.#expectedOwnerUid !== null && typeof stat.uid === 'number') {
      assert(stat.uid === this.#expectedOwnerUid, 'DRIVER_JOURNAL_OWNER_INVALID', 'driver journal root owner is not trusted');
    }
  }

  write(entry) {
    assert(object(entry) && entry.schema === JOURNAL_SCHEMA, 'DRIVER_JOURNAL_ENTRY_INVALID', 'driver journal entry is invalid');
    this.#ensureRoot();
    const target = this.#file(entry.transactionId);
    const temporary = `${target}.${crypto.randomUUID()}.tmp`;
    const serialized = `${JSON.stringify(entry, null, 2)}\n`;
    assert(Buffer.byteLength(serialized) <= MAX_JOURNAL_BYTES, 'DRIVER_JOURNAL_TOO_LARGE', 'driver journal entry exceeds the maximum size');
    fs.writeFileSync(temporary, serialized, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
    fs.chmodSync(temporary, 0o600);
    const fd = fs.openSync(temporary, 'r');
    try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
    fs.renameSync(temporary, target);
    const stat = fs.lstatSync(target);
    assert(stat.isFile() && !stat.isSymbolicLink() && (stat.mode & 0o077) === 0, 'DRIVER_JOURNAL_FILE_UNSAFE', 'driver journal file is unsafe');
    return target;
  }

  read(transactionId) {
    this.#ensureRoot();
    const file = this.#file(transactionId);
    const stat = fs.lstatSync(file);
    assert(stat.isFile() && !stat.isSymbolicLink() && (stat.mode & 0o077) === 0 && stat.size <= MAX_JOURNAL_BYTES, 'DRIVER_JOURNAL_FILE_UNSAFE', 'driver journal file is unsafe');
    const entry = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert(entry?.schema === JOURNAL_SCHEMA && entry.transactionId === transactionId, 'DRIVER_JOURNAL_BINDING_INVALID', 'driver journal identity is invalid');
    assert(entry.requestDigest === digest(entry.request), 'DRIVER_JOURNAL_DIGEST_MISMATCH', 'driver journal request digest mismatch');
    return entry;
  }

  list() {
    this.#ensureRoot();
    return fs.readdirSync(this.#root).filter(name => /^[A-Za-z0-9][A-Za-z0-9._:-]{7,159}\.json$/.test(name)).sort().map(name => this.read(name.slice(0, -5)));
  }
}

export class DriverMutationTransactionService {
  #packageTransactions;
  #firmwareTransactions;
  #journal;
  #clock;
  #idFactory;

  constructor({ packageTransactions, firmwareTransactions, journal = new FileDriverMutationJournal(), clock = () => new Date().toISOString(), idFactory = () => crypto.randomUUID() } = {}) {
    assert(typeof packageTransactions?.execute === 'function', 'DRIVER_PACKAGE_TRANSACTION_SERVICE_REQUIRED', 'packageTransactions.execute is required');
    assert(typeof firmwareTransactions?.update === 'function', 'DRIVER_FIRMWARE_TRANSACTION_SERVICE_REQUIRED', 'firmwareTransactions.update is required');
    assert(typeof journal?.write === 'function' && typeof journal?.read === 'function' && typeof journal?.list === 'function', 'DRIVER_JOURNAL_REQUIRED', 'driver mutation journal is required');
    this.#packageTransactions = packageTransactions;
    this.#firmwareTransactions = firmwareTransactions;
    this.#journal = journal;
    this.#clock = clock;
    this.#idFactory = idFactory;
  }

  async execute({ driverPlan, operationId, packagePlan = null, firmwareCandidate = null } = {}, context = {}) {
    const operation = findOperation(driverPlan, operationId);
    const binding = operation.kind === 'review-package'
      ? validatePackageBinding(operation, packagePlan)
      : validateFirmwareBinding(operation, firmwareCandidate);
    const request = {
      schema: 'swir.driver-mutation-request/0.1',
      driverPlanGeneratedAt: driverPlan.generatedAt,
      operation: clone(operation),
      binding: clone(binding),
      route: operation.kind === 'review-package' ? 'system-package-transaction' : 'fwupd-firmware-transaction'
    };
    const transactionId = this.#idFactory();
    assert(typeof transactionId === 'string' && TXID.test(transactionId), 'DRIVER_TRANSACTION_ID_INVALID', 'driver transaction id is invalid');
    const now = this.#clock();
    let entry = {
      schema: JOURNAL_SCHEMA,
      transactionId,
      state: 'prepared',
      createdAt: now,
      updatedAt: now,
      actorId: context.actorId ?? null,
      request,
      requestDigest: digest(request),
      child: null,
      recovery: { automaticMutation: false, childRecoveryRequired: true, operatorReviewRequired: false },
      error: null
    };
    this.#journal.write(entry);

    try {
      entry = { ...entry, state: 'delegating', updatedAt: this.#clock() };
      this.#journal.write(entry);
      if (operation.kind === 'review-package') {
        const child = await this.#packageTransactions.execute(packagePlan, context);
        assert(child?.schema === 'swir.system-package-transaction/0.1' && child?.state === 'committed', 'DRIVER_PACKAGE_CHILD_UNVERIFIED', 'package-backed driver transaction did not commit');
        entry = { ...entry, state: 'committed', updatedAt: this.#clock(), child: { class: 'package', transactionId: child.id, state: child.state, journalOwnedByChild: true }, recovery: { automaticMutation: false, childRecoveryRequired: false, operatorReviewRequired: false } };
      } else {
        const child = await this.#firmwareTransactions.update(firmwareCandidate, context);
        assert(child?.schema === 'swir.firmware-transaction-result/0.1' && ['committed', 'staged-reboot-required'].includes(child.status), 'DRIVER_FIRMWARE_CHILD_UNVERIFIED', 'firmware-backed driver transaction did not reach a verified state');
        entry = { ...entry, state: child.status === 'staged-reboot-required' ? 'staged-reboot-required' : 'committed', updatedAt: this.#clock(), child: { class: 'firmware', transactionId: child.transactionId, state: child.status, journalOwnedByChild: true }, recovery: { automaticMutation: false, childRecoveryRequired: child.status === 'staged-reboot-required', operatorReviewRequired: false } };
      }
      this.#journal.write(entry);
      return clone(entry);
    } catch (error) {
      entry = { ...entry, state: 'failed-needs-recovery', updatedAt: this.#clock(), error: safeError(error), recovery: { automaticMutation: false, childRecoveryRequired: true, operatorReviewRequired: true } };
      this.#journal.write(entry);
      throw error;
    }
  }

  inspectRecovery() {
    return this.#journal.list().filter(entry => !TERMINAL_STATES.has(entry.state) || entry.state === 'failed-needs-recovery' || entry.state === 'staged-reboot-required').map(entry => ({
      schema: 'swir.driver-mutation-recovery-assessment/0.1',
      transactionId: entry.transactionId,
      state: entry.state,
      operationId: entry.request?.operation?.id ?? null,
      route: entry.request?.route ?? null,
      child: clone(entry.child),
      automaticMutation: false,
      operatorReviewRequired: entry.recovery?.operatorReviewRequired === true,
      childRecoveryRequired: entry.recovery?.childRecoveryRequired === true
    }));
  }
}

export const DriverMutationTransactionPolicy = Object.freeze({
  schema: 'swir.driver-mutation-transaction-policy/0.1',
  supportedDriverOperationKinds: Object.freeze([...SUPPORTED_KINDS]),
  directKernelModuleMutation: false,
  arbitraryDriverDownloads: false,
  windowsKernelDriversAsLinuxDrivers: false,
  trustedPackageTransactionsOnly: true,
  trustedFwupdLvfsTransactionsOnly: true,
  parentJournalBeforeDelegation: true,
  childJournalRequired: true,
  automaticMutation: false,
  operatorRecoveryOnAmbiguousFailure: true
});
