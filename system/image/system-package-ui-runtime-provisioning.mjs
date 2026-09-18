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
  ['/usr/lib/swir/package-broker/ipc', 0o755],
  ['/usr/lib/swir/package-broker/packages', 0o755],
  ['/usr/lib/swir/package-broker/security', 0o755],
  ['/usr/lib/systemd/system', 0o755],
  ['/etc/systemd/system/multi-user.target.wants', 0o755],
  ['/etc/swir', 0o755],
  ['/var/lib/swir/image', 0o700],
  ['/var/lib/swir/package-transactions', 0o700],
]);

const ARTIFACTS = Object.freeze([
  ['package-broker', 'system/ipc/swir-package-transaction-broker.mjs', '/usr/lib/swir/package-broker/ipc/swir-package-transaction-broker.mjs', ['createPeerAuthorizedSystemPackageSecurityBoundary', 'GuardedPkexecPackageExecutor', 'planRecomputedBeforeCommit: true']],
  ['peer-grant', 'system/ipc/peer-authorization-grant.mjs', '/usr/lib/swir/package-broker/ipc/peer-authorization-grant.mjs', ['PeerAuthorizationGrantVerifier', 'oneTimeConsumption: true']],
  ['package-service', 'system/ipc/swir-package-transaction.service', SERVICE_TARGET, ['ExecStart=/usr/bin/node /usr/lib/swir/package-broker/ipc/swir-package-transaction-broker.mjs', 'Requires=swir-peer-authorization.socket', 'User=root']],
  ['distribution-provider', 'system/packages/distribution-package-provider.mjs', '/usr/lib/swir/package-broker/packages/distribution-package-provider.mjs', ['distribution-repository', 'sourceRef']],
  ['transaction-service', 'system/packages/package-transaction-service.mjs', '/usr/lib/swir/package-broker/packages/package-transaction-service.mjs', ['failed-needs-recovery', 'journal']],
  ['privileged-executor', 'system/packages/privileged-package-executor.mjs', '/usr/lib/swir/package-broker/packages/privileged-package-executor.mjs', ["'apt-get': '/usr/bin/apt-get'", 'DEBIAN_FRONTEND']],
  ['package-state', 'system/packages/distribution-package-state.mjs', '/usr/lib/swir/package-broker/packages/distribution-package-state.mjs', ['DistributionPackageSnapshotProvider', 'NativePackageHealthVerifier']],
  ['dependency-resolver', 'system/packages/apt-dependency-resolver.mjs', '/usr/lib/swir/package-broker/packages/apt-dependency-resolver.mjs', ['AptDependencyResolver', 'APT_SIMULATION_TIMEOUT']],
  ['package-stack', 'system/packages/system-package-stack.mjs', '/usr/lib/swir/package-broker/packages/system-package-stack.mjs', ['planWithDependencies', 'dependency-resolution']],
  ['peer-security-boundary', 'system/security/peer-package-security-boundary.mjs', '/usr/lib/swir/package-broker/security/peer-package-security-boundary.mjs', ['PeerAuthorizationGrantVerifier', 'callerSuppliedUnixIdentity: false']],
  ['repository-trust', 'system/security/distribution-repository-trust.mjs', '/usr/lib/swir/package-broker/security/distribution-repository-trust.mjs', ['DistributionRepositoryTrustVerifier', 'loadRepositoryTrustPolicy']],
  ['system-security-boundary', 'system/security/system-package-security-boundary.mjs', '/usr/lib/swir/package-broker/security/system-package-security-boundary.mjs', ['PolkitSystemAuthorizationBroker', 'arbitraryRepositoryUrls: false']],
  ['polkit-broker', 'system/security/polkit-authorization-broker.mjs', '/usr/lib/swir/package-broker/security/polkit-authorization-broker.mjs', ['org.swir.system.packages.mutate', 'pkcheck']],
  ['repository-policy', 'system/image/debian-trixie-repository-trust-policy.json', '/etc/swir/repository-trust-policy.json', ['swir.system-repository-trust-policy/0.1', 'debian-main', 'native-required']],
].map(([id, source, imagePath, required]) => Object.freeze({ id, source, path: imagePath, mode: 0o644, required })));

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'SystemPackageUiRuntimeProvisioningError';
  error.code = code;
  throw error;
}
function ensure(value, code, message) { if (!value) fail(code, message); }
function sha256(data) { return crypto.createHash('sha256').update(data).digest('hex'); }
function target(root, imagePath) {
  ensure(typeof imagePath === 'string' && imagePath.startsWith('/') && imagePath !== '/' && path.posix.normalize(imagePath) === imagePath && !imagePath.includes('\0'), 'INVALID_IMAGE_PATH', `invalid image path: ${imagePath}`);
  const resolved = path.resolve(root, `.${imagePath}`);
  ensure(resolved.startsWith(`${root}${path.sep}`), 'IMAGE_PATH_ESCAPE', `image path escapes rootfs: ${imagePath}`);
  return resolved;
}
async function safeRoot(rootfs) {
  ensure(typeof rootfs === 'string' && path.isAbsolute(rootfs), 'ROOTFS_PATH_REQUIRED', 'rootfs must be an explicit absolute path');
  const root = path.resolve(rootfs);
  ensure(root !== path.parse(root).root, 'REAL_ROOT_TARGET_FORBIDDEN', 'refusing to provision live filesystem root');
  const stat = await fsp.lstat(root).catch(error => fail('ROOTFS_UNAVAILABLE', `rootfs unavailable: ${root}`, error));
  ensure(stat.isDirectory() && !stat.isSymbolicLink(), 'ROOTFS_INVALID', 'rootfs must be a real non-symlink directory');
  ensure(await fsp.realpath(root) === root, 'ROOTFS_SYMLINKED', 'rootfs must resolve exactly to requested directory');
  return root;
}
async function noSymlinkAncestors(root, destination) {
  const relative = path.relative(root, destination);
  ensure(relative && !path.isAbsolute(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`), 'IMAGE_PATH_ESCAPE', 'managed path escaped rootfs');
  let current = root;
  const parts = relative.split(path.sep);
  for (let i = 0; i < parts.length; i += 1) {
    current = path.join(current, parts[i]);
    try {
      const stat = await fsp.lstat(current);
      ensure(!stat.isSymbolicLink(), 'IMAGE_PATH_SYMLINK_ANCESTOR', `managed path traverses symlink: ${current}`);
      if (i < parts.length - 1) ensure(stat.isDirectory(), 'IMAGE_PATH_ANCESTOR_INVALID', `non-directory ancestor: ${current}`);
    } catch (error) { if (error?.code === 'ENOENT') return; throw error; }
  }
}
async function sourceFile(sourceRoot, relative) {
  ensure(typeof sourceRoot === 'string' && path.isAbsolute(sourceRoot), 'SOURCE_ROOT_REQUIRED', 'sourceRoot must be absolute');
  const root = await fsp.realpath(sourceRoot);
  const source = path.resolve(root, relative);
  ensure(source.startsWith(`${root}${path.sep}`), 'SOURCE_ESCAPE', `source escaped repository: ${relative}`);
  const stat = await fsp.lstat(source);
  ensure(stat.isFile() && !stat.isSymbolicLink() && await fsp.realpath(source) === source, 'SOURCE_UNTRUSTED', `source must be regular non-symlink: ${relative}`);
  return source;
}
async function atomicWrite(destination, data, mode) {
  try {
    const stat = await fsp.lstat(destination);
    ensure(stat.isFile() && !stat.isSymbolicLink(), 'DESTINATION_UNTRUSTED', `unsafe destination: ${destination}`);
  } catch (error) { if (error?.code !== 'ENOENT') throw error; }
  const temporary = path.join(path.dirname(destination), `.${path.basename(destination)}.${process.pid}.${crypto.randomBytes(5).toString('hex')}.tmp`);
  try {
    await fsp.writeFile(temporary, data, { flag: 'wx', mode });
    await fsp.chmod(temporary, mode);
    await fsp.rename(temporary, destination);
  } finally { await fsp.rm(temporary, { force: true }).catch(() => {}); }
}
async function probe(destination, expectedMode, ownerUid, directory) {
  try {
    const stat = await fsp.lstat(destination);
    if (stat.isSymbolicLink()) return { trusted: false, reason: 'symlink' };
    const actualMode = stat.mode & 0o777;
    const typeOk = directory ? stat.isDirectory() : stat.isFile();
    const ownerOk = ownerUid === null || stat.uid === ownerUid;
    return { trusted: typeOk && actualMode === expectedMode && ownerOk, typeOk, ownerOk, ownerUid: stat.uid, mode: actualMode };
  } catch (error) { return { trusted: false, reason: error?.code || 'probe-failed' }; }
}
function validateRepoPolicy(text) {
  let value;
  try { value = JSON.parse(text); } catch (error) { fail('REPOSITORY_POLICY_INVALID', 'repository policy is invalid JSON', error); }
  ensure(value?.schema === 'swir.system-repository-trust-policy/0.1', 'REPOSITORY_POLICY_INVALID', 'repository policy schema mismatch');
  ensure(Array.isArray(value.repositories) && value.repositories.length > 0, 'REPOSITORY_POLICY_INVALID', 'repository policy is empty');
  for (const repo of value.repositories) {
    ensure(repo.manager === 'apt' && repo.sourceClass === 'distribution-repository', 'REPOSITORY_POLICY_INVALID', `unsupported image repository: ${repo.id}`);
    ensure(repo.signatureVerification === 'native-required' && repo.allowInsecure === false && repo.enabled === true, 'REPOSITORY_POLICY_INSECURE', `insecure repository: ${repo.id}`);
  }
}
async function makeDirectory(root, imagePath, mode, production) {
  const destination = target(root, imagePath);
  await noSymlinkAncestors(root, destination);
  try {
    const stat = await fsp.lstat(destination);
    ensure(stat.isDirectory() && !stat.isSymbolicLink(), 'DESTINATION_UNTRUSTED', `unsafe directory: ${imagePath}`);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
    await fsp.mkdir(destination, { recursive: true, mode });
  }
  await fsp.chmod(destination, mode);
  if (production) await fsp.chown(destination, 0, 0);
}
async function serviceLink(root) {
  const destination = target(root, SERVICE_LINK);
  await noSymlinkAncestors(root, path.dirname(destination));
  try {
    const stat = await fsp.lstat(destination);
    ensure(stat.isSymbolicLink(), 'SERVICE_LINK_UNTRUSTED', `refusing non-symlink ${SERVICE_LINK}`);
    ensure(await fsp.readlink(destination) === SERVICE_TARGET, 'SERVICE_LINK_UNTRUSTED', `unexpected ${SERVICE_LINK} target`);
    return;
  } catch (error) { if (error?.code !== 'ENOENT') throw error; }
  await fsp.symlink(SERVICE_TARGET, destination);
}

export async function stagePackageUiRuntime({ rootfs, sourceRoot, production = false, clock = () => new Date().toISOString(), includePeerAuthorization = true } = {}) {
  const root = await safeRoot(rootfs);
  const ownerUid = production ? 0 : process.getuid?.();
  ensure(Number.isInteger(ownerUid) && ownerUid >= 0, 'OWNER_UID_UNAVAILABLE', 'cannot determine image owner');
  if (production) {
    ensure(process.getuid?.() === 0, 'PRODUCTION_REQUIRES_ROOT', 'production provisioning requires root');
    const rootStat = await fsp.lstat(root);
    ensure(rootStat.uid === 0 && (rootStat.mode & 0o022) === 0, 'PRODUCTION_ROOTFS_UNTRUSTED', 'production rootfs must be root-owned and not group/world writable');
    const node = await probe(target(root, '/usr/bin/node'), 0o755, 0, false);
    ensure(node.trusted, 'NODE_RUNTIME_UNAVAILABLE', 'production image requires trusted root-owned /usr/bin/node');
  }
  if (includePeerAuthorization) await stagePeerAuthorizationFoundation({ rootfs: root, sourceRoot, production, clock });
  for (const [imagePath, mode] of DIRECTORIES) await makeDirectory(root, imagePath, mode, production);

  const records = [];
  for (const entry of ARTIFACTS) {
    const source = await sourceFile(sourceRoot, entry.source);
    const data = await fsp.readFile(source);
    const text = data.toString('utf8');
    for (const token of entry.required) ensure(text.includes(token), 'SOURCE_CONTRACT_MISMATCH', `${entry.id} is missing required invariant: ${token}`);
    if (entry.id === 'repository-policy') validateRepoPolicy(text);
    const destination = target(root, entry.path);
    await noSymlinkAncestors(root, destination);
    await fsp.mkdir(path.dirname(destination), { recursive: true });
    await noSymlinkAncestors(root, destination);
    await atomicWrite(destination, data, entry.mode);
    if (production) await fsp.chown(destination, 0, 0);
    records.push({ id: entry.id, path: entry.path, mode: entry.mode, bytes: data.length, sha256: sha256(data) });
  }
  await serviceLink(root);
  const state = {
    schema: STATE_SCHEMA,
    production,
    ownerUid,
    generatedAt: clock(),
    artifacts: records,
    peerAuthorizationIncluded: includePeerAuthorization,
    packageBrokerServiceEnabled: true,
    directUiPackageToolsAllowed: false,
    runtimeKeyEmbeddedInImage: false,
    bootableImageClaim: false,
  };
  const stateFile = target(root, STATE_PATH);
  await atomicWrite(stateFile, Buffer.from(`${JSON.stringify(state, null, 2)}\n`), 0o600);
  if (production) await fsp.chown(stateFile, 0, 0);
  const report = await verifyPackageUiRuntime({ rootfs: root, production, expectedOwnerUid: ownerUid, verifyPeerAuthorization: includePeerAuthorization });
  ensure(report.ready, 'PROVISIONING_VERIFICATION_FAILED', `package UI runtime verification failed: ${report.blockers.join(', ')}`);
  return Object.freeze({ ...report, staged: true, state });
}

export async function verifyPackageUiRuntime({ rootfs, production = false, expectedOwnerUid = production ? 0 : process.getuid?.(), verifyPeerAuthorization = true } = {}) {
  const root = await safeRoot(rootfs);
  const checks = [];
  for (const [imagePath, mode] of DIRECTORIES) {
    const destination = target(root, imagePath);
    let ancestorsSafe = true;
    try { await noSymlinkAncestors(root, destination); } catch { ancestorsSafe = false; }
    const detail = await probe(destination, mode, expectedOwnerUid, true);
    checks.push({ id: `dir:${imagePath}`, required: true, passed: ancestorsSafe && detail.trusted, detail });
  }
  let state = null;
  const stateFile = target(root, STATE_PATH);
  try { state = JSON.parse(await fsp.readFile(stateFile, 'utf8')); } catch {}
  checks.push({ id: 'state-shape', required: true, passed: state?.schema === STATE_SCHEMA && Array.isArray(state?.artifacts), detail: { schema: state?.schema ?? null } });
  checks.push({ id: 'runtime-key-not-baked-into-image', required: true, passed: state?.runtimeKeyEmbeddedInImage === false, detail: { embedded: state?.runtimeKeyEmbeddedInImage ?? null } });
  checks.push({ id: 'direct-ui-package-tools-forbidden', required: true, passed: state?.directUiPackageToolsAllowed === false, detail: { allowed: state?.directUiPackageToolsAllowed ?? null } });
  const recorded = new Map((state?.artifacts || []).map(item => [item?.id, item]));
  for (const entry of ARTIFACTS) {
    const destination = target(root, entry.path);
    let ancestorsSafe = true;
    try { await noSymlinkAncestors(root, destination); } catch { ancestorsSafe = false; }
    const detail = await probe(destination, entry.mode, expectedOwnerUid, false);
    let integrity = false;
    let requiredTokens = false;
    try {
      const data = await fsp.readFile(destination);
      const record = recorded.get(entry.id);
      integrity = Boolean(record && record.path === entry.path && record.mode === entry.mode && record.bytes === data.length && record.sha256 === sha256(data));
      const text = data.toString('utf8');
      requiredTokens = entry.required.every(token => text.includes(token));
      if (entry.id === 'repository-policy') validateRepoPolicy(text);
    } catch {}
    checks.push({ id: `file:${entry.id}`, required: true, passed: ancestorsSafe && detail.trusted && integrity && requiredTokens, detail: { ...detail, integrity, requiredTokens } });
  }
  let linkOk = false;
  try { linkOk = (await fsp.lstat(target(root, SERVICE_LINK))).isSymbolicLink() && await fsp.readlink(target(root, SERVICE_LINK)) === SERVICE_TARGET; } catch {}
  checks.push({ id: 'package-broker-service-enabled', required: true, passed: linkOk, detail: { target: linkOk ? SERVICE_TARGET : null } });
  checks.push({ id: 'state-file', required: true, passed: (await probe(stateFile, 0o600, expectedOwnerUid, false)).trusted, detail: {} });
  if (production) {
    const node = await probe(target(root, '/usr/bin/node'), 0o755, 0, false);
    checks.push({ id: 'node-runtime', required: true, passed: node.trusted, detail: node });
  }
  if (verifyPeerAuthorization) {
    const peer = await verifyPeerAuthorizationFoundation({ rootfs: root, production, expectedOwnerUid });
    checks.push({ id: 'peer-authorization-runtime', required: true, passed: peer.ready, detail: { blockers: peer.blockers } });
  }
  const blockers = checks.filter(check => check.required && !check.passed).map(check => check.id);
  return Object.freeze({ schema: REPORT_SCHEMA, ready: blockers.length === 0, production, packageBrokerServiceEnabled: linkOk, runtimeKeyEmbeddedInImage: false, directUiPackageToolsAllowed: false, bootableImageClaim: false, checks: Object.freeze(checks), blockers: Object.freeze(blockers) });
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
