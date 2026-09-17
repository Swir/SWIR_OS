import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const fsp = fs.promises;
const ARTIFACTS = Object.freeze([
  {
    id: 'recovery-agent',
    source: 'system/recovery/recovery-mode-agent.mjs',
    destination: '/opt/swir/system/recovery/recovery-mode-agent.mjs',
    mode: 0o644
  },
  {
    id: 'recovery-service',
    source: 'system/recovery/swir-recovery.service',
    destination: '/etc/systemd/system/swir-recovery.service',
    mode: 0o644
  },
  {
    id: 'recovery-target',
    source: 'system/recovery/swir-recovery.target',
    destination: '/etc/systemd/system/swir-recovery.target',
    mode: 0o644
  }
]);

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'RecoveryModeProvisioningError';
  error.code = code;
  throw error;
}
function assert(condition, code, message) { if (!condition) fail(code, message); }
function digest(buffer) { return crypto.createHash('sha256').update(buffer).digest('hex'); }
async function safeDirectory(directory, code) {
  assert(typeof directory === 'string' && path.isAbsolute(directory), code, 'path must be absolute');
  const resolved = path.resolve(directory);
  assert(resolved !== path.parse(resolved).root, code, 'refusing filesystem root');
  const stat = await fsp.lstat(resolved);
  assert(stat.isDirectory() && !stat.isSymbolicLink(), code, 'path must be a real directory');
  assert(await fsp.realpath(resolved) === resolved, code, 'path must resolve exactly');
  return resolved;
}
async function ensureNoSymlinkAncestors(root, destination) {
  const relative = path.relative(root, destination);
  assert(relative && !path.isAbsolute(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`), 'RECOVERY_PATH_ESCAPE', 'destination escaped rootfs');
  let current = root;
  for (const part of relative.split(path.sep)) {
    current = path.join(current, part);
    try {
      const stat = await fsp.lstat(current);
      assert(!stat.isSymbolicLink(), 'RECOVERY_SYMLINK_ANCESTOR', `destination traverses symlink: ${current}`);
    } catch (error) {
      if (error?.code === 'ENOENT') return;
      throw error;
    }
  }
}
async function trustedSource(sourceRoot, relative) {
  const source = path.resolve(sourceRoot, relative);
  assert(source.startsWith(`${sourceRoot}${path.sep}`), 'RECOVERY_SOURCE_ESCAPE', `source escaped repository: ${relative}`);
  const stat = await fsp.lstat(source);
  assert(stat.isFile() && !stat.isSymbolicLink(), 'RECOVERY_SOURCE_UNTRUSTED', `source must be regular file: ${relative}`);
  assert(await fsp.realpath(source) === source, 'RECOVERY_SOURCE_UNTRUSTED', `source must resolve exactly: ${relative}`);
  return source;
}
async function atomicWrite(destination, content, mode) {
  try {
    const current = await fsp.lstat(destination);
    assert(current.isFile() && !current.isSymbolicLink(), 'RECOVERY_DESTINATION_UNSAFE', `unsafe existing destination: ${destination}`);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  const temporary = path.join(path.dirname(destination), `.${path.basename(destination)}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`);
  try {
    await fsp.writeFile(temporary, content, { mode, flag: 'wx' });
    await fsp.chmod(temporary, mode);
    await fsp.rename(temporary, destination);
  } finally {
    await fsp.rm(temporary, { force: true }).catch(() => {});
  }
}
function validateUnitContent(id, content) {
  const text = content.toString('utf8');
  assert(!/^\s*Exec(Start|Stop|Reload)=.*(?:sh\s+-c|bash\s+-c)/m.test(text), 'RECOVERY_SHELL_EXECUTION_FORBIDDEN', `${id} must not execute a shell command string`);
  if (id === 'recovery-service') {
    assert(text.includes('ProtectSystem=strict'), 'RECOVERY_SERVICE_HARDENING_MISSING', 'recovery service must keep ProtectSystem=strict');
    assert(text.includes('NoNewPrivileges=yes'), 'RECOVERY_SERVICE_HARDENING_MISSING', 'recovery service must enable NoNewPrivileges');
    assert(text.includes('CapabilityBoundingSet='), 'RECOVERY_SERVICE_HARDENING_MISSING', 'recovery service must drop capabilities');
    assert(text.includes('/run/swir/recovery/recovery-report.json'), 'RECOVERY_REPORT_PATH_INVALID', 'recovery service report must stay in tmpfs /run');
  }
  if (id === 'recovery-target') {
    assert(text.includes('Requires=basic.target swir-recovery.service'), 'RECOVERY_TARGET_DEPENDENCY_MISSING', 'recovery target must require the diagnostics service');
    assert(text.includes('Conflicts=graphical.target multi-user.target'), 'RECOVERY_TARGET_CONFLICT_MISSING', 'recovery target must not start normal desktop targets');
  }
}

export async function stageRecoveryModeFoundation({ rootfs, sourceRoot, production = false, clock = () => new Date().toISOString() } = {}) {
  const root = await safeDirectory(rootfs, 'RECOVERY_ROOTFS_INVALID');
  const source = await safeDirectory(sourceRoot, 'RECOVERY_SOURCE_ROOT_INVALID');
  if (production) {
    assert(typeof process.getuid === 'function' && process.getuid() === 0, 'RECOVERY_PRODUCTION_REQUIRES_ROOT', 'production recovery staging requires root');
    const rootStat = await fsp.lstat(root);
    assert(rootStat.uid === 0 && (rootStat.mode & 0o022) === 0, 'RECOVERY_ROOTFS_UNTRUSTED', 'production rootfs must be root-owned and not group/world writable');
  }
  const ownerUid = production ? 0 : (typeof process.getuid === 'function' ? process.getuid() : null);
  assert(Number.isInteger(ownerUid) && ownerUid >= 0, 'RECOVERY_OWNER_UNAVAILABLE', 'cannot determine recovery artifact owner');
  const staged = [];
  for (const artifact of ARTIFACTS) {
    const sourceFile = await trustedSource(source, artifact.source);
    const content = await fsp.readFile(sourceFile);
    if (artifact.id !== 'recovery-agent') validateUnitContent(artifact.id, content);
    const destination = path.resolve(root, `.${artifact.destination}`);
    assert(destination.startsWith(`${root}${path.sep}`), 'RECOVERY_PATH_ESCAPE', 'recovery destination escaped rootfs');
    await ensureNoSymlinkAncestors(root, destination);
    await fsp.mkdir(path.dirname(destination), { recursive: true, mode: 0o755 });
    await ensureNoSymlinkAncestors(root, destination);
    await atomicWrite(destination, content, artifact.mode);
    if (production) await fsp.chown(destination, 0, 0);
    const stat = await fsp.lstat(destination);
    staged.push({
      id: artifact.id,
      path: artifact.destination,
      mode: stat.mode & 0o777,
      ownerUid: typeof stat.uid === 'number' ? stat.uid : null,
      sha256: digest(content),
      bytes: content.length
    });
  }
  const report = await verifyRecoveryModeFoundation({ rootfs: root, production, expectedOwnerUid: ownerUid });
  assert(report.ready, 'RECOVERY_PROVISIONING_VERIFY_FAILED', `recovery foundation verification failed: ${report.blockers.join(', ')}`);
  return Object.freeze({ ...report, staged: true, stagedAt: clock(), artifacts: staged });
}

export async function verifyRecoveryModeFoundation({ rootfs, production = false, expectedOwnerUid = production ? 0 : (typeof process.getuid === 'function' ? process.getuid() : null) } = {}) {
  const root = await safeDirectory(rootfs, 'RECOVERY_ROOTFS_INVALID');
  const checks = [];
  for (const artifact of ARTIFACTS) {
    const destination = path.resolve(root, `.${artifact.destination}`);
    let passed = false;
    let detail = {};
    try {
      await ensureNoSymlinkAncestors(root, destination);
      const stat = await fsp.lstat(destination);
      const content = await fsp.readFile(destination);
      if (artifact.id !== 'recovery-agent') validateUnitContent(artifact.id, content);
      const mode = stat.mode & 0o777;
      const ownerOk = expectedOwnerUid === null || stat.uid === expectedOwnerUid;
      passed = stat.isFile() && !stat.isSymbolicLink() && mode === artifact.mode && ownerOk;
      detail = { mode, ownerUid: stat.uid, sha256: digest(content) };
    } catch (error) {
      detail = { code: error?.code || 'VERIFY_FAILED' };
    }
    checks.push({ id: artifact.id, required: true, passed, detail });
  }
  const blockers = checks.filter(check => check.required && !check.passed).map(check => check.id);
  return Object.freeze({
    schema: 'swir.recovery-mode-provisioning/0.1',
    production,
    ready: blockers.length === 0,
    bootEntryRequired: true,
    recoveryBootVerified: false,
    filesystemRepairClaim: false,
    automaticMutationAllowed: false,
    checks,
    blockers
  });
}

export const RecoveryModeProvisioningPolicy = Object.freeze({
  schema: 'swir.recovery-mode-provisioning-policy/0.1',
  fixedArtifactsOnly: true,
  productionOwnerUid: 0,
  symlinkDestinationsAllowed: false,
  reportStorage: '/run/swir/recovery',
  shellExecution: false,
  automaticFilesystemRepair: false,
  automaticPackageMutation: false,
  automaticFirmwareMutation: false
});
