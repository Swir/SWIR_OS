import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';

import { stagePeerAuthorizationFoundation, verifyPeerAuthorizationFoundation } from './system-peer-authorization-provisioning.mjs';

const fsp = fs.promises;
const STATE_SCHEMA = 'swir.package-ui-runtime-provisioning-state/0.1';
const REPORT_SCHEMA = 'swir.package-ui-runtime-provisioning-report/0.1';
const STATE_PATH = '/var/lib/swir/image/package-ui-runtime-provisioning-state.json';
const SERVICE_LINK = '/etc/systemd/system/multi-user.target.wants/swir-package-transaction.service';
const SERVICE_TARGET = '/usr/lib/systemd/system/swir-package-transaction.service';

const DIRECTORIES = Object.freeze([
  { path: '/usr/lib/swir/package-broker/ipc', mode: 0o755 },
  { path: '/usr/lib/swir/package-broker/packages', mode: 0o755 },
  { path: '/usr/lib/swir/package-broker/security', mode: 0o755 },
  { path: '/usr/lib/systemd/system', mode: 0o755 },
  { path: '/etc/systemd/system/multi-user.target.wants', mode: 0o755 },
  { path: '/etc/swir', mode: 0o755 },
  { path: '/var/lib/swir/image', mode: 0o700 },
  { path: '/var/lib/swir/package-transactions', mode: 0o700 },
]);

const ARTIFACTS = Object.freeze([
  { id: 'package-broker', source: 'system/ipc/swir-package-transaction-broker.mjs', path: '/usr/lib/swir/package-broker/ipc/swir-package-transaction-broker.mjs', mode: 0o644, required: ['createPeerAuthorizedSystemPackageSecurityBoundary', 'GuardedPkexecPackageExecutor', 'planRecomputedBeforeCommit: true'] },
  { id: 'peer-grant', source: 'system/ipc/peer-authorization-grant.mjs', path: '/usr/lib/swir/package-broker/ipc/peer-authorization-grant.mjs', mode: 0o644, required: ['swir.peer-authorization-envelope/0.1', 'grantReplayAllowed'] },
  { id: 'package-service', source: 'system/ipc/swir-package-transaction.service', path: SERVICE_TARGET, mode: 0o644, required: ['ExecStart=/usr/bin/node /usr/lib/swir/package-broker/ipc/swir-package-transaction-broker.mjs', 'Requires=swir-peer-authorization.socket', 'User=root'] },
  { id: 'distribution-provider', source: 'system/packages/distribution-package-provider.mjs', path: '/usr/lib/swir/package-broker/packages/distribution-package-provider.mjs', mode: 0o644, required: ['distribution-repository', 'sourceRef'] },
  { id: 'transaction-service', source: 'system/packages/package-transaction-service.mjs', path: '/usr/lib/swir/package-broker/packages/package-transaction-service.mjs', mode: 0o644, required: ['failed-needs-recovery', 'journal'] },
  { id: 'privileged-executor', source: 'system/packages/privileged-package-executor.mjs', path: '/usr/lib/swir/package-broker/packages/privileged-package-executor.mjs', mode: 0o644, required: ["'apt-get': '/usr/bin/apt-get'", 'DEBIAN_FRONTEND'] },
  { id: 'package-state', source: 'system/packages/distribution-package-state.mjs', path: '/usr/lib/swir/package-broker/packages/distribution-package-state.mjs', mode: 0o644, required: ['DistributionPackageSnapshotProvider', 'NativePackageHealthVerifier'] },
  { id: 'dependency-resolver', source: 'system/packages/apt-dependency-resolver.mjs', path: '/usr/lib/swir/package-broker/packages/apt-dependency-resolver.mjs', mode: 0o644, required: ['AptDependencyResolver', '--simulate'] },
  { id: 'package-stack', source: 'system/packages/system-package-stack.mjs', path: '/usr/lib/swir/package-broker/packages/system-package-stack.mjs', mode: 0o644, required: ['planWithDependencies', 'dependency-resolution'] },
  { id: 'peer-security-boundary', source: 'system/security/peer-package-security-boundary.mjs', path: '/usr/lib/swir/package-broker/security/peer-package-security-boundary.mjs', mode: 0o644, required: ['PeerAuthorizationGrantVerifier', 'callerSuppliedUnixIdentity: false'] },
  { id: 'repository-trust', source: 'system/security/distribution-repository-trust.mjs', path: '/usr/lib/swir/package-broker/security/distribution-repository-trust.mjs', mode: 0o644, required: ['DistributionRepositoryTrustVerifier', 'loadRepositoryTrustPolicy'] },
  { id: 'system-security-boundary', source: 'system/security/system-package-security-boundary.mjs', path: '/usr/lib/swir/package-broker/security/system-package-security-boundary.mjs', mode: 0o644, required: ['PolkitSystemAuthorizationBroker', 'arbitraryRepositoryUrls: false'] },
  { id: 'polkit-broker', source: 'system/security/polkit-authorization-broker.mjs', path: '/usr/lib/swir/package-broker/security/polkit-authorization-broker.mjs', mode: 0o644, required: ['org.swir.system.packages.mutate', 'pkcheck'] },
  { id: 'repository-policy', source: 'system/image/debian-trixie-repository-trust-policy.json', path: '/etc/swir/repository-trust-policy.json', mode: 0o644, required: ['swir.system-repository-trust-policy/0.1', 'debian-main', 'native-required'] },
]);

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'SystemPackageUiRuntimeProvisioningError';
  error.code = code;
  throw error;
}
function assert(condition, code, message) { if (!condition) fail(code, message); }
function digest(data) { return crypto.createHash('sha256').update(data).digest('hex'); }
function imageTarget(rootfs, imagePath) {
  assert(typeof imagePath === 'string' && imagePath.startsWith('/') && imagePath !== '/' && path.posix.normalize(imagePath) === imagePath && !imagePath.includes('\0'), 'INVALID_IMAGE_PATH', `invalid image path: ${imagePath}`);
  const output = path.resolve(rootfs, `.${imagePath}`);
  assert(output.startsWith(`${rootfs}${path.sep}`), 'IMAGE_PATH_ESCAPE', `image path escapes rootfs: ${imagePath}`);
  return output;
}
async function safeRoot(rootfs) {
  assert(typeof rootfs === 'string' && path.isAbsolute(rootfs), 'ROOTFS_PATH_REQUIRED', 'rootfs must be an explicit absolute path');
  const resolved = path.resolve(rootfs);
  assert(resolved !== path.parse(resolved).root, 'REAL_ROOT_TARGET_FORBIDDEN', 'refusing to provision the live filesystem root');
  const stat = await fsp.lstat(resolved).catch(error => fail('ROOTFS_UNAVAILABLE', `rootfs unavailable: ${resolved}`, error));
  assert(stat.isDirectory() && !stat.isSymbolicLink(), 'ROOTFS_INVALID', 'rootfs must be a real non-symlink directory');
  assert(await fsp.realpath(resolved) === resolved, 'ROOTFS_SYMLINKED', 'rootfs must resolve exactly to requested directory');
  return resolved;
}
async function noSymlinkAncestors(rootfs, destination) {
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
  } catch (error) { if (error?.code !== 'ENOENT') throw error; }
  const temporary = path.join(path.dirname(destination), `.${path.basename(destination)}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`);
  try {
    await fsp.writeFile(temporary, data, { mode, flag: 'wx' });
    await fsp.chmod(temporary, mode);
    await fsp.rename(temporary, destination);
  } finally { await fsp.rm(temporary, { force: true }).catch(() => {}); }
}
async function inspect(destination, expectedMode, ownerUid, directory) {
  try {
    const stat = await fsp.lstat(destination);
    if (stat.isSymbolicLink()) return { trusted: false, reason: 'symlink' };
    const typeOk = directory ? stat.isDirectory() : stat.isFile();
    const actualMode = stat.mode & 0o777;
    const ownerOk = ownerUid === null || typeof stat.uid !== 'number' || stat.uid === ownerUid;
    return { trusted: typeOk && actualMode === expectedMode && ownerOk, typeOk, ownerOk, ownerUid: stat.uid ?? null, mode: actualMode };
  } catch (error) { return { trusted: false, reason: error?.code || 'probe-failed' }; }
}
async function ensureDirectory(root, entry, production) {
  const destination = imageTarget(root, entry.path);
  await noSymlinkAncestors(root, destination);
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
async function setExactServiceLink(root) {
  const destination = imageTarget(root, SERVICE_LINK);
  await noSymlinkAncestors(root, path.dirname(destination));
  try {
    const existing = await fsp.lstat(destination);
    if (!existing.isSymbolicLink()) fail('SERVICE_LINK_UNTRUSTED', `refusing non-symlink ${SERVICE_LINK}`);
    const value = await fsp.readlink(destination);
    if (value === SERVICE_TARGET) return;
    fail('SERVICE_LINK_UNTRUSTED', `refusing unexpected ${SERVICE_LINK} -> ${value}`);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  await fsp.symlink(SERVICE_TARGET, destination);
}
function validateRepositoryPolicy(text) {
  let value;
  try { value = JSON.parse(text); } catch (error) { fail('REPOSITORY_POLICY_INVALID', 'repository trust policy must be valid JSON', error); }
  assert(value?.schema === 'swir.system-repository-trust-policy/0.1', 'REPOSITORY_POLICY_INVALID', 'repository trust policy schema mismatch');
  assert(Array.isArray(value.repositories) && value.repositories.length > 0, 'REPOSITORY_POLICY_INVALID', 'repository trust policy must contain repositories');
  for (const repo of value.repositories) {
    assert(repo.manager === 'apt' && repo.sourceClass === 'distribution-repository', 'REPOSITORY_POLICY_INVALID', 'package broker image policy must remain distribution APT only');
    assert(repo.signatureVerification === 'native-required' && repo.allowInsecure === false && repo.enabled === true, 'REPOSITORY_POLICY_INSECURE', `insecure repository policy: ${repo.id}`);
  }
}

export async function stagePackageUiRuntime({ rootfs, sourceRoot, production = false, clock = () => new Date().toISOString(), includePeerAuthorization = true } = {}) {
  const root = await safeRoot(rootfs);
  const ownerUid = production ? 0 : (typeof process.getuid === 'function' ? process.getuid() : null);
  assert(Number.isInteger(ownerUid) && ownerUid >= 0, 'OWNER_UID_UNAVAILABLE', 'cannot determine owner uid');
  if (production) {
    assert(typeof process.getuid === 'function' && process.getuid() === 0, 'PRODUCTION_REQUIRES_ROOT', 'production package UI provisioning requires root');
    const rootStat = await fsp.lstat(root);
    assert(rootStat.uid === 0 && (rootStat.mode & 0o022) === 0, 'PRODUCTION_ROOTFS_UNTRUSTED', 'production rootfs must be root-owned and not group/world writable');
    const nodeResult = await inspect(imageTarget(root, '/usr/bin/node'), 0o755, 0, false);
    assert(nodeResult.trusted, 'NODE_RUNTIME_UNAVAILABLE', 'production package broker requires a trusted root-owned /usr/bin/node runtime');
  }

  if (includePeerAuthorization) {
    await stagePeerAuthorizationFoundation({ rootfs: root, sourceRoot, production, clock });
  }
  for (const entry of DIRECTORIES) await ensureDirectory(root, entry, production);

  const artifacts = [];
  for (const entry of ARTIFACTS) {
    const source = await trustedSource(sourceRoot, entry.source);
    const content = await fsp.readFile(source);
    const text = content.toString('utf8');
    for (const token of entry.required) assert(text.includes(token), 'SOURCE_CONTRACT_MISMATCH', `${entry.id} missing required token: ${token}`);
    if (entry.id === 'repository-policy') validateRepositoryPolicy(text);
    const destination = imageTarget(root, entry.path);
    await noSymlinkAncestors(root, destination);
    await fsp.mkdir(path.dirname(destination), { recursive: true });
    await noSymlinkAncestors(root, destination);
    await atomicWrite(destination, content, entry.mode);
    if (production) await fsp.chown(destination, 0, 0);
    artifacts.push({ id: entry.id, path: entry.path, bytes: content.length, mode: entry.mode, sha256: digest(content) });
  }
  await setExactServiceLink(root);

  const state = {
    schema: STATE_SCHEMA,
    production,
    ownerUid,
    generatedAt: clock(),
    artifacts,
    peerAuthorizationIncluded: includePeerAuthorization,
    packageBrokerServiceEnabled: true,
    directUiPackageToolsAllowed: false,
    runtimeKeyEmbeddedInImage: false,
    bootableImageClaim: false,
  };
  const stateFile = imageTarget(root, STATE_PATH);
  await atomicWrite(stateFile, Buffer.from(`${JSON.stringify(state, null, 2)}\n`), 0o600);
  if (production) await fsp.chown(stateFile, 0, 0);

  const report = await verifyPackageUiRuntime({ rootfs: root, production, expectedOwnerUid: ownerUid, verifyPeerAuthorization: includePeerAuthorization });
  assert(report.ready, 'PROVISIONING_VERIFICATION_FAILED', `package UI runtime staging failed: ${report.blockers.join(', ')}`);
  return Object.freeze({ ...report, staged: true, state });
}

export async function verifyPackageUiRuntime({ rootfs, production = false, expectedOwnerUid = production ? 0 : (typeof process.getuid === 'function' ? process.getuid() : null), verifyPeerAuthorization = true } = {}) {
  const root = await safeRoot(rootfs);
  const checks = [];
  for (const entry of DIRECTORIES) {
    const destination = imageTarget(root, entry.path);
    let ancestorsSafe = true;
    try { await noSymlinkAncestors(root, destination); } catch { ancestorsSafe = false; }
    const result = await inspect(destination, entry.mode, expectedOwnerUid, true);
    checks.push({ id: `dir:${entry.path}`, required: true, passed: ancestorsSafe && result.trusted, detail: result });
  }

  let state = null;
  const stateFile = imageTarget(root, STATE_PATH);
  try { state = JSON.parse(await fsp.readFile(stateFile, 'utf8')); } catch {}
  checks.push({ id: 'state-shape', required: true, passed: state?.schema === STATE_SCHEMA && Array.isArray(state?.artifacts), detail: { schema: state?.schema ?? null } });
  checks.push({ id: 'runtime-key-not-baked-into-image', required: true, passed: state?.runtimeKeyEmbeddedInImage === false, detail: { embedded: state?.runtimeKeyEmbeddedInImage ?? null } });
  checks.push({ id: 'direct-ui-package-tools-forbidden', required: true, passed: state?.directUiPackageToolsAllowed === false, detail: { allowed: state?.directUiPackageToolsAllowed ?? null } });
  const recorded = new Map((state?.artifacts || []).map(item => [item?.id, item]));

  for (const entry of ARTIFACTS) {
    const destination = imageTarget(root, entry.path);
    let ancestorsSafe = true;
    try { await noSymlinkAncestors(root, destination); } catch { ancestorsSafe = false; }
    const result = await inspect(destination, entry.mode, expectedOwnerUid, false);
    let integrity = false;
    let requiredTokens = false;
    try {
      const content = await fsp.readFile(destination);
      const record = recorded.get(entry.id);
      integrity = Boolean(record && record.path === entry.path && record.mode === entry.mode && record.bytes === content.length && record.sha256 === digest(content));
      const text = content.toString('utf8');
      requiredTokens = entry.required.every(token => text.includes(token));
      if (entry.id === 'repository-policy') validateRepositoryPolicy(text);
    } catch {}
    checks.push({ id: `file:${entry.id}`, required: true, passed: ancestorsSafe && result.trusted && integrity && requiredTokens, detail: { ...result, ancestorsSafe, integrity, requiredTokens } });
  }

  const serviceLink = imageTarget(root, SERVICE_LINK);
  let serviceLinkOk = false;
  try { serviceLinkOk = (await fsp.lstat(serviceLink)).isSymbolicLink() && await fsp.readlink(serviceLink) === SERVICE_TARGET; } catch {}
  checks.push({ id: 'package-broker-service-enabled', required: true, passed: serviceLinkOk, detail: { target: serviceLinkOk ? SERVICE_TARGET : null } });

  const stateStat = await inspect(stateFile, 0o600, expectedOwnerUid, false);
  checks.push({ id: 'state-file', required: true, passed: stateStat.trusted, detail: stateStat });

  if (production) {
    const nodeResult = await inspect(imageTarget(root, '/usr/bin/node'), 0o755, 0, false);
    checks.push({ id: 'node-runtime', required: true, passed: nodeResult.trusted, detail: nodeResult });
  }
  if (verifyPeerAuthorization) {
    const peer = await verifyPeerAuthorizationFoundation({ rootfs: root, production, expectedOwnerUid });
    checks.push({ id: 'peer-authorization-runtime', required: true, passed: peer.ready, detail: { blockers: peer.blockers } });
  }

  const blockers = checks.filter(check => check.required && !check.passed).map(check => check.id);
  return Object.freeze({
    schema: REPORT_SCHEMA,
    ready: blockers.length === 0,
    production,
    packageBrokerServiceEnabled: serviceLinkOk,
    runtimeKeyEmbeddedInImage: false,
    directUiPackageToolsAllowed: false,
    bootableImageClaim: false,
    checks: Object.freeze(checks),
    blockers: Object.freeze(blockers),
  });
}

export const PackageUiRuntimeProvisioningPolicy = Object.freeze({
  schema: 'swir.package-ui-runtime-provisioning-policy/0.1',
  liveRootTargetAllowed: false,
  symlinkDestinationsAllowed: false,
  peerAuthorizationRequired: true,
  signedDistributionRepositoryPolicyRequired: true,
  runtimeKeyEmbeddedInImage: false,
  directUiPackageToolsAllowed: false,
  packageBrokerServiceEnabled: true,
  productionRequiresRoot: true,
  bootableImageClaim: false,
});
