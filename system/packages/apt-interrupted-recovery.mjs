import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';
import {
  digestPackagePlan,
  validatePackageHealth,
  validatePackageSnapshot,
  validateSystemPackagePlan
} from './package-transaction-service.mjs';
import {
  DistributionPackageSnapshotProvider,
  NativePackageHealthVerifier
} from './distribution-package-state.mjs';
import { createSystemPackageSecurityBoundary } from '../security/system-package-security-boundary.mjs';

const TRANSACTION_ID = /^[A-Za-z0-9._-]{8,128}$/;
const RECOVERABLE_STATES = new Set(['mutating', 'verifying', 'failed-needs-recovery']);
const MAX_JOURNAL_BYTES = 1024 * 1024;
const SAFE_ENVIRONMENT = Object.freeze({
  PATH: '/usr/sbin:/usr/bin:/sbin:/bin',
  LANG: 'C.UTF-8',
  LC_ALL: 'C.UTF-8',
  DEBIAN_FRONTEND: 'noninteractive'
});

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'AptInterruptedRecoveryError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function clone(value) {
  return value == null ? value : JSON.parse(JSON.stringify(value));
}

function safeError(error) {
  return {
    code: typeof error?.code === 'string' ? error.code : 'APT_RECOVERY_FAILED',
    message: typeof error?.message === 'string' ? error.message.slice(0, 500) : 'APT recovery failed'
  };
}

function ensureSafeDirectory(directory) {
  fs.mkdirSync(directory, { recursive: true, mode: 0o700 });
  const stat = fs.lstatSync(directory);
  assert(stat.isDirectory() && !stat.isSymbolicLink(), 'UNSAFE_JOURNAL_DIRECTORY', 'package journal directory must be a real directory');
  assert((stat.mode & 0o022) === 0, 'UNSAFE_JOURNAL_DIRECTORY_MODE', 'package journal directory must not be group/world writable');
}

function readJournal(filePath) {
  const stat = fs.lstatSync(filePath);
  assert(stat.isFile() && !stat.isSymbolicLink(), 'UNSAFE_JOURNAL_FILE', 'package journal must be a regular file');
  assert((stat.mode & 0o022) === 0, 'UNSAFE_JOURNAL_FILE_MODE', 'package journal must not be group/world writable');
  assert(stat.size <= MAX_JOURNAL_BYTES, 'JOURNAL_TOO_LARGE', 'package transaction journal exceeds size limit');
  const record = JSON.parse(fs.readFileSync(filePath, 'utf8'));
  assert(record?.schema === 'swir.system-package-transaction/0.1', 'INVALID_JOURNAL_SCHEMA', 'unsupported package transaction journal schema');
  assert(typeof record.id === 'string' && TRANSACTION_ID.test(record.id), 'INVALID_TRANSACTION_ID', 'invalid package transaction id');
  assert(path.basename(filePath) === `${record.id}.json`, 'JOURNAL_ID_PATH_MISMATCH', 'journal id does not match file name');
  assert(record.plan && typeof record.plan === 'object' && !Array.isArray(record.plan), 'INVALID_JOURNAL', 'package journal requires original plan');
  assert(record.planDigest === digestPackagePlan(record.plan), 'JOURNAL_PLAN_DIGEST_MISMATCH', 'package journal plan digest mismatch');
  return record;
}

function atomicWriteJournal(directory, record) {
  assert(typeof record?.id === 'string' && TRANSACTION_ID.test(record.id), 'INVALID_TRANSACTION_ID', 'invalid package transaction id');
  ensureSafeDirectory(directory);
  const target = path.join(directory, `${record.id}.json`);
  const temporary = path.join(directory, `.${record.id}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`);
  const data = `${JSON.stringify(record, null, 2)}\n`;
  assert(Buffer.byteLength(data) <= MAX_JOURNAL_BYTES, 'JOURNAL_TOO_LARGE', 'package transaction journal exceeds size limit');
  fs.writeFileSync(temporary, data, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
  const fd = fs.openSync(temporary, 'r');
  try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  fs.renameSync(temporary, target);
  try {
    const directoryFd = fs.openSync(directory, 'r');
    try { fs.fsyncSync(directoryFd); } finally { fs.closeSync(directoryFd); }
  } catch {
    // Some filesystems do not expose directory fsync. Atomic rename still applies.
  }
}

function defaultRunner(file, args, { timeoutMs = 30_000, maxOutputBytes = 128 * 1024 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(file, args, {
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...SAFE_ENVIRONMENT }
    });
    let stdout = '';
    let stderr = '';
    let bytes = 0;
    let settled = false;
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };
    const collect = (kind, chunk) => {
      const text = Buffer.isBuffer(chunk) ? chunk.toString('utf8') : String(chunk);
      bytes += Buffer.byteLength(text);
      if (bytes > maxOutputBytes) {
        child.kill('SIGKILL');
        finish(reject, Object.assign(new Error('APT recovery probe output limit exceeded'), { code: 'RECOVERY_PROBE_OUTPUT_LIMIT' }));
        return;
      }
      if (kind === 'stdout') stdout += text;
      else stderr += text;
    };
    child.stdout?.on('data', chunk => collect('stdout', chunk));
    child.stderr?.on('data', chunk => collect('stderr', chunk));
    child.on('error', error => finish(reject, error));
    child.on('close', (exitCode, signal) => finish(resolve, { exitCode, signal: signal || null, stdout, stderr }));
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      finish(reject, Object.assign(new Error('APT recovery probe timed out'), { code: 'RECOVERY_PROBE_TIMEOUT' }));
    }, timeoutMs);
    timer.unref?.();
  });
}

function assertTrustedBinary(filePath) {
  const stat = fs.lstatSync(filePath);
  assert(stat.isFile() && !stat.isSymbolicLink(), 'UNTRUSTED_RECOVERY_BINARY', `${filePath} must be a regular non-symlink file`);
  assert(stat.uid === 0, 'UNTRUSTED_RECOVERY_BINARY_OWNER', `${filePath} must be root-owned`);
  assert((stat.mode & 0o022) === 0, 'UNTRUSTED_RECOVERY_BINARY_MODE', `${filePath} must not be group/world writable`);
}

export class AptDatabaseConsistencyProbe {
  #runner;

  constructor({ runner = defaultRunner } = {}) {
    assert(typeof runner === 'function', 'INVALID_RUNNER', 'APT consistency probe runner must be a function');
    this.#runner = runner;
  }

  async verify() {
    assertTrustedBinary('/usr/bin/dpkg');
    assertTrustedBinary('/usr/bin/apt-get');
    const dpkgAudit = await this.#runner('/usr/bin/dpkg', ['--audit'], { timeoutMs: 30_000, maxOutputBytes: 128 * 1024 });
    const aptCheck = await this.#runner('/usr/bin/apt-get', ['-o', 'Debug::NoLocking=1', 'check'], { timeoutMs: 60_000, maxOutputBytes: 128 * 1024 });
    const dpkgClean = dpkgAudit?.exitCode === 0 && !dpkgAudit?.signal && String(dpkgAudit.stdout || '').trim() === '';
    const aptClean = aptCheck?.exitCode === 0 && !aptCheck?.signal;
    return {
      schema: 'swir.apt-database-consistency/0.1',
      healthy: dpkgClean && aptClean,
      mutationPerformed: false,
      checks: [
        { id: 'dpkg-audit', ok: dpkgClean, exitCode: Number.isInteger(dpkgAudit?.exitCode) ? dpkgAudit.exitCode : null, signal: dpkgAudit?.signal || null },
        { id: 'apt-get-check', ok: aptClean, exitCode: Number.isInteger(aptCheck?.exitCode) ? aptCheck.exitCode : null, signal: aptCheck?.signal || null }
      ]
    };
  }
}

function validateConsistency(result) {
  assert(result && typeof result === 'object' && !Array.isArray(result), 'INVALID_CONSISTENCY_RESULT', 'APT consistency probe must return an object');
  assert(result.schema === 'swir.apt-database-consistency/0.1', 'INVALID_CONSISTENCY_SCHEMA', 'APT consistency schema mismatch');
  assert(typeof result.healthy === 'boolean', 'INVALID_CONSISTENCY_RESULT', 'APT consistency result requires healthy boolean');
  assert(result.mutationPerformed === false, 'RECOVERY_MUTATION_FORBIDDEN', 'APT recovery consistency probe must remain read-only');
  assert(Array.isArray(result.checks) && result.checks.length >= 2, 'INVALID_CONSISTENCY_RESULT', 'APT consistency result requires probe checks');
  return result;
}

function desiredStateReached(plan, before, current) {
  if (plan.operation === 'install') return current.installed === true;
  if (plan.operation === 'remove') return current.installed === false;
  if (plan.operation === 'update') {
    if (before.installed !== true || current.installed !== true) return false;
    return typeof before.version === 'string' && typeof current.version === 'string' && before.version !== current.version;
  }
  return false;
}

function appendRecoveryState(record, state, clock, detail) {
  const next = clone(record);
  next.state = state;
  next.sequence = Number.isInteger(next.sequence) ? next.sequence + 1 : 1;
  next.updatedAt = clock();
  next.history = Array.isArray(next.history) ? next.history : [];
  next.history.push({ state, at: next.updatedAt, detail: clone(detail) });
  return next;
}

export class AptInterruptedTransactionRecoveryService {
  #journalDirectory;
  #authorizationBroker;
  #snapshotProvider;
  #healthVerifier;
  #consistencyProbe;
  #allowlistedRepositories;
  #clock;

  constructor({
    journalDirectory,
    authorizationBroker,
    snapshotProvider,
    healthVerifier,
    consistencyProbe,
    allowlistedRepositories = [],
    clock = () => new Date().toISOString()
  } = {}) {
    assert(typeof journalDirectory === 'string' && path.isAbsolute(journalDirectory), 'INVALID_JOURNAL_DIRECTORY', 'APT recovery journalDirectory must be absolute');
    assert(authorizationBroker && typeof authorizationBroker.authorize === 'function', 'MISSING_AUTHORIZATION_BROKER', 'authorizationBroker.authorize is required');
    assert(snapshotProvider && typeof snapshotProvider.capture === 'function', 'MISSING_SNAPSHOT_PROVIDER', 'snapshotProvider.capture is required');
    assert(healthVerifier && typeof healthVerifier.verify === 'function', 'MISSING_HEALTH_VERIFIER', 'healthVerifier.verify is required');
    assert(consistencyProbe && typeof consistencyProbe.verify === 'function', 'MISSING_CONSISTENCY_PROBE', 'consistencyProbe.verify is required');
    this.#journalDirectory = journalDirectory;
    this.#authorizationBroker = authorizationBroker;
    this.#snapshotProvider = snapshotProvider;
    this.#healthVerifier = healthVerifier;
    this.#consistencyProbe = consistencyProbe;
    this.#allowlistedRepositories = [...new Set(allowlistedRepositories.filter(value => typeof value === 'string' && value.length > 0))];
    this.#clock = clock;
    ensureSafeDirectory(journalDirectory);
  }

  async recoverPending(context = {}) {
    assert(context && typeof context === 'object' && !Array.isArray(context), 'INVALID_AUTHORIZATION_CONTEXT', 'recovery authorization context must be an object');
    const outcomes = [];
    const files = fs.readdirSync(this.#journalDirectory)
      .filter(name => /^[A-Za-z0-9._-]{8,128}\.json$/.test(name))
      .sort();

    for (const name of files) {
      const filePath = path.join(this.#journalDirectory, name);
      let record;
      try {
        record = readJournal(filePath);
      } catch (error) {
        outcomes.push({ id: name.replace(/\.json$/, ''), status: 'corrupt', error: safeError(error) });
        continue;
      }
      if (!RECOVERABLE_STATES.has(record.state)) continue;

      try {
        const validated = validateSystemPackagePlan(record.plan, { allowlistedRepositories: this.#allowlistedRepositories });
        assert(validated.manager === 'apt', 'UNSUPPORTED_RECOVERY_MANAGER', 'state reconciliation is currently limited to APT');
        const before = validatePackageSnapshot(record.snapshot, {
          manager: 'apt', packageName: validated.packageName, packageId: record.plan.package.id
        });
        const authorization = await this.#authorizationBroker.authorize({
          schema: 'swir.system-authorization-request/0.1',
          scope: 'packages.recover',
          planDigest: validated.planDigest,
          packageId: record.plan.package.id,
          operation: validated.operation,
          context: clone(context)
        });
        assert(authorization?.authorized === true, 'RECOVERY_AUTHORIZATION_DENIED', 'authorization denied for packages.recover');
        assert(typeof authorization.grantId === 'string' && authorization.grantId.length > 0, 'INVALID_RECOVERY_GRANT', 'recovery authorization must include grantId');
        assert(typeof authorization.actorId === 'string' && authorization.actorId.length > 0, 'INVALID_RECOVERY_GRANT', 'recovery authorization must include actorId');

        const current = validatePackageSnapshot(await this.#snapshotProvider.capture({
          manager: 'apt', operation: validated.operation, packageName: validated.packageName, packageId: record.plan.package.id
        }), {
          manager: 'apt', packageName: validated.packageName, packageId: record.plan.package.id
        });
        const consistency = validateConsistency(await this.#consistencyProbe.verify());
        const health = validatePackageHealth(await this.#healthVerifier.verify({
          transactionId: record.id,
          packageId: record.plan.package.id,
          packageName: validated.packageName,
          nativeEntryPoint: record.plan.package.nativeEntryPoint,
          operation: validated.operation,
          manager: 'apt'
        }), {
          packageId: record.plan.package.id,
          packageName: validated.packageName
        });
        const targetReached = desiredStateReached(record.plan, before, current);
        const commitSafe = targetReached && consistency.healthy === true && health.healthy === true;
        const reconciliation = {
          schema: 'swir.apt-interrupted-recovery/0.1',
          mode: 'read-only-state-reconciliation',
          recoveredAt: this.#clock(),
          authorization: {
            grantId: authorization.grantId,
            actorId: authorization.actorId,
            scope: 'packages.recover',
            planDigest: validated.planDigest
          },
          before: clone(before),
          current: clone(current),
          consistency: clone(consistency),
          health: clone(health),
          desiredStateReached: targetReached,
          packageMutationPerformedByRecovery: false,
          commitSafe
        };

        record.recovery = { ...(record.recovery || {}), reconciliation };
        record.health = clone(health);
        if (commitSafe) {
          record.error = null;
          record = appendRecoveryState(record, 'committed', this.#clock, {
            reason: 'interrupted APT transaction reconciled from verified live state',
            recoverySchema: reconciliation.schema,
            packageMutationPerformedByRecovery: false
          });
          atomicWriteJournal(this.#journalDirectory, record);
          outcomes.push({ id: record.id, status: 'committed', reconciled: true, mutationPerformed: false });
        } else {
          record.error = {
            code: 'RECOVERY_REQUIRES_MANUAL_INTERVENTION',
            message: 'APT state could not be safely reconciled; no automatic package mutation was attempted.'
          };
          record = appendRecoveryState(record, 'failed-needs-recovery', this.#clock, {
            reason: record.error.code,
            desiredStateReached: targetReached,
            consistencyHealthy: consistency.healthy,
            packageHealthy: health.healthy,
            packageMutationPerformedByRecovery: false
          });
          atomicWriteJournal(this.#journalDirectory, record);
          outcomes.push({ id: record.id, status: 'failed-needs-recovery', reconciled: false, mutationPerformed: false, error: clone(record.error) });
        }
      } catch (error) {
        outcomes.push({ id: record.id, status: 'blocked', error: safeError(error) });
      }
    }
    return outcomes;
  }

  readJournal(id) {
    assert(typeof id === 'string' && TRANSACTION_ID.test(id), 'INVALID_TRANSACTION_ID', 'invalid transaction id');
    return clone(readJournal(path.join(this.#journalDirectory, `${id}.json`)));
  }
}

export function createAptInterruptedTransactionRecoveryService({
  journalDirectory = '/var/lib/swir/package-transactions',
  repositoryPolicyPath = '/etc/swir/repository-trust-policy.json'
} = {}) {
  const security = createSystemPackageSecurityBoundary({ repositoryPolicyPath });
  return new AptInterruptedTransactionRecoveryService({
    journalDirectory,
    authorizationBroker: security.authorizationBroker,
    snapshotProvider: new DistributionPackageSnapshotProvider(),
    healthVerifier: new NativePackageHealthVerifier(),
    consistencyProbe: new AptDatabaseConsistencyProbe(),
    allowlistedRepositories: security.allowlistedRepositories
  });
}

export const AptInterruptedRecoveryPolicy = Object.freeze({
  schema: 'swir.apt-interrupted-recovery/0.1',
  packageManager: 'apt',
  authorizationScope: 'packages.recover',
  planDigestBinding: true,
  reconciliationOnly: true,
  automaticInversePackageMutation: false,
  probes: ['dpkg --audit', 'apt-get -o Debug::NoLocking=1 check'],
  desiredStateVerification: true,
  nativeHealthVerification: true,
  shellExecution: false,
  inheritedEnvironment: false,
  failClosedOnAmbiguousState: true
});
