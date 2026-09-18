import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const fsp = fs.promises;
const POLICY_SCHEMA = 'swir.vendor-official-repository-policy/0.1';
const REVIEW_SCHEMA = 'swir.vendor-official-repository-review/0.1';
const SOURCE_CLASS = 'vendor-official-repository';
const MAX_POLICY_BYTES = 128 * 1024;
const MAX_ENTRIES = 64;
const MAX_PACKAGES_PER_ENTRY = 128;
const MAX_HOSTS_PER_ENTRY = 8;
const MAX_DISTRIBUTIONS_PER_ENTRY = 16;
const SAFE_TOKEN = /^[A-Za-z0-9][A-Za-z0-9._+:-]{0,127}$/;
const SAFE_PACKAGE = /^[a-z0-9][a-z0-9+.-]{0,127}$/;
const SAFE_HOST = /^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$/;
const KEYRING_ROOT = '/usr/share/keyrings/';

function fail(code, message) {
  const error = new Error(message);
  error.name = 'VendorOfficialRepositoryPolicyError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function text(value, max = 256) {
  const result = String(value ?? '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim();
  return result.slice(0, max);
}

function boundedStringList(value, { maxItems, pattern = SAFE_TOKEN, field }) {
  assert(Array.isArray(value), 'POLICY_FIELD_INVALID', `${field} must be an array`);
  assert(value.length <= maxItems, 'POLICY_FIELD_TOO_LARGE', `${field} exceeds its verified item bound`);
  const normalized = [];
  for (const raw of value) {
    const item = text(raw, 160);
    assert(item && pattern.test(item), 'POLICY_TOKEN_INVALID', `${field} contains an invalid token`);
    if (!normalized.includes(item)) normalized.push(item);
  }
  return normalized;
}

function normalizeHost(raw) {
  const host = text(raw, 253).toLowerCase();
  assert(SAFE_HOST.test(host), 'POLICY_HOST_INVALID', `Invalid official vendor host: ${host || '<empty>'}`);
  return host;
}

function normalizeRepositoryUrl(raw, officialHosts) {
  let url;
  try { url = new URL(String(raw)); } catch { fail('POLICY_URL_INVALID', 'Vendor repository URL must be an absolute URL'); }
  assert(url.protocol === 'https:', 'POLICY_URL_SCHEME_INVALID', 'Vendor repository URL must use HTTPS');
  assert(!url.username && !url.password, 'POLICY_URL_CREDENTIALS_FORBIDDEN', 'Vendor repository URL must not contain credentials');
  assert(!url.search && !url.hash, 'POLICY_URL_DECORATION_FORBIDDEN', 'Vendor repository URL must not contain query or fragment data');
  assert(officialHosts.includes(url.hostname.toLowerCase()), 'POLICY_URL_HOST_NOT_ALLOWLISTED', 'Vendor repository URL host is not in the entry allowlist');
  return url.toString();
}

function normalizeKeyring(raw) {
  assert(raw && typeof raw === 'object' && !Array.isArray(raw), 'POLICY_KEYRING_INVALID', 'keyring must be an object');
  const keyringPath = text(raw.path, 4096);
  assert(path.posix.isAbsolute(keyringPath), 'POLICY_KEYRING_PATH_INVALID', 'Vendor signing keyring path must be absolute');
  assert(keyringPath.startsWith(KEYRING_ROOT), 'POLICY_KEYRING_PATH_INVALID', `Vendor signing keyring must live under ${KEYRING_ROOT}`);
  assert(!keyringPath.includes('/../') && !keyringPath.endsWith('/..'), 'POLICY_KEYRING_PATH_INVALID', 'Vendor signing keyring path must not traverse parents');
  assert(keyringPath.endsWith('.gpg'), 'POLICY_KEYRING_PATH_INVALID', 'Vendor signing keyring must be a .gpg file');
  const fingerprint = text(raw.fingerprint, 80).replace(/\s+/g, '').toUpperCase();
  assert(/^[A-F0-9]{40}$/.test(fingerprint), 'POLICY_KEY_FINGERPRINT_INVALID', 'Vendor signing key fingerprint must be exactly 40 hexadecimal characters');
  assert(raw.downloadUrl === undefined && raw.keyUrl === undefined, 'POLICY_KEY_DOWNLOAD_FORBIDDEN', 'Vendor policy must not contain a signing-key download URL');
  return Object.freeze({ path: keyringPath, fingerprint });
}

function normalizeDistribution(raw) {
  assert(raw && typeof raw === 'object' && !Array.isArray(raw), 'POLICY_DISTRIBUTION_INVALID', 'distribution entry must be an object');
  const id = text(raw.id, 64).toLowerCase();
  assert(/^[a-z0-9][a-z0-9._-]{0,63}$/.test(id), 'POLICY_DISTRIBUTION_INVALID', 'distribution id is invalid');
  const versions = boundedStringList(raw.versions ?? [], { maxItems: 16, pattern: SAFE_TOKEN, field: 'distribution.versions' });
  const architectures = boundedStringList(raw.architectures ?? [], { maxItems: 16, pattern: SAFE_TOKEN, field: 'distribution.architectures' });
  assert(versions.length > 0 && architectures.length > 0, 'POLICY_DISTRIBUTION_INVALID', 'distribution versions and architectures must be explicit');
  return Object.freeze({ id, versions, architectures });
}

function normalizeEntry(raw) {
  assert(raw && typeof raw === 'object' && !Array.isArray(raw), 'POLICY_ENTRY_INVALID', 'repository entry must be an object');
  const id = text(raw.id, 128);
  const vendor = text(raw.vendor, 160);
  assert(id && SAFE_TOKEN.test(id), 'POLICY_ENTRY_ID_INVALID', 'repository id is invalid');
  assert(vendor, 'POLICY_VENDOR_INVALID', 'repository vendor name is required');
  assert(raw.sourceClass === SOURCE_CLASS, 'POLICY_SOURCE_CLASS_INVALID', `sourceClass must be ${SOURCE_CLASS}`);
  assert(raw.enabled === true || raw.enabled === false, 'POLICY_ENABLED_INVALID', 'enabled must be boolean');
  assert(raw.packageManager === 'apt', 'POLICY_PACKAGE_MANAGER_INVALID', 'initial vendor repository policy supports apt only');
  assert(raw.directBinaryDownloads === false, 'POLICY_DIRECT_DOWNLOAD_FORBIDDEN', 'directBinaryDownloads must be false');
  assert(raw.automaticEnable === false, 'POLICY_AUTO_ENABLE_FORBIDDEN', 'automaticEnable must be false');
  assert(raw.arbitraryPackages === false, 'POLICY_ARBITRARY_PACKAGES_FORBIDDEN', 'arbitraryPackages must be false');

  const officialHosts = boundedStringList(raw.officialHosts, { maxItems: MAX_HOSTS_PER_ENTRY, pattern: SAFE_HOST, field: 'officialHosts' }).map(normalizeHost);
  assert(officialHosts.length > 0, 'POLICY_HOST_INVALID', 'at least one official vendor host is required');
  const baseUrl = normalizeRepositoryUrl(raw.baseUrl, officialHosts);
  const distributionsRaw = raw.distributions;
  assert(Array.isArray(distributionsRaw) && distributionsRaw.length > 0 && distributionsRaw.length <= MAX_DISTRIBUTIONS_PER_ENTRY,
    'POLICY_DISTRIBUTION_INVALID', 'at least one bounded distribution mapping is required');
  const distributions = distributionsRaw.map(normalizeDistribution);
  const suites = boundedStringList(raw.suites, { maxItems: 16, pattern: SAFE_TOKEN, field: 'suites' });
  const components = boundedStringList(raw.components, { maxItems: 16, pattern: SAFE_TOKEN, field: 'components' });
  const packages = boundedStringList(raw.packages, { maxItems: MAX_PACKAGES_PER_ENTRY, pattern: SAFE_PACKAGE, field: 'packages' });
  const hardwareVendors = boundedStringList(raw.hardwareVendors, { maxItems: 64, pattern: /^[A-Fa-f0-9]{4}$/, field: 'hardwareVendors' }).map(value => value.toLowerCase());
  assert(packages.length > 0, 'POLICY_PACKAGES_EMPTY', 'vendor repository must allowlist at least one package');
  assert(hardwareVendors.length > 0, 'POLICY_HARDWARE_VENDOR_EMPTY', 'vendor repository must bind at least one PCI/USB vendor id');

  return Object.freeze({
    id, vendor, enabled: raw.enabled, sourceClass: SOURCE_CLASS, packageManager: 'apt', officialHosts,
    baseUrl, distributions, suites, components, packages, hardwareVendors,
    keyring: normalizeKeyring(raw.keyring), directBinaryDownloads: false, automaticEnable: false,
    arbitraryPackages: false, mutationAuthorized: false
  });
}

export function parseVendorOfficialRepositoryPolicy(document) {
  assert(document && typeof document === 'object' && !Array.isArray(document), 'POLICY_ROOT_INVALID', 'vendor repository policy root must be an object');
  assert(document.schema === POLICY_SCHEMA, 'POLICY_SCHEMA_INVALID', `vendor repository policy schema must be ${POLICY_SCHEMA}`);
  assert(document.failClosed === true, 'POLICY_FAIL_CLOSED_REQUIRED', 'vendor repository policy must declare failClosed=true');
  assert(document.defaultEnabled === false, 'POLICY_DEFAULT_ENABLE_FORBIDDEN', 'vendor repositories must be disabled by default');
  assert(document.allowDirectBinaryDownloads === false, 'POLICY_DIRECT_DOWNLOAD_FORBIDDEN', 'direct binary downloads must be globally disabled');
  assert(Array.isArray(document.entries) && document.entries.length <= MAX_ENTRIES, 'POLICY_ENTRIES_INVALID', 'vendor repository entries must be a bounded array');
  const entries = document.entries.map(normalizeEntry);
  const ids = new Set();
  for (const entry of entries) {
    assert(!ids.has(entry.id), 'POLICY_ENTRY_DUPLICATE', `duplicate vendor repository id: ${entry.id}`);
    ids.add(entry.id);
  }
  return Object.freeze({ schema: POLICY_SCHEMA, failClosed: true, defaultEnabled: false, allowDirectBinaryDownloads: false, entries });
}

export async function loadVendorOfficialRepositoryPolicy(policyPath = '/etc/swir/hardware/vendor-repositories.json') {
  const requested = path.resolve(String(policyPath));
  let stat;
  try { stat = await fsp.lstat(requested); } catch (error) { fail('POLICY_FILE_UNAVAILABLE', `vendor repository policy is unavailable: ${error.message}`); }
  assert(stat.isFile(), 'POLICY_FILE_INVALID', 'vendor repository policy must be a regular file');
  assert(!stat.isSymbolicLink(), 'POLICY_FILE_SYMLINKED', 'vendor repository policy must not be a symbolic link');
  assert(stat.size > 0 && stat.size <= MAX_POLICY_BYTES, 'POLICY_FILE_SIZE_INVALID', 'vendor repository policy size is outside the verified bound');
  assert((stat.mode & 0o022) === 0, 'POLICY_FILE_WRITABLE', 'vendor repository policy must not be writable by group or others');
  if (typeof stat.uid === 'number') assert(stat.uid === 0, 'POLICY_FILE_OWNER_INVALID', 'vendor repository policy must be root-owned');
  const real = await fsp.realpath(requested);
  assert(real === requested, 'POLICY_FILE_PATH_CHANGED', 'vendor repository policy must resolve exactly to the requested path');
  const raw = await fsp.readFile(requested, 'utf8');
  let document;
  try { document = JSON.parse(raw); } catch { fail('POLICY_JSON_INVALID', 'vendor repository policy is not valid JSON'); }
  return parseVendorOfficialRepositoryPolicy(document);
}

export function resolveVendorOfficialRepositories(policy, { hardwareVendor, distributionId, versionId, architecture }) {
  assert(policy?.schema === POLICY_SCHEMA, 'POLICY_SCHEMA_INVALID', 'trusted vendor repository policy is required');
  const vendorId = text(hardwareVendor, 8).toLowerCase();
  const distro = text(distributionId, 64).toLowerCase();
  const version = text(versionId, 64);
  const arch = text(architecture, 64);
  assert(/^[a-f0-9]{4}$/.test(vendorId), 'QUERY_VENDOR_INVALID', 'hardware vendor id must be four hexadecimal characters');
  assert(distro && version && arch, 'QUERY_PLATFORM_INVALID', 'distribution id, version and architecture are required');

  return policy.entries.filter(entry => {
    if (!entry.enabled || !entry.hardwareVendors.includes(vendorId)) return false;
    return entry.distributions.some(item => item.id === distro && item.versions.includes(version) && item.architectures.includes(arch));
  }).map(entry => Object.freeze({
    schema: REVIEW_SCHEMA,
    repositoryId: entry.id,
    vendor: entry.vendor,
    source: Object.freeze({ class: SOURCE_CLASS, ref: `vendor-repo:${entry.id}` }),
    packageManager: 'apt', baseUrl: entry.baseUrl, suites: entry.suites, components: entry.components,
    packages: entry.packages, keyring: entry.keyring, hardwareVendor: vendorId,
    distribution: Object.freeze({ id: distro, versionId: version, architecture: arch }),
    trustedSource: true, directBinaryDownloads: false, mutationAuthorized: false, automaticEnable: false
  }));
}

export function assertSafeVendorRepositoryReview(candidate) {
  assert(candidate?.schema === REVIEW_SCHEMA, 'REVIEW_SCHEMA_INVALID', 'vendor repository review schema mismatch');
  assert(candidate?.source?.class === SOURCE_CLASS, 'REVIEW_SOURCE_INVALID', 'review candidate source class mismatch');
  assert(candidate.trustedSource === true, 'REVIEW_TRUST_INVALID', 'review candidate must originate from trusted root-owned policy');
  assert(candidate.directBinaryDownloads === false, 'REVIEW_DIRECT_DOWNLOAD_FORBIDDEN', 'review candidate must not allow direct binary downloads');
  assert(candidate.mutationAuthorized === false && candidate.automaticEnable === false, 'REVIEW_PREAUTHORIZED', 'review candidate must never pre-authorize repository mutation');
  assert(Array.isArray(candidate.packages) && candidate.packages.length > 0, 'REVIEW_PACKAGES_INVALID', 'review candidate must retain explicit package allowlist');
  assert(typeof candidate.keyring?.path === 'string' && candidate.keyring.path.startsWith(KEYRING_ROOT), 'REVIEW_KEYRING_INVALID', 'review candidate keyring must remain under trusted keyring root');
  return true;
}

export const VendorOfficialRepositoryPolicy = Object.freeze({
  schema: POLICY_SCHEMA,
  sourceClass: SOURCE_CLASS,
  rootOwnedPolicyPath: '/etc/swir/hardware/vendor-repositories.json',
  packageManager: 'apt',
  directBinaryDownloads: false,
  automaticEnable: false,
  arbitraryPackages: false,
  mutationRequiresExistingJournaledPackageBroker: true,
  productionNetworkFetchImplemented: false
});

async function main() {
  const [, , command, policyPath, vendorId, distroId, versionId, architecture] = process.argv;
  if (command === '--verify') {
    const policy = await loadVendorOfficialRepositoryPolicy(policyPath);
    process.stdout.write(JSON.stringify({ schema: policy.schema, entries: policy.entries.length, verified: true }) + '\n');
    return;
  }
  if (command === '--resolve') {
    const policy = await loadVendorOfficialRepositoryPolicy(policyPath);
    const candidates = resolveVendorOfficialRepositories(policy, { hardwareVendor: vendorId, distributionId: distroId, versionId, architecture });
    for (const candidate of candidates) assertSafeVendorRepositoryReview(candidate);
    process.stdout.write(JSON.stringify({ schema: REVIEW_SCHEMA, candidates }) + '\n');
    return;
  }
  fail('CLI_USAGE', 'usage: vendor-official-repository-service.mjs --verify <policy> | --resolve <policy> <vendor-id> <distro> <version> <arch>');
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main().catch(error => {
    process.stderr.write(`${error.name || 'Error'}:${error.code || 'UNKNOWN'}:${error.message}\n`);
    process.exitCode = 64;
  });
}
