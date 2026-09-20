import crypto from 'node:crypto';

const BINDING_SCHEMA = 'swir.vendor-repository-transaction-binding/0.1';
const REVIEW_SCHEMA = 'swir.vendor-official-repository-review/0.1';
const EVIDENCE_SCHEMA = 'swir.vendor-repository-evidence/0.1';
const SYSTEM_PACKAGE_MANIFEST_SCHEMA = 'swir.package-provider/0.2';
const PACKAGE = /^[a-z0-9][a-z0-9+.-]{0,127}$/;
const REPOSITORY_ID = /^[A-Za-z0-9][A-Za-z0-9._+:-]{0,127}$/;
const APT_SUITE = /^(?:\.\/|[A-Za-z0-9][A-Za-z0-9._+~\/-]{0,127})$/;
const APT_COMPONENT = /^[A-Za-z0-9][A-Za-z0-9._+~-]{0,63}$/;
const PLATFORM_TOKEN = /^[A-Za-z0-9][A-Za-z0-9._+~-]{0,63}$/;
const KEYRING_PATH = /^\/usr\/share\/keyrings\/[A-Za-z0-9][A-Za-z0-9._+~-]{0,127}\.gpg$/;
const HEX40 = /^[A-F0-9]{40}$/;
const HEX64 = /^[a-f0-9]{64}$/;

function fail(code, message) {
  const error = new Error(message);
  error.name = 'VendorRepositoryTransactionBindingError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function object(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function stableStringify(value) {
  if (value === null || typeof value !== 'object') return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(stableStringify).join(',')}]`;
  return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${stableStringify(value[key])}`).join(',')}}`;
}

function digest(value) {
  return crypto.createHash('sha256').update(stableStringify(value), 'utf8').digest('hex');
}

function normalizeBaseUrl(raw) {
  let url;
  try { url = new URL(String(raw)); } catch { fail('BINDING_URL_INVALID', 'review baseUrl must be an absolute URL'); }
  assert(url.protocol === 'https:', 'BINDING_URL_SCHEME_INVALID', 'review baseUrl must use HTTPS');
  assert(!url.username && !url.password && !url.search && !url.hash, 'BINDING_URL_DECORATION_FORBIDDEN', 'review baseUrl must not contain credentials, query or fragment data');
  if (!url.pathname.endsWith('/')) url.pathname += '/';
  return url.toString();
}

function evidenceBaseUrl(evidence) {
  assert(typeof evidence?.source?.origin === 'string' && typeof evidence?.source?.basePath === 'string', 'BINDING_EVIDENCE_SOURCE_INVALID', 'evidence source origin and basePath are required');
  const origin = new URL(evidence.source.origin);
  const resolved = new URL(evidence.source.basePath, origin);
  assert(resolved.origin === origin.origin, 'BINDING_EVIDENCE_SOURCE_INVALID', 'evidence basePath escaped the pinned origin');
  return normalizeBaseUrl(resolved.toString());
}

function validAptSuite(value) {
  if (typeof value !== 'string' || !APT_SUITE.test(value)) return false;
  if (value === './') return true;
  if (value.includes('//')) return false;
  return !value.split('/').some(segment => segment === '..' || segment === '');
}

function validateAptScope(review) {
  assert(Array.isArray(review.suites) && review.suites.length > 0 && review.suites.length <= 16, 'BINDING_REVIEW_SUITES_INVALID', 'review APT suites must be a bounded non-empty token list');
  assert(review.suites.every(validAptSuite), 'BINDING_REVIEW_SUITES_INVALID', 'review APT suite contains whitespace, control data or an unsafe path token');
  assert(new Set(review.suites).size === review.suites.length, 'BINDING_REVIEW_SUITES_INVALID', 'review APT suites must not contain duplicates');
  assert(Array.isArray(review.components) && review.components.length <= 32, 'BINDING_REVIEW_COMPONENTS_INVALID', 'review APT components must be a bounded token list');
  assert(review.components.every(value => typeof value === 'string' && APT_COMPONENT.test(value)), 'BINDING_REVIEW_COMPONENTS_INVALID', 'review APT component contains whitespace or control data');
  assert(new Set(review.components).size === review.components.length, 'BINDING_REVIEW_COMPONENTS_INVALID', 'review APT components must not contain duplicates');
}

function validatePlatform(platform, code) {
  assert(object(platform) && PLATFORM_TOKEN.test(String(platform.id || '')) && PLATFORM_TOKEN.test(String(platform.versionId || '')) && PLATFORM_TOKEN.test(String(platform.architecture || '')), code, 'repository platform binding is incomplete or contains unsafe token data');
}

function validateReview(review) {
  assert(object(review) && review.schema === REVIEW_SCHEMA, 'BINDING_REVIEW_INVALID', 'trusted vendor repository review is required');
  assert(review?.source?.class === 'vendor-official-repository', 'BINDING_REVIEW_SOURCE_INVALID', 'review must retain vendor-official-repository source class');
  assert(review.trustedSource === true, 'BINDING_REVIEW_TRUST_INVALID', 'review must originate from trusted root-owned policy');
  assert(review.directBinaryDownloads === false, 'BINDING_DIRECT_DOWNLOAD_FORBIDDEN', 'review must forbid direct binary downloads');
  assert(review.mutationAuthorized === false && review.automaticEnable === false, 'BINDING_REVIEW_PREAUTHORIZED', 'review must not pre-authorize repository mutation');
  assert(typeof review.repositoryId === 'string' && REPOSITORY_ID.test(review.repositoryId), 'BINDING_REPOSITORY_ID_INVALID', 'review repository id is invalid');
  assert(review?.source?.ref === `vendor-repo:${review.repositoryId}`, 'BINDING_REVIEW_SOURCE_INVALID', 'review source ref must bind exactly to repositoryId');
  assert(review.packageManager === 'apt', 'BINDING_PACKAGE_MANAGER_INVALID', 'initial vendor repository binding supports apt only');
  normalizeBaseUrl(review.baseUrl);
  validateAptScope(review);
  assert(Array.isArray(review.packages) && review.packages.length > 0 && review.packages.length <= 256 && review.packages.every(name => PACKAGE.test(name)), 'BINDING_REVIEW_PACKAGES_INVALID', 'review package allowlist is invalid');
  assert(new Set(review.packages).size === review.packages.length, 'BINDING_REVIEW_PACKAGES_INVALID', 'review package allowlist must not contain duplicates');
  assert(typeof review?.keyring?.path === 'string' && KEYRING_PATH.test(review.keyring.path), 'BINDING_REVIEW_KEYRING_PATH_INVALID', 'review keyring path must be a pinned root-owned /usr/share/keyrings/*.gpg file');
  assert(HEX40.test(String(review?.keyring?.fingerprint || '').toUpperCase()), 'BINDING_REVIEW_FINGERPRINT_INVALID', 'review must retain a full 40-hex signing-key fingerprint');
  assert(/^[a-f0-9]{4}$/i.test(String(review.hardwareVendor || '')), 'BINDING_REVIEW_HARDWARE_VENDOR_INVALID', 'review hardware vendor must be a four-hex PCI vendor id');
  validatePlatform(review.distribution, 'BINDING_REVIEW_PLATFORM_INVALID');
  return review;
}

function validateEvidence(evidence, now) {
  assert(object(evidence) && evidence.schema === EVIDENCE_SCHEMA, 'BINDING_EVIDENCE_INVALID', 'qualified vendor repository evidence is required');
  assert(evidence.qualificationOnly === true, 'BINDING_EVIDENCE_MODE_INVALID', 'vendor evidence must remain qualification-only');
  assert(evidence.authorizesMutation === false && evidence.authorizesRepositoryEnablement === false, 'BINDING_EVIDENCE_PREAUTHORIZED', 'qualification evidence must never authorize mutation or repository enablement');
  assert(typeof evidence.repositoryId === 'string' && REPOSITORY_ID.test(evidence.repositoryId), 'BINDING_EVIDENCE_REPOSITORY_INVALID', 'evidence repository id is invalid');
  assert(/^[a-f0-9]{4}$/i.test(String(evidence.hardwareVendor || '')), 'BINDING_EVIDENCE_HARDWARE_VENDOR_INVALID', 'evidence hardware vendor must be a four-hex PCI vendor id');
  assert(HEX40.test(String(evidence?.key?.fingerprint || '').toUpperCase()), 'BINDING_EVIDENCE_FINGERPRINT_INVALID', 'evidence full signing-key fingerprint is required');
  assert(evidence?.inRelease?.freshnessVerified === true, 'BINDING_EVIDENCE_FRESHNESS_REQUIRED', 'signed repository metadata freshness must be verified');
  const expiry = Date.parse(evidence?.inRelease?.effectiveValidUntil);
  assert(Number.isFinite(expiry), 'BINDING_EVIDENCE_EXPIRY_INVALID', 'evidence effective expiry is invalid');
  assert(expiry >= now.getTime(), 'BINDING_EVIDENCE_EXPIRED', 'vendor repository qualification evidence has expired');
  assert(HEX64.test(String(evidence?.inRelease?.sha256 || '')), 'BINDING_EVIDENCE_DIGEST_INVALID', 'InRelease SHA-256 evidence is required');
  assert(HEX64.test(String(evidence?.packages?.indexSha256 || '')), 'BINDING_EVIDENCE_DIGEST_INVALID', 'Packages index SHA-256 evidence is required');
  assert(HEX64.test(String(evidence?.key?.sha256 || '')), 'BINDING_EVIDENCE_DIGEST_INVALID', 'signing-key SHA-256 evidence is required');
  assert(Array.isArray(evidence?.packages?.verified) && evidence.packages.verified.length > 0 && evidence.packages.verified.length <= 256 && evidence.packages.verified.every(name => PACKAGE.test(name)), 'BINDING_EVIDENCE_PACKAGES_INVALID', 'verified evidence package set is invalid');
  assert(new Set(evidence.packages.verified).size === evidence.packages.verified.length, 'BINDING_EVIDENCE_PACKAGES_INVALID', 'verified evidence package set must not contain duplicates');
  validatePlatform(evidence.distribution, 'BINDING_EVIDENCE_PLATFORM_INVALID');
  return evidence;
}

function samePlatform(a, b) {
  return a.id === b.id && a.versionId === b.versionId && a.architecture === b.architecture;
}

function packageManifests(repositoryId, bindingDigest, packages) {
  return packages.map(packageName => Object.freeze({
    schema: SYSTEM_PACKAGE_MANIFEST_SCHEMA,
    id: `vendor.${repositoryId}.${packageName}`,
    targetEditions: ['system'],
    executionClass: 'linux-native',
    provider: 'swir.package.system',
    package: Object.freeze({ sourceRef: packageName }),
    trust: Object.freeze({
      sourceClass: 'distribution-repository',
      repositoryId,
      signatureRequired: true,
      upstreamSourceClass: 'vendor-official-repository',
      vendorRepositoryBindingDigest: bindingDigest
    })
  }));
}

export function bindVendorRepositoryTransaction({ review, evidence, requestedPackages, now = new Date() } = {}) {
  validateReview(review);
  const current = now instanceof Date ? new Date(now.getTime()) : new Date(now);
  assert(Number.isFinite(current.getTime()), 'BINDING_CLOCK_INVALID', 'binding requires a valid current time');
  validateEvidence(evidence, current);

  assert(review.repositoryId === evidence.repositoryId, 'BINDING_REPOSITORY_MISMATCH', 'policy review and qualification evidence repository ids differ');
  assert(review.hardwareVendor === evidence.hardwareVendor, 'BINDING_HARDWARE_VENDOR_MISMATCH', 'policy review and qualification evidence hardware vendors differ');
  assert(samePlatform(review.distribution, evidence.distribution), 'BINDING_PLATFORM_MISMATCH', 'policy review and qualification evidence platforms differ');
  assert(normalizeBaseUrl(review.baseUrl) === evidenceBaseUrl(evidence), 'BINDING_BASE_URL_MISMATCH', 'policy review and qualification evidence repository URLs differ');

  const reviewFingerprint = String(review.keyring.fingerprint).toUpperCase();
  const evidenceFingerprint = String(evidence.key.fingerprint).toUpperCase();
  assert(reviewFingerprint === evidenceFingerprint, 'BINDING_FINGERPRINT_MISMATCH', 'root-owned policy fingerprint does not match qualified evidence');
  assert(String(evidence.key.expectedFingerprint || '').toUpperCase() === evidenceFingerprint, 'BINDING_EVIDENCE_FINGERPRINT_MISMATCH', 'qualification evidence does not retain its pinned expected fingerprint');
  assert(String(evidence.inRelease.validSignaturePrimaryFingerprint || '').toUpperCase() === evidenceFingerprint, 'BINDING_SIGNATURE_MISMATCH', 'qualified InRelease signature is not bound to the pinned primary fingerprint');

  assert(Array.isArray(requestedPackages) && requestedPackages.length > 0, 'BINDING_PACKAGES_REQUIRED', 'at least one package must be explicitly requested');
  const requested = [...new Set(requestedPackages.map(value => String(value)))].sort();
  assert(requested.every(name => PACKAGE.test(name)), 'BINDING_PACKAGE_INVALID', 'requested package name is invalid');
  const policyPackages = new Set(review.packages);
  const evidencePackages = new Set(evidence.packages.verified);
  for (const name of requested) {
    assert(policyPackages.has(name), 'BINDING_PACKAGE_NOT_ALLOWLISTED', `package is outside root-owned policy allowlist: ${name}`);
    assert(evidencePackages.has(name), 'BINDING_PACKAGE_NOT_QUALIFIED', `package is outside qualified metadata evidence: ${name}`);
  }

  const bound = Object.freeze({
    repository: Object.freeze({
      id: review.repositoryId,
      vendor: review.vendor,
      sourceClass: 'vendor-official-repository',
      packageManager: 'apt',
      baseUrl: normalizeBaseUrl(review.baseUrl),
      suites: Object.freeze([...review.suites]),
      components: Object.freeze([...review.components])
    }),
    platform: Object.freeze({ ...review.distribution, hardwareVendor: review.hardwareVendor }),
    key: Object.freeze({
      keyringPath: review.keyring.path,
      fingerprint: evidenceFingerprint,
      fetchedKeySha256: evidence.key.sha256
    }),
    metadata: Object.freeze({
      inReleaseSha256: evidence.inRelease.sha256,
      packagesIndexSha256: evidence.packages.indexSha256,
      signedAt: evidence.inRelease.signedAt,
      effectiveValidUntil: evidence.inRelease.effectiveValidUntil,
      evidenceCheckedAt: evidence.inRelease.checkedAt
    }),
    packages: Object.freeze(requested)
  });
  const bindingDigest = digest(bound);

  return Object.freeze({
    schema: BINDING_SCHEMA,
    mode: 'preview',
    readOnly: true,
    autoExecutable: false,
    qualificationOnly: false,
    mutationAuthorized: false,
    repositoryEnablementAuthorized: false,
    requiresExplicitConfirmation: true,
    bindingDigest,
    bound,
    packagePlanInputs: Object.freeze(packageManifests(review.repositoryId, bindingDigest, requested)),
    transactionRoute: Object.freeze({
      packageProvider: 'swir.package.system',
      packagePlanSchema: 'swir.system-package-plan/0.1',
      packageTransactionSchema: 'swir.system-package-transaction/0.1',
      driverTransactionSchema: 'swir.driver-mutation-transaction/0.1',
      durableJournalRequired: true,
      existingBrokerRequired: true,
      directAptMutationAllowed: false,
      directPkexecAllowed: false,
      repositoryActivationImplementedHere: false
    })
  });
}

export function assertVendorRepositoryTransactionBinding(binding) {
  assert(object(binding) && binding.schema === BINDING_SCHEMA, 'BINDING_SCHEMA_INVALID', 'vendor repository transaction binding schema mismatch');
  assert(binding.mode === 'preview' && binding.readOnly === true && binding.autoExecutable === false, 'BINDING_MODE_INVALID', 'binding must remain a read-only preview');
  assert(binding.mutationAuthorized === false && binding.repositoryEnablementAuthorized === false, 'BINDING_PREAUTHORIZED', 'binding must not authorize privileged mutation');
  assert(binding.requiresExplicitConfirmation === true, 'BINDING_CONFIRMATION_REQUIRED', 'binding must require explicit confirmation downstream');
  assert(HEX64.test(String(binding.bindingDigest || '')), 'BINDING_DIGEST_INVALID', 'binding digest is invalid');
  assert(binding.bindingDigest === digest(binding.bound), 'BINDING_DIGEST_MISMATCH', 'binding digest no longer matches the bound trust scope');
  assert(binding.transactionRoute?.durableJournalRequired === true && binding.transactionRoute?.existingBrokerRequired === true, 'BINDING_TRANSACTION_ROUTE_INVALID', 'binding must route through the existing journaled broker');
  assert(binding.transactionRoute?.directAptMutationAllowed === false && binding.transactionRoute?.directPkexecAllowed === false, 'BINDING_DIRECT_MUTATION_FORBIDDEN', 'binding must not expose direct privileged mutation');
  return true;
}

export const VendorRepositoryTransactionBindingPolicy = Object.freeze({
  schema: BINDING_SCHEMA,
  sideEffectFree: true,
  requiresRootOwnedPolicyReview: true,
  requiresFreshQualifiedEvidence: true,
  requiresFullFingerprintMatch: true,
  requiresExactRepositoryAndPlatformMatch: true,
  packageIntersectionRequired: true,
  deterministicDigestBinding: true,
  aptDeb822TokensValidatedBeforeBinding: true,
  exactSourceReferenceBindingRequired: true,
  pinnedKeyringPathValidatedBeforeBinding: true,
  existingJournaledPackageBrokerRequired: true,
  repositoryActivationImplementedHere: false,
  directAptMutationAllowed: false,
  directPkexecAllowed: false
});
