import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { assertVendorRepositoryTransactionBinding } from './vendor-repository-transaction-binding.mjs';

const PLAN_SCHEMA = 'swir.vendor-repository-activation-plan/0.1';
const JOURNAL_SCHEMA = 'swir.vendor-repository-activation-transaction/0.1';
const DEFAULT_SOURCE_ROOT = '/etc/apt/sources.list.d';
const DEFAULT_JOURNAL_ROOT = '/var/lib/swir/transactions/vendor-repositories';
const HEX40 = /^[A-F0-9]{40}$/;
const HEX64 = /^[a-f0-9]{64}$/;
const SAFE_ID = /^[A-Za-z0-9][A-Za-z0-9._+:-]{0,127}$/;
const MAX_SOURCE_BYTES = 64 * 1024;
const MAX_JOURNAL_BYTES = 1024 * 1024;
const TERMINAL_STATES = new Set(['committed', 'rolled-back', 'aborted', 'failed-needs-recovery']);

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'VendorRepositoryActivationError';
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
  return crypto.createHash('sha256').update(typeof value === 'string' ? value : stableStringify(value), 'utf8').digest('hex');
}

function mapAptArchitecture(value) {
  const raw = String(value || '').trim().toLowerCase();
  if (raw === 'x86_64' || raw === 'x64') return 'amd64';
  if (raw === 'aarch64') return 'arm64';
  assert(/^[a-z0-9][a-z0-9._-]{0,31}$/.test(raw), 'ACTIVATION_ARCH_INVALID', 'repository architecture is invalid');
  return raw;
}

function safeRepositoryFileName(repositoryId) {
  assert(typeof repositoryId === 'string' && SAFE_ID.test(repositoryId), 'ACTIVATION_REPOSITORY_ID_INVALID', 'repository id is invalid');
  return `swir-vendor-${repositoryId.replace(/[^A-Za-z0-9._-]/g, '_')}.sources`;
}

function normalizeRoot(root) {
  assert(typeof root === 'string' && path.isAbsolute(root), 'ACTIVATION_SOURCE_ROOT_INVALID', 'APT source root must be absolute');
  return path.resolve(root);
}

function sourcePathFor(root, repositoryId) {
  const resolvedRoot = normalizeRoot(root);
  const target = path.resolve(resolvedRoot, safeRepositoryFileName(repositoryId));
  assert(path.dirname(target) === resolvedRoot, 'ACTIVATION_SOURCE_PATH_ESCAPE', 'APT source path escaped its trusted root');
  return target;
}

function sourceDocument(binding) {
  assertVendorRepositoryTransactionBinding(binding);
  const repository = binding.bound?.repository;
  const platform = binding.bound?.platform;
  const key = binding.bound?.key;
  assert(repository?.packageManager === 'apt', 'ACTIVATION_PACKAGE_MANAGER_INVALID', 'vendor repository activation currently supports apt only');
  assert(typeof repository.baseUrl === 'string' && repository.baseUrl.startsWith('https://'), 'ACTIVATION_URL_INVALID', 'vendor repository activation requires an HTTPS repository URL');
  assert(Array.isArray(repository.suites) && repository.suites.length > 0, 'ACTIVATION_SUITES_INVALID', 'vendor repository activation requires at least one suite');
  assert(Array.isArray(repository.components), 'ACTIVATION_COMPONENTS_INVALID', 'vendor repository components must be an array');
  assert(typeof key?.keyringPath === 'string' && key.keyringPath.startsWith('/usr/share/keyrings/') && key.keyringPath.endsWith('.gpg'), 'ACTIVATION_KEYRING_PATH_INVALID', 'vendor repository activation requires an existing trusted keyring path');
  assert(HEX40.test(String(key?.fingerprint || '').toUpperCase()), 'ACTIVATION_KEY_FINGERPRINT_INVALID', 'vendor repository activation requires a full signing-key fingerprint');

  const lines = [
    '# Managed by SWIR OS. Do not edit while a vendor repository transaction is active.',
    'Types: deb',
    `URIs: ${repository.baseUrl}`,
    `Suites: ${repository.suites.join(' ')}`
  ];
  if (repository.components.length) lines.push(`Components: ${repository.components.join(' ')}`);
  lines.push(`Architectures: ${mapAptArchitecture(platform?.architecture)}`);
  lines.push(`Signed-By: ${key.keyringPath}`);
  lines.push('Trusted: no');
  lines.push('Enabled: yes');
  return `${lines.join('\n')}\n`;
}

function validateUpdateCommand(command, sourcePath) {
  const expected = [
    'apt-get',
    '-o', `Dir::Etc::sourcelist=${sourcePath}`,
    '-o', 'Dir::Etc::sourceparts=-',
    '-o', 'APT::Get::List-Cleanup=0',
    'update'
  ];
  assert(Array.isArray(command) && stableStringify(command) === stableStringify(expected), 'ACTIVATION_COMMAND_MISMATCH', 'repository metadata refresh command is not the fixed trusted argv');
  return expected;
}

export function buildVendorRepositoryActivationPlan(binding, { sourceRoot = DEFAULT_SOURCE_ROOT, now = new Date() } = {}) {
  assertVendorRepositoryTransactionBinding(binding);
  const current = now instanceof Date ? new Date(now.getTime()) : new Date(now);
  assert(Number.isFinite(current.getTime()), 'ACTIVATION_CLOCK_INVALID', 'activation planning requires a valid current time');
  const validUntil = Date.parse(binding.bound?.metadata?.effectiveValidUntil);
  assert(Number.isFinite(validUntil) && validUntil >= current.getTime(), 'ACTIVATION_EVIDENCE_EXPIRED', 'vendor repository qualification evidence expired before activation');

  const sourcePath = sourcePathFor(sourceRoot, binding.bound.repository.id);
  const content = sourceDocument(binding);
  assert(Buffer.byteLength(content) <= MAX_SOURCE_BYTES, 'ACTIVATION_SOURCE_TOO_LARGE', 'APT source document exceeds the verified size bound');
  const scope = Object.freeze({
    bindingDigest: binding.bindingDigest,
    repositoryId: binding.bound.repository.id,
    sourcePath,
    sourceSha256: digest(content),
    keyringPath: binding.bound.key.keyringPath,
    keyFingerprint: String(binding.bound.key.fingerprint).toUpperCase(),
    evidenceValidUntil: binding.bound.metadata.effectiveValidUntil,
    architecture: mapAptArchitecture(binding.bound.platform.architecture)
  });
  const activationDigest = digest(scope);
  const command = validateUpdateCommand([
    'apt-get', '-o', `Dir::Etc::sourcelist=${sourcePath}`, '-o', 'Dir::Etc::sourceparts=-', '-o', 'APT::Get::List-Cleanup=0', 'update'
  ], sourcePath);

  return Object.freeze({
    schema: PLAN_SCHEMA,
    mode: 'preview',
    readOnly: true,
    autoExecutable: false,
    repositoryEnablementAuthorized: false,
    requiresPrivilege: true,
    requiresExplicitConfirmation: true,
    bindingDigest: binding.bindingDigest,
    activationDigest,
    repositoryId: binding.bound.repository.id,
    source: Object.freeze({ path: sourcePath, content, sha256: scope.sourceSha256 }),
    keyring: Object.freeze({ path: scope.keyringPath, fingerprint: scope.keyFingerprint }),
    evidenceValidUntil: scope.evidenceValidUntil,
    updateCommand: Object.freeze(command),
    recovery: Object.freeze({ journalBeforeMutation: true, previousSourceCaptured: true, automaticPackageMutation: false, operatorRecoverySupported: true })
  });
}

export function assertVendorRepositoryActivationPlan(plan, { allowedSourceRoot = DEFAULT_SOURCE_ROOT, now = new Date() } = {}) {
  assert(object(plan) && plan.schema === PLAN_SCHEMA, 'ACTIVATION_PLAN_INVALID', 'vendor repository activation plan schema mismatch');
  assert(plan.mode === 'preview' && plan.readOnly === true && plan.autoExecutable === false, 'ACTIVATION_PLAN_MODE_INVALID', 'activation plan must remain preview/read-only/non-executable');
  assert(plan.repositoryEnablementAuthorized === false && plan.requiresPrivilege === true && plan.requiresExplicitConfirmation === true, 'ACTIVATION_PLAN_AUTH_INVALID', 'activation plan must require explicit privileged authorization');
  assert(HEX64.test(String(plan.bindingDigest || '')) && HEX64.test(String(plan.activationDigest || '')), 'ACTIVATION_DIGEST_INVALID', 'activation plan digests are invalid');
  assert(typeof plan.repositoryId === 'string' && SAFE_ID.test(plan.repositoryId), 'ACTIVATION_REPOSITORY_ID_INVALID', 'activation plan repository id is invalid');
  const expectedPath = sourcePathFor(allowedSourceRoot, plan.repositoryId);
  assert(plan.source?.path === expectedPath, 'ACTIVATION_SOURCE_PATH_INVALID', 'activation plan source path does not match its trusted root');
  assert(typeof plan.source?.content === 'string' && Buffer.byteLength(plan.source.content) <= MAX_SOURCE_BYTES, 'ACTIVATION_SOURCE_INVALID', 'activation plan source content is invalid');
  assert(plan.source.sha256 === digest(plan.source.content), 'ACTIVATION_SOURCE_DIGEST_MISMATCH', 'activation source digest mismatch');
  assert(typeof plan.keyring?.path === 'string' && plan.keyring.path.startsWith('/usr/share/keyrings/') && plan.keyring.path.endsWith('.gpg'), 'ACTIVATION_KEYRING_PATH_INVALID', 'activation keyring path is outside the trusted root');
  assert(HEX40.test(String(plan.keyring?.fingerprint || '').toUpperCase()), 'ACTIVATION_KEY_FINGERPRINT_INVALID', 'activation plan signing fingerprint is invalid');
  const expiry = Date.parse(plan.evidenceValidUntil);
  const current = now instanceof Date ? now.getTime() : Date.parse(now);
  assert(Number.isFinite(expiry) && Number.isFinite(current) && expiry >= current, 'ACTIVATION_EVIDENCE_EXPIRED', 'activation evidence expired before mutation');
  validateUpdateCommand(plan.updateCommand, expectedPath);
  const scope = {
    bindingDigest: plan.bindingDigest,
    repositoryId: plan.repositoryId,
    sourcePath: plan.source.path,
    sourceSha256: plan.source.sha256,
    keyringPath: plan.keyring.path,
    keyFingerprint: String(plan.keyring.fingerprint).toUpperCase(),
    evidenceValidUntil: plan.evidenceValidUntil,
    architecture: plan.source.content.match(/^Architectures:\s*(\S+)$/m)?.[1] || null
  };
  assert(plan.activationDigest === digest(scope), 'ACTIVATION_DIGEST_MISMATCH', 'activation digest no longer matches the trusted activation scope');
  return true;
}

function ensurePrivateDirectory(root, { expectedOwnerUid = 0, enforceOwnership = true } = {}) {
  fs.mkdirSync(root, { recursive: true, mode: 0o700 });
  const stat = fs.lstatSync(root);
  assert(stat.isDirectory() && !stat.isSymbolicLink(), 'ACTIVATION_JOURNAL_ROOT_UNSAFE', 'activation journal root must be a real directory');
  assert((stat.mode & 0o077) === 0, 'ACTIVATION_JOURNAL_ROOT_MODE_UNSAFE', 'activation journal root must be private');
  if (enforceOwnership && typeof stat.uid === 'number') assert(stat.uid === expectedOwnerUid, 'ACTIVATION_JOURNAL_ROOT_OWNER_INVALID', 'activation journal root owner is not trusted');
}

function atomicWrite(file, data, mode) {
  const directory = path.dirname(file);
  const temporary = path.join(directory, `.${path.basename(file)}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`);
  fs.writeFileSync(temporary, data, { encoding: 'utf8', mode, flag: 'wx' });
  const fd = fs.openSync(temporary, 'r');
  try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
  fs.renameSync(temporary, file);
  try {
    const dirFd = fs.openSync(directory, 'r');
    try { fs.fsyncSync(dirFd); } finally { fs.closeSync(dirFd); }
  } catch {}
}

export class FileVendorRepositoryActivationJournal {
  constructor({ root = DEFAULT_JOURNAL_ROOT, expectedOwnerUid = 0, enforceOwnership = true } = {}) {
    assert(typeof root === 'string' && path.isAbsolute(root), 'ACTIVATION_JOURNAL_ROOT_INVALID', 'activation journal root must be absolute');
    this.root = path.resolve(root);
    this.expectedOwnerUid = expectedOwnerUid;
    this.enforceOwnership = enforceOwnership;
  }

  file(id) {
    assert(typeof id === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{7,159}$/.test(id), 'ACTIVATION_TRANSACTION_ID_INVALID', 'activation transaction id is invalid');
    const file = path.resolve(this.root, `${id}.json`);
    assert(path.dirname(file) === this.root, 'ACTIVATION_JOURNAL_PATH_ESCAPE', 'activation journal path escaped its root');
    return file;
  }

  write(record) {
    assert(object(record) && record.schema === JOURNAL_SCHEMA, 'ACTIVATION_JOURNAL_INVALID', 'activation journal record is invalid');
    ensurePrivateDirectory(this.root, { expectedOwnerUid: this.expectedOwnerUid, enforceOwnership: this.enforceOwnership });
    const serialized = `${JSON.stringify(record, null, 2)}\n`;
    assert(Buffer.byteLength(serialized) <= MAX_JOURNAL_BYTES, 'ACTIVATION_JOURNAL_TOO_LARGE', 'activation journal record exceeds the size bound');
    const file = this.file(record.transactionId);
    atomicWrite(file, serialized, 0o600);
    fs.chmodSync(file, 0o600);
    return file;
  }

  read(id) {
    ensurePrivateDirectory(this.root, { expectedOwnerUid: this.expectedOwnerUid, enforceOwnership: this.enforceOwnership });
    const file = this.file(id);
    const stat = fs.lstatSync(file);
    assert(stat.isFile() && !stat.isSymbolicLink() && stat.size <= MAX_JOURNAL_BYTES && (stat.mode & 0o077) === 0, 'ACTIVATION_JOURNAL_FILE_UNSAFE', 'activation journal file is unsafe');
    const record = JSON.parse(fs.readFileSync(file, 'utf8'));
    assert(record?.schema === JOURNAL_SCHEMA && record.transactionId === id, 'ACTIVATION_JOURNAL_BINDING_INVALID', 'activation journal identity mismatch');
    assert(record.planDigest === digest(record.plan), 'ACTIVATION_JOURNAL_PLAN_DIGEST_MISMATCH', 'activation journal plan digest mismatch');
    return record;
  }

  list() {
    ensurePrivateDirectory(this.root, { expectedOwnerUid: this.expectedOwnerUid, enforceOwnership: this.enforceOwnership });
    return fs.readdirSync(this.root).filter(name => /^[A-Za-z0-9][A-Za-z0-9._-]{7,159}\.json$/.test(name)).sort().map(name => this.read(name.slice(0, -5)));
  }
}

export class FileVendorRepositorySourceStore {
  constructor({ root = DEFAULT_SOURCE_ROOT, expectedOwnerUid = 0, enforceOwnership = true } = {}) {
    this.root = normalizeRoot(root);
    this.expectedOwnerUid = expectedOwnerUid;
    this.enforceOwnership = enforceOwnership;
  }

  assertRoot() {
    const stat = fs.lstatSync(this.root);
    assert(stat.isDirectory() && !stat.isSymbolicLink(), 'ACTIVATION_SOURCE_ROOT_UNSAFE', 'APT source root must be a real directory');
    assert(fs.realpathSync(this.root) === this.root, 'ACTIVATION_SOURCE_ROOT_UNSAFE', 'APT source root must resolve exactly to its trusted path');
    assert((stat.mode & 0o022) === 0, 'ACTIVATION_SOURCE_ROOT_MODE_UNSAFE', 'APT source root must not be group/world writable');
    if (this.enforceOwnership && typeof stat.uid === 'number') assert(stat.uid === this.expectedOwnerUid, 'ACTIVATION_SOURCE_ROOT_OWNER_INVALID', 'APT source root owner is not trusted');
  }

  inspect(file) {
    this.assertRoot();
    assert(path.dirname(path.resolve(file)) === this.root, 'ACTIVATION_SOURCE_PATH_ESCAPE', 'APT source file escaped trusted root');
    if (!fs.existsSync(file)) return { existed: false, content: null, sha256: null };
    const stat = fs.lstatSync(file);
    assert(stat.isFile() && !stat.isSymbolicLink(), 'ACTIVATION_SOURCE_FILE_UNSAFE', 'APT source target must be a regular non-symlink file');
    assert((stat.mode & 0o022) === 0 && stat.size <= MAX_SOURCE_BYTES, 'ACTIVATION_SOURCE_FILE_UNSAFE', 'APT source target permissions or size are unsafe');
    if (this.enforceOwnership && typeof stat.uid === 'number') assert(stat.uid === this.expectedOwnerUid, 'ACTIVATION_SOURCE_FILE_OWNER_INVALID', 'APT source target owner is not trusted');
    const content = fs.readFileSync(file, 'utf8');
    return { existed: true, content, sha256: digest(content) };
  }

  write(file, content) {
    this.inspect(file);
    assert(typeof content === 'string' && Buffer.byteLength(content) <= MAX_SOURCE_BYTES, 'ACTIVATION_SOURCE_INVALID', 'APT source content exceeds the verified bound');
    atomicWrite(file, content, 0o644);
    fs.chmodSync(file, 0o644);
    const current = this.inspect(file);
    assert(current.sha256 === digest(content), 'ACTIVATION_SOURCE_WRITE_MISMATCH', 'APT source atomic write did not preserve expected content');
    return current;
  }

  restore(file, previous) {
    assert(object(previous) && typeof previous.existed === 'boolean', 'ACTIVATION_PREVIOUS_SOURCE_INVALID', 'previous source state is invalid');
    if (previous.existed) {
      this.write(file, String(previous.content ?? ''));
      return this.inspect(file);
    }
    this.inspect(file);
    if (fs.existsSync(file)) {
      const stat = fs.lstatSync(file);
      assert(stat.isFile() && !stat.isSymbolicLink(), 'ACTIVATION_SOURCE_FILE_UNSAFE', 'APT source target became unsafe before rollback');
      fs.unlinkSync(file);
    }
    return { existed: false, content: null, sha256: null };
  }
}

export class GpgVendorKeyringVerifier {
  constructor({ executable = '/usr/bin/gpg', expectedOwnerUid = 0, enforceOwnership = true } = {}) {
    this.executable = executable;
    this.expectedOwnerUid = expectedOwnerUid;
    this.enforceOwnership = enforceOwnership;
  }

  verify(keyring) {
    assert(typeof keyring?.path === 'string' && keyring.path.startsWith('/usr/share/keyrings/') && keyring.path.endsWith('.gpg'), 'ACTIVATION_KEYRING_PATH_INVALID', 'keyring path is outside /usr/share/keyrings');
    const stat = fs.lstatSync(keyring.path);
    assert(stat.isFile() && !stat.isSymbolicLink() && stat.size > 0 && stat.size <= 16 * 1024 * 1024, 'ACTIVATION_KEYRING_FILE_UNSAFE', 'vendor keyring must be a bounded regular file');
    assert(fs.realpathSync(keyring.path) === path.resolve(keyring.path), 'ACTIVATION_KEYRING_FILE_UNSAFE', 'vendor keyring must resolve exactly to the reviewed path');
    assert((stat.mode & 0o022) === 0, 'ACTIVATION_KEYRING_MODE_UNSAFE', 'vendor keyring must not be group/world writable');
    if (this.enforceOwnership && typeof stat.uid === 'number') assert(stat.uid === this.expectedOwnerUid, 'ACTIVATION_KEYRING_OWNER_INVALID', 'vendor keyring owner is not trusted');
    const result = spawnSync(this.executable, ['--batch', '--no-options', '--show-keys', '--with-colons', '--fingerprint', keyring.path], { encoding: 'utf8', maxBuffer: 256 * 1024, shell: false });
    assert(result.status === 0 && !result.error, 'ACTIVATION_KEYRING_GPG_FAILED', 'failed to inspect vendor keyring with fixed gpg argv');
    const fingerprints = String(result.stdout || '').split(/\r?\n/).filter(line => line.startsWith('fpr:')).map(line => line.split(':')[9]).filter(Boolean).map(value => value.toUpperCase());
    const expected = String(keyring.fingerprint || '').toUpperCase();
    assert(HEX40.test(expected) && fingerprints.includes(expected), 'ACTIVATION_KEYRING_FINGERPRINT_MISMATCH', 'installed vendor keyring fingerprint does not match the reviewed full fingerprint');
    return { verified: true, fingerprint: expected };
  }
}

function safeError(error) {
  return { code: typeof error?.code === 'string' ? error.code.slice(0, 128) : 'ACTIVATION_FAILED', message: typeof error?.message === 'string' ? error.message.slice(0, 1000) : 'vendor repository activation failed' };
}

export class VendorRepositoryActivationTransactionService {
  constructor({ journal, sourceStore, keyringVerifier, authorizationBroker, executor, allowedSourceRoot = DEFAULT_SOURCE_ROOT, clock = () => new Date().toISOString(), idFactory = () => crypto.randomUUID(), enforceRoot = true } = {}) {
    assert(journal?.write && journal?.read && journal?.list, 'ACTIVATION_JOURNAL_REQUIRED', 'activation journal dependency is required');
    assert(sourceStore?.inspect && sourceStore?.write && sourceStore?.restore, 'ACTIVATION_SOURCE_STORE_REQUIRED', 'activation source store dependency is required');
    assert(typeof keyringVerifier?.verify === 'function', 'ACTIVATION_KEYRING_VERIFIER_REQUIRED', 'keyring verifier dependency is required');
    assert(typeof authorizationBroker?.authorize === 'function', 'ACTIVATION_AUTHORIZATION_REQUIRED', 'authorization broker dependency is required');
    assert(typeof executor?.run === 'function', 'ACTIVATION_EXECUTOR_REQUIRED', 'privileged argv executor dependency is required');
    this.journal = journal;
    this.sourceStore = sourceStore;
    this.keyringVerifier = keyringVerifier;
    this.authorizationBroker = authorizationBroker;
    this.executor = executor;
    this.allowedSourceRoot = normalizeRoot(allowedSourceRoot);
    this.clock = clock;
    this.idFactory = idFactory;
    this.enforceRoot = enforceRoot;
  }

  async execute(plan, context = {}) {
    const now = new Date(this.clock());
    assertVendorRepositoryActivationPlan(plan, { allowedSourceRoot: this.allowedSourceRoot, now });
    if (this.enforceRoot && typeof process.geteuid === 'function') assert(process.geteuid() === 0, 'ACTIVATION_ROOT_REQUIRED', 'vendor repository activation must execute inside the existing privileged broker');
    assert(context.confirmationDigest === plan.activationDigest, 'ACTIVATION_CONFIRMATION_MISMATCH', 'explicit activation digest confirmation is required');
    this.keyringVerifier.verify(plan.keyring);
    const authorization = await this.authorizationBroker.authorize({
      schema: 'swir.vendor-repository-activation-authorization-request/0.1',
      repositoryId: plan.repositoryId,
      activationDigest: plan.activationDigest,
      bindingDigest: plan.bindingDigest,
      sourcePath: plan.source.path,
      command: [...plan.updateCommand]
    }, context);
    assert(authorization?.authorized === true && typeof authorization.authorizationId === 'string' && authorization.authorizationId.length > 0, 'ACTIVATION_NOT_AUTHORIZED', 'existing privilege broker did not authorize repository activation');

    const previous = this.sourceStore.inspect(plan.source.path);
    const transactionId = this.idFactory();
    assert(typeof transactionId === 'string' && /^[A-Za-z0-9][A-Za-z0-9._-]{7,159}$/.test(transactionId), 'ACTIVATION_TRANSACTION_ID_INVALID', 'activation transaction id is invalid');
    let record = {
      schema: JOURNAL_SCHEMA,
      transactionId,
      state: 'prepared',
      createdAt: this.clock(),
      updatedAt: this.clock(),
      actorId: context.actorId ?? null,
      authorizationId: authorization.authorizationId,
      plan: clone(plan),
      planDigest: digest(plan),
      previousSource: previous,
      result: null,
      recovery: { operatorReviewRequired: false, sourceRestoreRequired: false, automaticPackageMutation: false },
      error: null
    };
    this.journal.write(record);

    try {
      this.sourceStore.write(plan.source.path, plan.source.content);
      record = { ...record, state: 'source-staged', updatedAt: this.clock(), recovery: { ...record.recovery, sourceRestoreRequired: true } };
      this.journal.write(record);

      const command = validateUpdateCommand(plan.updateCommand, plan.source.path);
      const result = await this.executor.run(command, { repositoryId: plan.repositoryId, activationDigest: plan.activationDigest, authorizationId: authorization.authorizationId });
      assert(object(result) && Number.isInteger(result.exitCode), 'ACTIVATION_EXECUTOR_RESULT_INVALID', 'repository metadata refresh executor returned an invalid result');
      assert(result.exitCode === 0 && (result.signal === null || result.signal === undefined), 'ACTIVATION_METADATA_REFRESH_FAILED', 'APT rejected the activated vendor repository metadata');
      const current = this.sourceStore.inspect(plan.source.path);
      assert(current.existed && current.sha256 === plan.source.sha256, 'ACTIVATION_POST_VERIFY_FAILED', 'vendor repository source changed during activation');

      record = { ...record, state: 'committed', updatedAt: this.clock(), result: { metadataRefreshExitCode: result.exitCode, sourceSha256: current.sha256 }, recovery: { operatorReviewRequired: false, sourceRestoreRequired: false, automaticPackageMutation: false } };
      this.journal.write(record);
      return clone(record);
    } catch (error) {
      try {
        this.sourceStore.restore(plan.source.path, previous);
        record = { ...record, state: 'rolled-back', updatedAt: this.clock(), error: safeError(error), recovery: { operatorReviewRequired: false, sourceRestoreRequired: false, automaticPackageMutation: false } };
      } catch (rollbackError) {
        record = { ...record, state: 'failed-needs-recovery', updatedAt: this.clock(), error: safeError(error), recovery: { operatorReviewRequired: true, sourceRestoreRequired: true, automaticPackageMutation: false, rollbackError: safeError(rollbackError) } };
      }
      this.journal.write(record);
      throw error;
    }
  }

  inspectRecovery() {
    return this.journal.list().filter(record => !TERMINAL_STATES.has(record.state) || record.state === 'failed-needs-recovery').map(record => ({
      schema: 'swir.vendor-repository-activation-recovery-assessment/0.1',
      transactionId: record.transactionId,
      state: record.state,
      repositoryId: record.plan?.repositoryId ?? null,
      activationDigest: record.plan?.activationDigest ?? null,
      operatorReviewRequired: true,
      sourceRestoreRequired: record.recovery?.sourceRestoreRequired === true,
      automaticPackageMutation: false
    }));
  }

  async recoverSource(transactionId, context = {}) {
    const record = this.journal.read(transactionId);
    assert(!TERMINAL_STATES.has(record.state) || record.state === 'failed-needs-recovery', 'ACTIVATION_RECOVERY_NOT_REQUIRED', 'activation transaction does not require source recovery');
    if (this.enforceRoot && typeof process.geteuid === 'function') assert(process.geteuid() === 0, 'ACTIVATION_ROOT_REQUIRED', 'vendor repository recovery must execute inside the existing privileged broker');
    assert(context.confirmationDigest === record.plan.activationDigest, 'ACTIVATION_CONFIRMATION_MISMATCH', 'recovery requires the exact activation digest confirmation');
    const authorization = await this.authorizationBroker.authorize({
      schema: 'swir.vendor-repository-activation-recovery-authorization-request/0.1',
      repositoryId: record.plan.repositoryId,
      activationDigest: record.plan.activationDigest,
      transactionId
    }, context);
    assert(authorization?.authorized === true && typeof authorization.authorizationId === 'string' && authorization.authorizationId.length > 0, 'ACTIVATION_NOT_AUTHORIZED', 'existing privilege broker did not authorize repository recovery');
    const current = this.sourceStore.inspect(record.plan.source.path);
    if (current.existed && current.sha256 !== record.plan.source.sha256 && current.sha256 !== record.previousSource?.sha256) {
      fail('ACTIVATION_RECOVERY_SOURCE_DIVERGED', 'APT source changed outside the transaction; refusing automatic recovery');
    }
    this.sourceStore.restore(record.plan.source.path, record.previousSource);
    const recovered = { ...record, state: 'rolled-back', updatedAt: this.clock(), recoveryAuthorizationId: authorization.authorizationId, recovery: { operatorReviewRequired: false, sourceRestoreRequired: false, automaticPackageMutation: false } };
    this.journal.write(recovered);
    return clone(recovered);
  }
}

export const VendorRepositoryActivationPolicy = Object.freeze({
  schema: 'swir.vendor-repository-activation-policy/0.1',
  aptOnly: true,
  sourceRoot: DEFAULT_SOURCE_ROOT,
  journalRoot: DEFAULT_JOURNAL_ROOT,
  existingPrivilegeBrokerRequired: true,
  exactActivationDigestConfirmationRequired: true,
  rootOwnedPinnedKeyringRequired: true,
  signedByRequired: true,
  trustedFlagForcedFalse: true,
  targetedMetadataRefreshOnly: true,
  journalBeforeMutation: true,
  rollbackOnSynchronousFailure: true,
  interruptedRecoveryRequiresOperator: true,
  directPackageInstall: false,
  arbitraryRepositoryUrl: false,
  arbitraryKeyDownload: false,
  shellExecution: false
});
