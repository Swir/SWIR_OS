import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

const fsp = fs.promises;
const STATE_SCHEMA = 'swir.package-ui-broker-provisioning-state/0.1';
const REPORT_SCHEMA = 'swir.package-ui-broker-provisioning-report/0.1';
const STATE_PATH = '/var/lib/swir/image/package-ui-broker-provisioning-state.json';

const MANAGED_DIRECTORIES = Object.freeze([
  { path: '/usr/lib/swir/package-broker/ipc', mode: 0o755 },
  { path: '/usr/lib/swir/package-broker/packages', mode: 0o755 },
  { path: '/usr/lib/swir/package-broker/security', mode: 0o755 },
  { path: '/usr/local/lib/swir', mode: 0o755 },
  { path: '/usr/lib/systemd/system', mode: 0o755 },
  { path: '/usr/lib/systemd/system-preset', mode: 0o755 },
  { path: '/usr/share/doc/swir/system', mode: 0o755 },
  { path: '/var/lib/swir/image', mode: 0o700 }
]);

const ARTIFACTS = Object.freeze([
  { id: 'broker', source: 'system/ipc/swir-package-transaction-broker.mjs', path: '/usr/lib/swir/package-broker/ipc/swir-package-transaction-broker.mjs', mode: 0o644, required: ['DEFAULT_SOCKET = \'/run/swir/package-transaction.sock\'', 'createPeerAuthorizedSystemPackageSecurityBoundary', 'SystemPackageTransactionService'] },
  { id: 'peer-grant', source: 'system/ipc/peer-authorization-grant.mjs', path: '/usr/lib/swir/package-broker/ipc/peer-authorization-grant.mjs', mode: 0o644, required: ['DEFAULT_KEY = \'/run/swir/peer-authorization.key\'', 'GRANT_REPLAYED'] },
  { id: 'package-stack', source: 'system/packages/system-package-stack.mjs', path: '/usr/lib/swir/package-broker/packages/system-package-stack.mjs', mode: 0o644, required: ['planWithDependencies', 'execute(operation'] },
  { id: 'distribution-provider', source: 'system/packages/distribution-package-provider.mjs', path: '/usr/lib/swir/package-broker/packages/distribution-package-provider.mjs', mode: 0o644, required: ['DistributionPackageProvider'] },
  { id: 'transaction-service', source: 'system/packages/package-transaction-service.mjs', path: '/usr/lib/swir/package-broker/packages/package-transaction-service.mjs', mode: 0o644, required: ['SystemPackageTransactionService', 'digestPackagePlan'] },
  { id: 'privileged-executor', source: 'system/packages/privileged-package-executor.mjs', path: '/usr/lib/swir/package-broker/packages/privileged-package-executor.mjs', mode: 0o644, required: ['GuardedPkexecPackageExecutor'] },
  { id: 'package-state', source: 'system/packages/distribution-package-state.mjs', path: '/usr/lib/swir/package-broker/packages/distribution-package-state.mjs', mode: 0o644, required: ['DistributionPackageSnapshotProvider', 'NativePackageHealthVerifier'] },
  { id: 'dependency-resolver', source: 'system/packages/apt-dependency-resolver.mjs', path: '/usr/lib/swir/package-broker/packages/apt-dependency-resolver.mjs', mode: 0o644, required: ['AptDependencyResolver'] },
  { id: 'peer-boundary', source: 'system/security/peer-package-security-boundary.mjs', path: '/usr/lib/swir/package-broker/security/peer-package-security-boundary.mjs', mode: 0o644, required: ['createPeerAuthorizedSystemPackageSecurityBoundary'] },
  { id: 'package-boundary', source: 'system/security/system-package-security-boundary.mjs', path: '/usr/lib/swir/package-broker/security/system-package-security-boundary.mjs', mode: 0o644, required: ['createSystemPackageSecurityBoundary'] },
  { id: 'polkit-broker', source: 'system/security/polkit-authorization-broker.mjs', path: '/usr/lib/swir/package-broker/security/polkit-authorization-broker.mjs', mode: 0o644, required: ['PolkitAuthorizationBroker'] },
  { id: 'repository-trust', source: 'system/security/distribution-repository-trust.mjs', path: '/usr/lib/swir/package-broker/security/distribution-repository-trust.mjs', mode: 0o644, required: ['DistributionRepositoryTrustVerifier'] },
  { id: 'native-client', source: 'system/apps/package_transaction_client.py', path: '/usr/local/lib/swir/package_transaction_client.py', mode: 0o644, required: ['class PackageTransactionClient', 'authorize_and_commit'] },
  { id: 'service', source: 'system/ipc/swir-package-transaction.service', path: '/usr/lib/systemd/system/swir-package-transaction.service', mode: 0o644, required: ['ExecStart=/usr/bin/node /usr/lib/swir/package-broker/ipc/swir-package-transaction-broker.mjs', 'Requires=swir-peer-authorization.socket'] },
  { id: 'preset', source: 'system/ipc/91-swir-package-transaction.preset', path: '/usr/lib/systemd/system-preset/91-swir-package-transaction.preset', mode: 0o644, required: ['enable swir-package-transaction.service'] },
  { id: 'documentation', source: 'system/SWIR-PACKAGE-UI-BROKER-0.1.md', path: '/usr/share/doc/swir/system/SWIR-PACKAGE-UI-BROKER-0.1.md', mode: 0o644, required: ['SWIR Package UI Broker 0.1', 'Confused-deputy protections'] }
]);

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'SystemPackageUiBrokerProvisioningError';
  error.code = code;
  throw error;
}
function assert(condition, code, message) { if (!condition) fail(code, message); }
function digest(data) { return crypto.createHash('sha256').update(data).digest('hex'); }
function target(rootfs, imagePath) {
  assert(typeof imagePath === 'string' && imagePath.startsWith('/') && imagePath !== '/' && path.posix.normalize(imagePath) === imagePath, 'INVALID_IMAGE_PATH', `invalid image path ${imagePath}`);
  const resolved = path.resolve(rootfs, `.${imagePath}`);
  assert(resolved.startsWith(`${rootfs}${path.sep}`), 'IMAGE_PATH_ESCAPE', `image path escapes rootfs: ${imagePath}`);
  return resolved;
}
async function safeRoot(rootfs) {
  assert(typeof rootfs === 'string' && path.isAbsolute(rootfs), 'ROOTFS_PATH_REQUIRED', 'rootfs must be an explicit absolute path');
  const resolved = path.resolve(rootfs);
  assert(resolved !== path.parse(resolved).root, 'REAL_ROOT_TARGET_FORBIDDEN', 'refusing to provision live filesystem root');
  const stat = await fsp.lstat(resolved).catch(error => fail('ROOTFS_UNAVAILABLE', `rootfs unavailable: ${resolved}`, error));
  assert(stat.isDirectory() && !stat.isSymbolicLink(), 'ROOTFS_INVALID', 'rootfs must be a real non-symlink directory');
  assert(await fsp.realpath(resolved) === resolved, 'ROOTFS_SYMLINKED', 'rootfs must resolve exactly to requested directory');
  return resolved;
}
async function assertNoSymlinkAncestors(rootfs, destination) {
  const relative = path.relative(rootfs, destination);
  assert(relative && !path.isAbsolute(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`), 'IMAGE_PATH_ESCAPE', 'managed path escaped rootfs');
  let current = rootfs;
  const parts = relative.split(path.sep);
  for (let i = 0; i < parts.length; i += 1) {
    current = path.join(current, parts[i]);
    try {
      const stat = await fsp.lstat(current);
      assert(!stat.isSymbolicLink(), 'IMAGE_PATH_SYMLINK_ANCESTOR', `managed image path traverses symlink: ${current}`);
      if (i < parts.length - 1) assert(stat.isDirectory(), 'IMAGE_PATH_ANCESTOR_INVALID', `non-directory ancestor: ${current}`);
    } catch (error) {
      if (error?.code === 'ENOENT') return;
      throw error;
    }
  }
}
async function trustedSource(sourceRoot, relative) {
  assert(typeof sourceRoot === 'string' && path.isAbsolute(sourceRoot), 'SOURCE_ROOT_REQUIRED', 'sourceRoot must be absolute');
  const root = await fsp.realpath(sourceRoot);
  const source = path.resolve(root, relative);
  assert(source.startsWith(`${root}${path.sep}`), 'SOURCE_ESCAPE', `source escaped repository: ${relative}`);
  const stat = await fsp.lstat(source);
  assert(stat.isFile() && !stat.isSymbolicLink() && await fsp.realpath(source) === source, 'SOURCE_UNTRUSTED', `source must be a regular non-symlink file: ${relative}`);
  return source;
}
async function atomicWrite(destination, data, mode) {
  try {
    const existing = await fsp.lstat(destination);
    assert(existing.isFile() && !existing.isSymbolicLink(), 'DESTINATION_UNTRUSTED', `unsafe destination ${destination}`);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  const temporary = path.join(path.dirname(destination), `.${path.basename(destination)}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`);
  try {
    await fsp.writeFile(temporary, data, { mode, flag: 'wx' });
    await fsp.chmod(temporary, mode);
    await fsp.rename(temporary, destination);
  } finally {
    await fsp.rm(temporary, { force: true }).catch(() => {});
  }
}
async function inspect(destination, expectedMode, ownerUid, directory) {
  try {
    const stat = await fsp.lstat(destination);
    if (stat.isSymbolicLink()) return { trusted: false, reason: 'symlink' };
    const typeOk = directory ? stat.isDirectory() : stat.isFile();
    const mode = stat.mode & 0o777;
    const ownerOk = ownerUid === null || typeof stat.uid !== 'number' || stat.uid === ownerUid;
    return { trusted: typeOk && mode === expectedMode && ownerOk, typeOk, mode, ownerUid: stat.uid ?? null, ownerOk };
  } catch (error) {
    return { trusted: false, reason: error?.code || 'probe-failed' };
  }
}
async function runtimeCheck(root, ownerUid) {
  const nodePath = target(root, '/usr/bin/node');
  try {
    const stat = await fsp.lstat(nodePath);
    return {
      passed: stat.isFile() && !stat.isSymbolicLink() && (stat.mode & 0o022) === 0 && (ownerUid === null || stat.uid === ownerUid),
      path: '/usr/bin/node', mode: stat.mode & 0o777, ownerUid: stat.uid
    };
  } catch (error) {
    return { passed: false, path: '/usr/bin/node', reason: error?.code || 'probe-failed' };
  }
}

export async function stagePackageUiBrokerFoundation({ rootfs, sourceRoot, production = false, requireRuntime = production, clock = () => new Date().toISOString() } = {}) {
  const root = await safeRoot(rootfs);
  const ownerUid = production ? 0 : (typeof process.getuid === 'function' ? process.getuid() : null);
  assert(Number.isInteger(ownerUid) && ownerUid >= 0, 'OWNER_UID_UNAVAILABLE', 'cannot determine owner uid');
  if (production) {
    assert(typeof process.getuid === 'function' && process.getuid() === 0, 'PRODUCTION_REQUIRES_ROOT', 'production provisioning requires root');
    const rootStat = await fsp.lstat(root);
    assert(rootStat.uid === 0 && (rootStat.mode & 0o022) === 0, 'PRODUCTION_ROOTFS_UNTRUSTED', 'production rootfs must be root-owned and not group/world writable');
  }

  for (const entry of MANAGED_DIRECTORIES) {
    const destination = target(root, entry.path);
    await assertNoSymlinkAncestors(root, destination);
    try {
      const stat = await fsp.lstat(destination);
      assert(stat.isDirectory() && !stat.isSymbolicLink(), 'DESTINATION_UNTRUSTED', `unsafe managed directory ${entry.path}`);
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error;
      await fsp.mkdir(destination, { recursive: true, mode: entry.mode });
    }
    await fsp.chmod(destination, entry.mode);
    if (production) await fsp.chown(destination, 0, 0);
  }

  const runtime = await runtimeCheck(root, ownerUid);
  if (requireRuntime) assert(runtime.passed, 'NODE_RUNTIME_UNAVAILABLE', 'trusted /usr/bin/node runtime is required before package broker provisioning');

  const artifacts = [];
  for (const entry of ARTIFACTS) {
    const source = await trustedSource(sourceRoot, entry.source);
    const content = await fsp.readFile(source);
    const text = content.toString('utf8');
    for (const token of entry.required) assert(text.includes(token), 'SOURCE_CONTRACT_MISMATCH', `${entry.id} is missing required token: ${token}`);
    const destination = target(root, entry.path);
    await assertNoSymlinkAncestors(root, destination);
    await fsp.mkdir(path.dirname(destination), { recursive: true });
    await assertNoSymlinkAncestors(root, destination);
    await atomicWrite(destination, content, entry.mode);
    if (production) await fsp.chown(destination, 0, 0);
    artifacts.push({ id: entry.id, path: entry.path, mode: entry.mode, bytes: content.length, sha256: digest(content) });
  }

  const state = {
    schema: STATE_SCHEMA,
    production,
    ownerUid,
    generatedAt: clock(),
    artifacts,
    nodeRuntimeRequired: requireRuntime,
    nodeRuntime: runtime,
    servicePreset: true,
    directUiPackageToolInvocation: false,
    bootedMutationE2eClaim: false
  };
  const stateFile = target(root, STATE_PATH);
  await assertNoSymlinkAncestors(root, stateFile);
  await atomicWrite(stateFile, Buffer.from(`${JSON.stringify(state, null, 2)}\n`), 0o600);
  if (production) await fsp.chown(stateFile, 0, 0);

  const report = await verifyPackageUiBrokerFoundation({ rootfs: root, production, expectedOwnerUid: ownerUid, requireRuntime });
  assert(report.ready, 'PROVISIONING_VERIFICATION_FAILED', `package UI broker staging failed: ${report.blockers.join(', ')}`);
  return Object.freeze({ ...report, staged: true, state });
}

export async function verifyPackageUiBrokerFoundation({ rootfs, production = false, expectedOwnerUid = production ? 0 : (typeof process.getuid === 'function' ? process.getuid() : null), requireRuntime = production } = {}) {
  const root = await safeRoot(rootfs);
  const checks = [];
  for (const entry of MANAGED_DIRECTORIES) {
    const destination = target(root, entry.path);
    let ancestorsSafe = true;
    try { await assertNoSymlinkAncestors(root, destination); } catch { ancestorsSafe = false; }
    const result = await inspect(destination, entry.mode, expectedOwnerUid, true);
    checks.push({ id: `dir:${entry.path}`, required: true, passed: ancestorsSafe && result.trusted, detail: result });
  }

  let state = null;
  const stateFile = target(root, STATE_PATH);
  try { state = JSON.parse(await fsp.readFile(stateFile, 'utf8')); } catch {}
  checks.push({ id: 'state-shape', required: true, passed: state?.schema === STATE_SCHEMA && Array.isArray(state?.artifacts), detail: { schema: state?.schema ?? null } });
  const recorded = new Map((state?.artifacts || []).map(item => [item?.id, item]));

  for (const entry of ARTIFACTS) {
    const destination = target(root, entry.path);
    let ancestorsSafe = true;
    try { await assertNoSymlinkAncestors(root, destination); } catch { ancestorsSafe = false; }
    const result = await inspect(destination, entry.mode, expectedOwnerUid, false);
    let integrity = false;
    let requiredTokens = false;
    try {
      const content = await fsp.readFile(destination);
      const record = recorded.get(entry.id);
      integrity = Boolean(record && record.path === entry.path && record.mode === entry.mode && record.bytes === content.length && record.sha256 === digest(content));
      const text = content.toString('utf8');
      requiredTokens = entry.required.every(token => text.includes(token));
    } catch {}
    checks.push({ id: `file:${entry.id}`, required: true, passed: ancestorsSafe && result.trusted && integrity && requiredTokens, detail: { ...result, ancestorsSafe, integrity, requiredTokens } });
  }

  const runtime = await runtimeCheck(root, expectedOwnerUid);
  checks.push({ id: 'node-runtime', required: requireRuntime, passed: !requireRuntime || runtime.passed, detail: runtime });
  const stateStat = await inspect(stateFile, 0o600, expectedOwnerUid, false);
  checks.push({ id: 'state-file', required: true, passed: stateStat.trusted, detail: stateStat });
  const blockers = checks.filter(check => check.required && !check.passed).map(check => check.id);
  return Object.freeze({ schema: REPORT_SCHEMA, ready: blockers.length === 0, production, servicePreset: true, bootedMutationE2eClaim: false, checks: Object.freeze(checks), blockers: Object.freeze(blockers) });
}

export const PackageUiBrokerProvisioningPolicy = Object.freeze({
  schema: 'swir.package-ui-broker-provisioning-policy/0.1',
  liveRootTargetAllowed: false,
  symlinkDestinationsAllowed: false,
  productionRequiresRoot: true,
  trustedNodeRuntimeRequiredInProduction: true,
  servicePreset: true,
  directUiPackageToolInvocation: false,
  bootedMutationE2eClaim: false
});
