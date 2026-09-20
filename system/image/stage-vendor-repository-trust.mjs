import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

import {
  parseVendorOfficialRepositoryPolicy
} from '../hardware/vendor-official-repository-service.mjs';
import {
  collectVendorRepositoryEvidence,
  getVendorRepositoryEvidenceProfile,
  parseGpgPrimaryFingerprint
} from '../hardware/vendor-repository-trust-evidence.mjs';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.resolve(HERE, '../..');
const DEFAULT_POLICY = path.join(REPO_ROOT, 'system/hardware/vendor-repositories.debian13.json');
const DEFAULT_PROFILE = 'nvidia-debian13-amd64';
const POLICY_TARGET = '/etc/swir/hardware/vendor-repositories.json';
const STATE_TARGET = '/var/lib/swir/image/vendor-repository-trust-state.json';
const SOURCE_ROOT = '/etc/apt/sources.list.d';
const STATE_SCHEMA = 'swir.vendor-repository-image-trust/0.1';
const MAX_KEY_BYTES = 128 * 1024;
const MAX_KEYRING_BYTES = 256 * 1024;
const HEX40 = /^[A-F0-9]{40}$/;
const HEX64 = /^[a-f0-9]{64}$/;

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'VendorRepositoryImageTrustError';
  error.code = code;
  throw error;
}
function ensure(value, code, message) { if (!value) fail(code, message); }
function sha256(bytes) { return crypto.createHash('sha256').update(bytes).digest('hex'); }

function imageTarget(rootfs, absolutePath) {
  ensure(typeof absolutePath === 'string' && path.posix.isAbsolute(absolutePath) && absolutePath !== '/',
    'IMAGE_PATH_INVALID', 'managed image path must be absolute and non-root');
  ensure(path.posix.normalize(absolutePath) === absolutePath && !absolutePath.split('/').includes('..'),
    'IMAGE_PATH_INVALID', `managed image path is not canonical: ${absolutePath}`);
  const target = path.resolve(rootfs, `.${absolutePath}`);
  ensure(target.startsWith(`${rootfs}${path.sep}`), 'IMAGE_PATH_ESCAPE', `managed path escaped rootfs: ${absolutePath}`);
  return target;
}

async function safeRootfs(rootfs) {
  ensure(typeof rootfs === 'string' && path.isAbsolute(rootfs), 'ROOTFS_PATH_REQUIRED', 'rootfs must be an explicit absolute path');
  const resolved = path.resolve(rootfs);
  ensure(resolved !== path.parse(resolved).root, 'REAL_ROOT_TARGET_FORBIDDEN', 'refusing to stage vendor trust into the live filesystem root');
  let stat;
  try { stat = await fs.promises.lstat(resolved); }
  catch (error) { fail('ROOTFS_UNAVAILABLE', `rootfs is unavailable: ${resolved}`, error); }
  ensure(stat.isDirectory() && !stat.isSymbolicLink(), 'ROOTFS_INVALID', 'rootfs must be a real directory');
  ensure(await fs.promises.realpath(resolved) === resolved, 'ROOTFS_SYMLINKED', 'rootfs must resolve exactly to the requested path');
  if (typeof stat.uid === 'number') ensure(stat.uid === 0, 'ROOTFS_OWNER_INVALID', 'production rootfs must be root-owned');
  ensure((stat.mode & 0o022) === 0, 'ROOTFS_MODE_UNSAFE', 'production rootfs must not be group/world writable');
  return resolved;
}

async function noSymlinkAncestors(rootfs, destination) {
  const relative = path.relative(rootfs, destination);
  ensure(relative && !path.isAbsolute(relative) && relative !== '..' && !relative.startsWith(`..${path.sep}`),
    'IMAGE_PATH_ESCAPE', 'managed path escaped rootfs');
  let current = rootfs;
  const parts = relative.split(path.sep);
  for (const [index, part] of parts.entries()) {
    current = path.join(current, part);
    try {
      const stat = await fs.promises.lstat(current);
      ensure(!stat.isSymbolicLink(), 'IMAGE_PATH_SYMLINKED', `managed path traverses a symlink: ${current}`);
      if (index < parts.length - 1) ensure(stat.isDirectory(), 'IMAGE_PATH_ANCESTOR_INVALID', `managed path ancestor is not a directory: ${current}`);
    } catch (error) {
      if (error?.code === 'ENOENT') return;
      throw error;
    }
  }
}

async function ensureDirectory(rootfs, absolutePath, mode) {
  const destination = imageTarget(rootfs, absolutePath);
  await noSymlinkAncestors(rootfs, destination);
  await fs.promises.mkdir(destination, { recursive: true, mode });
  await noSymlinkAncestors(rootfs, destination);
  const stat = await fs.promises.lstat(destination);
  ensure(stat.isDirectory() && !stat.isSymbolicLink(), 'IMAGE_DIRECTORY_INVALID', `unsafe image directory: ${absolutePath}`);
  await fs.promises.chmod(destination, mode);
  await fs.promises.chown(destination, 0, 0);
  return destination;
}

async function atomicWrite(rootfs, absolutePath, content, mode, parentMode = 0o755) {
  const destination = imageTarget(rootfs, absolutePath);
  await ensureDirectory(rootfs, path.posix.dirname(absolutePath), parentMode);
  await noSymlinkAncestors(rootfs, destination);
  try {
    const existing = await fs.promises.lstat(destination);
    ensure(existing.isFile() && !existing.isSymbolicLink(), 'IMAGE_DESTINATION_INVALID', `unsafe existing destination: ${absolutePath}`);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
  const temp = path.join(path.dirname(destination), `.${path.basename(destination)}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`);
  try {
    const handle = await fs.promises.open(temp, 'wx', mode);
    try {
      await handle.writeFile(content);
      await handle.sync();
    } finally {
      await handle.close();
    }
    await fs.promises.chmod(temp, mode);
    await fs.promises.chown(temp, 0, 0);
    await fs.promises.rename(temp, destination);
    const dir = await fs.promises.open(path.dirname(destination), 'r');
    try { await dir.sync(); } finally { await dir.close(); }
  } finally {
    await fs.promises.rm(temp, { force: true }).catch(() => {});
  }
  return destination;
}

async function readRegular(file, { maxBytes = 512 * 1024, requireRootOwner = false, forbidWritable = false } = {}) {
  let stat;
  try { stat = await fs.promises.lstat(file); }
  catch (error) { fail('FILE_UNAVAILABLE', `required file is unavailable: ${file}`, error); }
  ensure(stat.isFile() && !stat.isSymbolicLink(), 'FILE_INVALID', `required file must be a regular non-symlink file: ${file}`);
  ensure(stat.size > 0 && stat.size <= maxBytes, 'FILE_SIZE_INVALID', `required file size is outside the verified bound: ${file}`);
  if (requireRootOwner && typeof stat.uid === 'number') ensure(stat.uid === 0, 'FILE_OWNER_INVALID', `required file must be root-owned: ${file}`);
  if (forbidWritable) ensure((stat.mode & 0o022) === 0, 'FILE_MODE_UNSAFE', `required file must not be group/world writable: ${file}`);
  return fs.promises.readFile(file);
}

function sourceFileName(repositoryId) {
  ensure(/^[A-Za-z0-9][A-Za-z0-9._+:-]{0,127}$/.test(repositoryId), 'REPOSITORY_ID_INVALID', 'repository id is invalid');
  return `swir-vendor-${repositoryId.replace(/[^A-Za-z0-9._-]/g, '_')}.sources`;
}

function resolvePolicyProfile(policy, profile) {
  const entry = policy.entries.find(item => item.id === profile.repositoryId);
  ensure(entry, 'PROFILE_POLICY_MISMATCH', `reviewed policy does not contain ${profile.repositoryId}`);
  ensure(entry.automaticEnable === false && entry.mutationAuthorized === false, 'AUTO_ENABLE_FORBIDDEN', 'reviewed vendor repository must never auto-enable');
  ensure(entry.keyring.fingerprint === profile.expectedFingerprint, 'PROFILE_FINGERPRINT_MISMATCH', 'reviewed policy fingerprint does not match the pinned evidence profile');
  ensure(entry.hardwareVendors.includes(profile.hardwareVendor), 'PROFILE_VENDOR_MISMATCH', 'reviewed policy hardware vendor does not match the pinned evidence profile');
  const platform = entry.distributions.find(item => item.id === profile.distribution.id);
  ensure(platform?.versions.includes(profile.distribution.versionId) && platform?.architectures.includes(profile.distribution.architecture),
    'PROFILE_PLATFORM_MISMATCH', 'reviewed policy platform does not match the pinned evidence profile');
  const expectedBase = new URL(profile.basePath, profile.origin).toString();
  ensure(entry.baseUrl === expectedBase, 'PROFILE_URL_MISMATCH', 'reviewed policy repository URL does not match the pinned evidence profile');
  return entry;
}

async function loadReviewedPolicy(policyPath) {
  const absolute = path.resolve(policyPath);
  const stat = await fs.promises.lstat(absolute);
  ensure(stat.isFile() && !stat.isSymbolicLink() && await fs.promises.realpath(absolute) === absolute,
    'POLICY_SOURCE_INVALID', 'reviewed vendor policy must be a regular non-symlink file');
  ensure(stat.size > 0 && stat.size <= 128 * 1024, 'POLICY_SOURCE_SIZE_INVALID', 'reviewed vendor policy size is outside the verified bound');
  const raw = await fs.promises.readFile(absolute);
  let document;
  try { document = JSON.parse(raw.toString('utf8')); }
  catch (error) { fail('POLICY_JSON_INVALID', 'reviewed vendor policy is not valid JSON', error); }
  return { raw, policy: parseVendorOfficialRepositoryPolicy(document) };
}

async function fetchPinnedKey(profile, evidence, fetchImpl = globalThis.fetch) {
  ensure(typeof fetchImpl === 'function', 'FETCH_UNAVAILABLE', 'Fetch API is unavailable');
  const expectedUrl = new URL(profile.keyPath, profile.origin);
  const response = await fetchImpl(expectedUrl, {
    redirect: 'manual',
    headers: { 'user-agent': 'SWIR-OS-vendor-image-trust/0.1' }
  });
  ensure(response?.status === 200 && !response.headers?.get?.('location'), 'KEY_FETCH_INVALID', `pinned vendor key returned HTTP ${response?.status ?? 'unknown'}`);
  const declared = Number(response.headers?.get?.('content-length') || 0);
  if (Number.isFinite(declared) && declared > 0) ensure(declared <= MAX_KEY_BYTES, 'KEY_FETCH_TOO_LARGE', 'pinned vendor key exceeds the verified size bound');
  const bytes = Buffer.from(await response.arrayBuffer());
  ensure(bytes.length > 0 && bytes.length <= MAX_KEY_BYTES, 'KEY_FETCH_TOO_LARGE', 'pinned vendor key is empty or too large');
  ensure(sha256(bytes) === evidence.key.sha256, 'KEY_DIGEST_MISMATCH', 'fetched vendor key no longer matches verified evidence');
  return bytes;
}

function runGpg(args, options = {}) {
  const result = spawnSync('gpg', args, { encoding: 'utf8', maxBuffer: 2 * 1024 * 1024, ...options });
  if (result.error) fail('GPG_FAILED', `gpg failed to start: ${result.error.message}`);
  if (result.status !== 0) fail('GPG_FAILED', `gpg failed with status ${result.status}: ${(result.stderr || '').trim().slice(0, 800)}`);
  return result;
}

function verifyKeyFingerprint(file, expectedFingerprint) {
  const result = runGpg(['--batch', '--with-colons', '--show-keys', file]);
  const fingerprint = parseGpgPrimaryFingerprint(result.stdout);
  ensure(fingerprint && HEX40.test(fingerprint), 'KEY_FINGERPRINT_MISSING', 'staged vendor keyring has no parseable primary fingerprint');
  ensure(fingerprint === expectedFingerprint, 'KEY_FINGERPRINT_MISMATCH', 'staged vendor keyring fingerprint does not match reviewed policy');
  return fingerprint;
}

async function dearmorKey(keyBytes, expectedFingerprint) {
  const tempRoot = await fs.promises.mkdtemp(path.join(os.tmpdir(), 'swir-vendor-image-key-'));
  try {
    const armored = path.join(tempRoot, 'vendor-key.asc');
    const keyring = path.join(tempRoot, 'vendor-keyring.gpg');
    await fs.promises.writeFile(armored, keyBytes, { mode: 0o600, flag: 'wx' });
    verifyKeyFingerprint(armored, expectedFingerprint);
    runGpg(['--batch', '--yes', '--dearmor', '--output', keyring, armored]);
    const bytes = await readRegular(keyring, { maxBytes: MAX_KEYRING_BYTES });
    verifyKeyFingerprint(keyring, expectedFingerprint);
    return bytes;
  } finally {
    await fs.promises.rm(tempRoot, { recursive: true, force: true });
  }
}

async function assertRepositoryDisabled(rootfs, repositoryId) {
  const sourcePath = imageTarget(rootfs, path.posix.join(SOURCE_ROOT, sourceFileName(repositoryId)));
  try {
    await fs.promises.lstat(sourcePath);
    fail('VENDOR_SOURCE_PREENABLED', `vendor repository source must not exist in the final image: ${sourcePath}`);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
}

async function stage({ rootfs, policyPath, profileId }) {
  ensure(typeof process.getuid === 'function' && process.getuid() === 0, 'ROOT_REQUIRED', 'vendor image trust staging must run as root');
  const root = await safeRootfs(rootfs);
  const profile = getVendorRepositoryEvidenceProfile(profileId);
  const { raw: policyRaw, policy } = await loadReviewedPolicy(policyPath);
  const entry = resolvePolicyProfile(policy, profile);
  await assertRepositoryDisabled(root, entry.id);

  const evidence = await collectVendorRepositoryEvidence(profile.id);
  ensure(evidence.repositoryId === entry.id && evidence.key.fingerprint === entry.keyring.fingerprint,
    'EVIDENCE_POLICY_MISMATCH', 'fresh vendor evidence does not match the reviewed policy');
  ensure(Date.parse(evidence.inRelease.effectiveValidUntil) >= Date.now(), 'EVIDENCE_EXPIRED', 'vendor metadata evidence expired before image staging');

  const keyBytes = await fetchPinnedKey(profile, evidence);
  const keyringBytes = await dearmorKey(keyBytes, entry.keyring.fingerprint);
  const keyringDigest = sha256(keyringBytes);
  const policyDigest = sha256(policyRaw);

  await atomicWrite(root, entry.keyring.path, keyringBytes, 0o644);
  await atomicWrite(root, POLICY_TARGET, policyRaw, 0o644);
  const state = {
    schema: STATE_SCHEMA,
    repositoryId: entry.id,
    profileId: profile.id,
    policyPath: POLICY_TARGET,
    policySha256: policyDigest,
    keyringPath: entry.keyring.path,
    keyringSha256: keyringDigest,
    sourceKeySha256: evidence.key.sha256,
    fingerprint: entry.keyring.fingerprint,
    evidence: {
      checkedAt: evidence.inRelease.checkedAt,
      signedAt: evidence.inRelease.signedAt,
      effectiveValidUntil: evidence.inRelease.effectiveValidUntil,
      inReleaseSha256: evidence.inRelease.sha256,
      packagesIndexSha256: evidence.packages.indexSha256,
      requiredPackagesVerified: evidence.packages.verified
    },
    automaticRepositoryEnablement: false,
    sourceConfigured: false,
    stagedAt: new Date().toISOString()
  };
  await atomicWrite(root, STATE_TARGET, Buffer.from(`${JSON.stringify(state, null, 2)}\n`), 0o600, 0o700);
  return verify({ rootfs: root, profileId });
}

async function verify({ rootfs, profileId }) {
  const root = await safeRootfs(rootfs);
  const profile = getVendorRepositoryEvidenceProfile(profileId);
  const policyFile = imageTarget(root, POLICY_TARGET);
  const policyRaw = await readRegular(policyFile, { maxBytes: 128 * 1024, requireRootOwner: true, forbidWritable: true });
  const policy = parseVendorOfficialRepositoryPolicy(JSON.parse(policyRaw.toString('utf8')));
  const entry = resolvePolicyProfile(policy, profile);
  const keyringFile = imageTarget(root, entry.keyring.path);
  const keyringBytes = await readRegular(keyringFile, { maxBytes: MAX_KEYRING_BYTES, requireRootOwner: true, forbidWritable: true });
  const fingerprint = verifyKeyFingerprint(keyringFile, entry.keyring.fingerprint);
  const stateFile = imageTarget(root, STATE_TARGET);
  const stateRaw = await readRegular(stateFile, { maxBytes: 128 * 1024, requireRootOwner: true, forbidWritable: true });
  let state;
  try { state = JSON.parse(stateRaw.toString('utf8')); }
  catch (error) { fail('STATE_JSON_INVALID', 'vendor image trust state is not valid JSON', error); }
  ensure(state?.schema === STATE_SCHEMA && state.repositoryId === entry.id && state.profileId === profile.id,
    'STATE_IDENTITY_INVALID', 'vendor image trust state identity is invalid');
  ensure(HEX64.test(state.policySha256 || '') && state.policySha256 === sha256(policyRaw), 'STATE_POLICY_DIGEST_MISMATCH', 'staged policy digest does not match trust state');
  ensure(HEX64.test(state.keyringSha256 || '') && state.keyringSha256 === sha256(keyringBytes), 'STATE_KEYRING_DIGEST_MISMATCH', 'staged keyring digest does not match trust state');
  ensure(state.fingerprint === fingerprint && state.fingerprint === profile.expectedFingerprint, 'STATE_FINGERPRINT_MISMATCH', 'staged keyring fingerprint does not match trust state');
  ensure(state.automaticRepositoryEnablement === false && state.sourceConfigured === false, 'STATE_AUTO_ENABLE_FORBIDDEN', 'image trust state must record disabled-by-default vendor repository behavior');
  ensure(Number.isFinite(Date.parse(state.evidence?.effectiveValidUntil)) && Date.parse(state.evidence.effectiveValidUntil) >= Date.now(),
    'STATE_EVIDENCE_EXPIRED', 'staged vendor repository evidence is no longer fresh');
  await assertRepositoryDisabled(root, entry.id);
  return Object.freeze({
    schema: STATE_SCHEMA,
    ready: true,
    repositoryId: entry.id,
    profileId: profile.id,
    fingerprint,
    policySha256: state.policySha256,
    keyringSha256: state.keyringSha256,
    evidenceValidUntil: state.evidence.effectiveValidUntil,
    automaticRepositoryEnablement: false,
    sourceConfigured: false
  });
}

async function main() {
  let command = '';
  let rootfs = '';
  let policyPath = DEFAULT_POLICY;
  let profileId = DEFAULT_PROFILE;
  const args = process.argv.slice(2);
  while (args.length) {
    const arg = args.shift();
    if (arg === '--stage' || arg === '--verify') command = arg;
    else if (arg === '--rootfs') rootfs = args.shift() || '';
    else if (arg === '--policy') policyPath = args.shift() || '';
    else if (arg === '--profile') profileId = args.shift() || '';
    else fail('CLI_USAGE', `unknown argument: ${arg}`);
  }
  ensure((command === '--stage' || command === '--verify') && rootfs, 'CLI_USAGE',
    'usage: stage-vendor-repository-trust.mjs --stage|--verify --rootfs <absolute-dir> [--policy <reviewed-json>] [--profile <id>]');
  const result = command === '--stage'
    ? await stage({ rootfs, policyPath, profileId })
    : await verify({ rootfs, profileId });
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
}

export const VendorRepositoryImageTrust = Object.freeze({
  schema: STATE_SCHEMA,
  policyTarget: POLICY_TARGET,
  sourceRoot: SOURCE_ROOT,
  automaticRepositoryEnablement: false,
  directBinaryDownloads: false,
  rootOwnedPolicyRequired: true,
  rootOwnedPinnedKeyringRequired: true,
  signedMetadataFreshnessRequiredAtStaging: true,
  finalImageVerificationRequired: true
});

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main().catch(error => {
    process.stderr.write(`${error.name || 'Error'}:${error.code || 'UNKNOWN'}:${error.message}\n`);
    process.exitCode = 64;
  });
}
