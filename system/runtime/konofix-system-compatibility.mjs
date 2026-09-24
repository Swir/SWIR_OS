import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { managedPrefixPath } from './windows-compatibility-service.mjs';

export const KonofixSystemCompatibilityIdentity = Object.freeze({
  schema: 'swir.konofix-system-compatibility/0.1',
  appId: 'info.swir.konofixchat',
  repository: 'Swir/Konofix',
  version: '0.5.1',
  sourceCommit: '31298cc732c97ff90230c3743cd1c3be17f40b6c',
  installerSha256: '9d0ae79d32d49272ec597cfaae19023a5d0a3a1c8dc23d622b987bb2bc250de6',
  executableName: 'konofix-chat.exe',
  provider: 'swir.compat.wine',
  windowsArchitecture: 'win64'
});

const DEFAULT_PREFIX_ROOT = '/var/lib/swir/compat/prefixes';
const MAX_EXECUTABLE_BYTES = 256 * 1024 * 1024;
const DIGEST_RE = /^[0-9a-f]{64}$/;

function fail(code, message) {
  const error = new Error(message);
  error.name = 'KonofixSystemCompatibilityError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function within(candidate, root) {
  const relative = path.relative(root, candidate);
  return relative === '' || (!relative.startsWith('..') && !path.isAbsolute(relative));
}

function hashRegularFileNoFollow(file) {
  const before = fs.lstatSync(file);
  assert(before.isFile() && !before.isSymbolicLink(), 'INVALID_EXECUTABLE', 'Konofix executable must be a regular non-symlink file');
  assert(before.size > 0 && before.size <= MAX_EXECUTABLE_BYTES, 'INVALID_EXECUTABLE_SIZE', 'Konofix executable size is outside the guarded limit');
  const fd = fs.openSync(file, fs.constants.O_RDONLY | (fs.constants.O_NOFOLLOW || 0));
  try {
    const opened = fs.fstatSync(fd);
    assert(opened.isFile() && opened.dev === before.dev && opened.ino === before.ino, 'EXECUTABLE_CHANGED', 'Konofix executable changed while being opened');
    const hash = crypto.createHash('sha256');
    const buffer = Buffer.allocUnsafe(128 * 1024);
    let position = 0;
    while (position < opened.size) {
      const bytes = fs.readSync(fd, buffer, 0, Math.min(buffer.length, opened.size - position), position);
      assert(bytes > 0, 'EXECUTABLE_CHANGED', 'Konofix executable ended during verification');
      hash.update(buffer.subarray(0, bytes));
      position += bytes;
    }
    const after = fs.fstatSync(fd);
    assert(after.dev === opened.dev && after.ino === opened.ino && after.size === opened.size && after.mtimeMs === opened.mtimeMs,
      'EXECUTABLE_CHANGED', 'Konofix executable changed during verification');
    return hash.digest('hex');
  } finally {
    fs.closeSync(fd);
  }
}

function validateLineage(evidence) {
  assert(evidence.upstreamRepository === KonofixSystemCompatibilityIdentity.repository, 'UNSUPPORTED_UPSTREAM', 'Unexpected Konofix upstream repository');
  assert(evidence.version === KonofixSystemCompatibilityIdentity.version, 'UNSUPPORTED_VERSION', 'Only the reviewed Konofix version is allowed');
  assert(evidence.sourceCommit === KonofixSystemCompatibilityIdentity.sourceCommit, 'SOURCE_COMMIT_MISMATCH', 'Konofix source commit does not match the reviewed source');
  assert(evidence.installerSha256 === KonofixSystemCompatibilityIdentity.installerSha256, 'INSTALLER_DIGEST_MISMATCH', 'Konofix installer digest does not match the reviewed release');
  assert(evidence.installerVerified === true, 'INSTALLER_NOT_VERIFIED', 'Installer verification evidence is required');
  assert(evidence.explicitInstallApproved === true, 'INSTALL_NOT_APPROVED', 'Explicit user installation approval is required');
  assert(evidence.legacyDataImported === false, 'LEGACY_IMPORT_FORBIDDEN', 'Legacy SWIR Chat identity/history/files must not be silently imported');
}

export function validateKonofixSystemInstallEvidence(evidence, { prefixRoot = DEFAULT_PREFIX_ROOT } = {}) {
  assert(evidence && typeof evidence === 'object' && !Array.isArray(evidence), 'INVALID_EVIDENCE', 'Konofix installation evidence must be an object');
  assert(evidence.schema === 'swir.konofix-system-install/0.1', 'INVALID_EVIDENCE_SCHEMA', 'Unsupported Konofix installation evidence schema');
  validateLineage(evidence);
  assert(typeof prefixRoot === 'string' && path.isAbsolute(prefixRoot), 'INVALID_PREFIX_ROOT', 'Compatibility prefix root must be absolute');
  assert(typeof evidence.installedExecutable === 'string' && path.isAbsolute(evidence.installedExecutable), 'INVALID_EXECUTABLE_PATH', 'Installed executable path must be absolute');
  assert(typeof evidence.installedExecutableSha256 === 'string' && DIGEST_RE.test(evidence.installedExecutableSha256), 'INVALID_EXECUTABLE_DIGEST', 'Installed executable SHA-256 is required');

  const original = fs.lstatSync(evidence.installedExecutable);
  assert(original.isFile() && !original.isSymbolicLink(), 'INVALID_EXECUTABLE', 'Installed executable must be a regular non-symlink file');
  const prefix = fs.realpathSync(managedPrefixPath(KonofixSystemCompatibilityIdentity.appId, { prefixRoot }));
  const executable = fs.realpathSync(evidence.installedExecutable);
  assert(within(executable, prefix), 'EXECUTABLE_OUTSIDE_PREFIX', 'Konofix executable is outside its dedicated managed prefix');
  assert(path.basename(executable).toLowerCase() === KonofixSystemCompatibilityIdentity.executableName, 'UNEXPECTED_EXECUTABLE', 'Unexpected Konofix executable name');
  const digest = hashRegularFileNoFollow(executable);
  assert(crypto.timingSafeEqual(Buffer.from(digest, 'hex'), Buffer.from(evidence.installedExecutableSha256, 'hex')),
    'EXECUTABLE_DIGEST_MISMATCH', 'Installed Konofix executable digest does not match installation evidence');

  return Object.freeze({ executable, executableSha256: digest, prefix, legacyDataImported: false });
}

export function createKonofixSystemManifest(evidence, options = {}) {
  const verified = validateKonofixSystemInstallEvidence(evidence, options);
  return Object.freeze({
    schema: 'swir.package-provider/0.2',
    id: KonofixSystemCompatibilityIdentity.appId,
    targetEditions: ['system'],
    executionClass: 'windows-compat',
    provider: KonofixSystemCompatibilityIdentity.provider,
    package: Object.freeze({
      name: 'Konofix Chat',
      version: KonofixSystemCompatibilityIdentity.version,
      channel: 'stable',
      sourceRef: KonofixSystemCompatibilityIdentity.sourceCommit,
      nativeEntryPoint: verified.executable,
      sha256: verified.executableSha256
    }),
    compatibility: Object.freeze({ prefixPolicy: 'per-app', windowsArchitecture: KonofixSystemCompatibilityIdentity.windowsArchitecture, runtimeChannel: 'system-managed' }),
    trust: Object.freeze({
      sourceClass: 'swir-signed',
      repositoryId: 'official',
      signatureRequired: true
    }),
    permissions: [],
    rollback: true
  });
}

export class KonofixSystemCompatibilityAdapter {
  #stack;
  #prefixRoot;

  constructor({ stack, prefixRoot = DEFAULT_PREFIX_ROOT } = {}) {
    assert(stack && typeof stack.plan === 'function' && typeof stack.launch === 'function', 'INVALID_COMPATIBILITY_STACK', 'Managed Windows compatibility stack is required');
    assert(typeof prefixRoot === 'string' && path.isAbsolute(prefixRoot), 'INVALID_PREFIX_ROOT', 'Compatibility prefix root must be absolute');
    this.#stack = stack;
    this.#prefixRoot = prefixRoot;
  }

  plan(evidence, { packageTrustVerified = false, args = [], environment } = {}) {
    assert(packageTrustVerified === true, 'PACKAGE_TRUST_REQUIRED', 'SWIR package trust must be verified before Konofix planning');
    const manifest = createKonofixSystemManifest(evidence, { prefixRoot: this.#prefixRoot });
    return this.#stack.plan(manifest, { trustVerified: true, args, environment });
  }

  launch(evidence, { packageTrustVerified = false, userApprovedLaunch = false, args = [], environment, stdio } = {}) {
    assert(packageTrustVerified === true, 'PACKAGE_TRUST_REQUIRED', 'SWIR package trust must be verified before Konofix launch');
    assert(userApprovedLaunch === true, 'USER_APPROVAL_REQUIRED', 'Explicit user launch approval is required');
    const manifest = createKonofixSystemManifest(evidence, { prefixRoot: this.#prefixRoot });
    return this.#stack.launch(manifest, { trustVerified: true, args, environment, stdio });
  }
}

export const KonofixSystemCompatibilityPolicy = Object.freeze({
  schema: 'swir.konofix-system-compatibility/0.1',
  executionClass: 'windows-compat',
  provider: 'swir.compat.wine',
  prefixPolicy: 'per-app',
  packageTrustVerifiedRequired: true,
  installerVerificationRequired: true,
  installedExecutableDigestRequired: true,
  explicitInstallApprovalRequired: true,
  explicitLaunchApprovalRequired: true,
  silentLegacyDataImportAllowed: false,
  arbitraryExecutableAllowed: false,
  nativeLinuxGuiQualified: false,
  protonQualified: false,
  realPeerInteroperabilityQualified: false
});
