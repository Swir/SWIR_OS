import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import zlib from 'node:zlib';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const EVIDENCE_SCHEMA = 'swir.vendor-repository-evidence/0.1';
const MAX_KEY_BYTES = 128 * 1024;
const MAX_INRELEASE_BYTES = 512 * 1024;
const MAX_PACKAGES_GZ_BYTES = 4 * 1024 * 1024;
const MAX_PACKAGES_BYTES = 32 * 1024 * 1024;
const MAX_INRELEASE_AGE_MS = 14 * 24 * 60 * 60 * 1000;
const MAX_FUTURE_SKEW_MS = 24 * 60 * 60 * 1000;
const HEX40 = /^[A-F0-9]{40}$/;
const KEY_ID = /^[A-F0-9]{8,16}$/;
const PACKAGE = /^[a-z0-9][a-z0-9+.-]{0,127}$/;

const PROFILES = Object.freeze({
  'nvidia-debian13-amd64': Object.freeze({
    id: 'nvidia-debian13-amd64',
    vendor: 'NVIDIA',
    repositoryId: 'nvidia-cuda-debian13-x86_64',
    hardwareVendor: '10de',
    distribution: Object.freeze({ id: 'debian', versionId: '13', architecture: 'x86_64' }),
    origin: 'https://developer.download.nvidia.com',
    basePath: '/compute/cuda/repos/debian13/x86_64/',
    keyPath: '/compute/cuda/repos/debian13/x86_64/8793F200.pub',
    inReleasePath: '/compute/cuda/repos/debian13/x86_64/InRelease',
    packagesPath: '/compute/cuda/repos/debian13/x86_64/Packages.gz',
    expectedKeyId: '8793F200',
    expectedFingerprint: '02182E60104FCDC26EAE1B8597A5D4CB8793F200',
    requiredPackages: Object.freeze(['cuda-keyring', 'nvidia-open'])
  })
});

function fail(code, message) {
  const error = new Error(message);
  error.name = 'VendorRepositoryEvidenceError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function sha256(buffer) {
  return crypto.createHash('sha256').update(buffer).digest('hex');
}

function normalizeNow(value = new Date()) {
  const now = value instanceof Date ? new Date(value.getTime()) : new Date(value);
  assert(Number.isFinite(now.getTime()), 'CLOCK_INVALID', 'freshness verification requires a valid current time');
  return now;
}

function normalizeUrl(profile, pathname) {
  assert(profile && typeof profile === 'object', 'PROFILE_INVALID', 'vendor evidence profile is invalid');
  assert(typeof profile.origin === 'string' && typeof pathname === 'string', 'PROFILE_INVALID', 'profile URL data is invalid');
  const url = new URL(pathname, profile.origin);
  const origin = new URL(profile.origin);
  assert(url.protocol === 'https:', 'PROFILE_URL_SCHEME_INVALID', 'qualification URLs must use HTTPS');
  assert(url.origin === origin.origin, 'PROFILE_URL_ORIGIN_INVALID', 'qualification URL escaped its pinned origin');
  assert(!url.username && !url.password && !url.search && !url.hash, 'PROFILE_URL_DECORATION_FORBIDDEN', 'qualification URL must not contain credentials, query or fragment data');
  assert(url.pathname.startsWith(profile.basePath), 'PROFILE_URL_PATH_INVALID', 'qualification URL escaped its pinned repository path');
  return url.toString();
}

function validateProfile(profile) {
  assert(profile && typeof profile === 'object', 'PROFILE_INVALID', 'vendor evidence profile is invalid');
  assert(/^[a-z0-9][a-z0-9._-]{1,127}$/.test(profile.id), 'PROFILE_ID_INVALID', 'profile id is invalid');
  assert(/^[a-f0-9]{4}$/.test(profile.hardwareVendor), 'PROFILE_VENDOR_ID_INVALID', 'hardware vendor id must be four hexadecimal characters');
  assert(KEY_ID.test(profile.expectedKeyId), 'PROFILE_KEY_ID_INVALID', 'expected key id must be 8-16 uppercase hexadecimal characters');
  assert(HEX40.test(profile.expectedFingerprint), 'PROFILE_FINGERPRINT_INVALID', 'expected primary signing-key fingerprint must be exactly 40 uppercase hexadecimal characters');
  assert(profile.expectedFingerprint.endsWith(profile.expectedKeyId), 'PROFILE_KEY_ID_MISMATCH', 'profile key id must match the pinned full fingerprint');
  assert(Array.isArray(profile.requiredPackages) && profile.requiredPackages.length > 0 && profile.requiredPackages.every(name => PACKAGE.test(name)),
    'PROFILE_PACKAGES_INVALID', 'required package probes are invalid');
  for (const pathname of [profile.keyPath, profile.inReleasePath, profile.packagesPath]) normalizeUrl(profile, pathname);
  return profile;
}

export function getVendorRepositoryEvidenceProfile(profileId) {
  const profile = PROFILES[String(profileId || '')];
  if (!profile) fail('PROFILE_NOT_FOUND', `unknown vendor repository evidence profile: ${profileId || '<empty>'}`);
  return validateProfile(profile);
}

async function fetchBounded(url, maxBytes, fetchImpl) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 20_000);
  try {
    const response = await fetchImpl(url, {
      redirect: 'manual',
      signal: controller.signal,
      headers: { 'user-agent': 'SWIR-OS-vendor-repository-evidence/0.1' }
    });
    assert(response && response.status === 200, 'FETCH_STATUS_INVALID', `pinned vendor resource returned HTTP ${response?.status ?? 'unknown'}`);
    assert(!response.headers?.get?.('location'), 'FETCH_REDIRECT_FORBIDDEN', 'vendor evidence fetch must not follow redirects');
    const declared = Number(response.headers?.get?.('content-length') || 0);
    if (Number.isFinite(declared) && declared > 0) assert(declared <= maxBytes, 'FETCH_TOO_LARGE', 'pinned vendor resource exceeds its verified size bound');
    const bytes = Buffer.from(await response.arrayBuffer());
    assert(bytes.length > 0 && bytes.length <= maxBytes, 'FETCH_TOO_LARGE', 'pinned vendor resource is empty or exceeds its verified size bound');
    return bytes;
  } catch (error) {
    if (error?.name === 'VendorRepositoryEvidenceError') throw error;
    fail('FETCH_FAILED', `failed to fetch pinned vendor resource: ${error?.message || 'network error'}`);
  } finally {
    clearTimeout(timer);
  }
}

export function parseGpgPrimaryFingerprint(colonText) {
  const lines = String(colonText || '').split(/\r?\n/);
  let awaitingPrimaryFingerprint = false;
  for (const line of lines) {
    if (line.startsWith('pub:')) {
      awaitingPrimaryFingerprint = true;
      continue;
    }
    if (awaitingPrimaryFingerprint && line.startsWith('fpr:')) {
      const fingerprint = line.split(':')[9]?.toUpperCase();
      return HEX40.test(fingerprint || '') ? fingerprint : null;
    }
    if (awaitingPrimaryFingerprint && (line.startsWith('sub:') || line.startsWith('uid:'))) awaitingPrimaryFingerprint = false;
  }
  return null;
}

export function parseValidSignatures(statusText) {
  return String(statusText || '').split(/\r?\n/).map(line => {
    if (!line.startsWith('[GNUPG:] VALIDSIG ')) return null;
    const fields = line.slice('[GNUPG:] VALIDSIG '.length).trim().split(/\s+/);
    const signerFingerprint = fields[0]?.toUpperCase();
    const primaryFingerprint = fields[9]?.toUpperCase() || signerFingerprint;
    if (!HEX40.test(signerFingerprint || '') || !HEX40.test(primaryFingerprint || '')) return null;
    return { signerFingerprint, primaryFingerprint };
  }).filter(Boolean);
}

export function parsePackagesIndex(text) {
  const packages = new Set();
  for (const line of String(text || '').split(/\r?\n/)) {
    const match = line.match(/^Package:\s*([a-z0-9][a-z0-9+.-]{0,127})\s*$/);
    if (match) packages.add(match[1]);
  }
  return packages;
}

function parseSingleReleaseField(text, field, { required = false } = {}) {
  const matches = [...String(text || '').matchAll(new RegExp(`^${field}:\\s*(.+?)\\s*$`, 'gmi'))];
  assert(matches.length <= 1, 'INRELEASE_FIELD_DUPLICATE', `InRelease contains duplicate ${field} fields`);
  if (matches.length === 0) {
    if (required) fail(`INRELEASE_${field.toUpperCase().replace('-', '_')}_MISSING`, `InRelease is missing required ${field} field`);
    return null;
  }
  return matches[0][1];
}

export function verifyInReleaseFreshness(inReleaseBytes, options = {}) {
  const now = normalizeNow(options.now ?? new Date());
  const text = Buffer.isBuffer(inReleaseBytes) ? inReleaseBytes.toString('utf8') : String(inReleaseBytes || '');
  const dateText = parseSingleReleaseField(text, 'Date', { required: true });
  const validUntilText = parseSingleReleaseField(text, 'Valid-Until');

  const signedAtMs = Date.parse(dateText);
  assert(Number.isFinite(signedAtMs), 'INRELEASE_DATE_INVALID', 'InRelease Date field is invalid');
  const signedAt = new Date(signedAtMs);
  assert(signedAtMs <= now.getTime() + MAX_FUTURE_SKEW_MS, 'INRELEASE_DATE_IN_FUTURE', 'InRelease Date is too far in the future');
  assert(now.getTime() - signedAtMs <= MAX_INRELEASE_AGE_MS, 'INRELEASE_TOO_OLD', 'InRelease signed metadata exceeds the maximum verified age');

  let validUntil = null;
  let effectiveValidUntilMs = signedAtMs + MAX_INRELEASE_AGE_MS;
  let expirySource = 'max-age-fallback';
  if (validUntilText !== null) {
    const validUntilMs = Date.parse(validUntilText);
    assert(Number.isFinite(validUntilMs), 'INRELEASE_VALID_UNTIL_INVALID', 'InRelease Valid-Until field is invalid');
    assert(validUntilMs > signedAtMs, 'INRELEASE_VALIDITY_WINDOW_INVALID', 'InRelease Valid-Until must be later than Date');
    assert(now.getTime() <= validUntilMs, 'INRELEASE_EXPIRED', 'InRelease metadata is expired');
    validUntil = new Date(validUntilMs);
    effectiveValidUntilMs = Math.min(effectiveValidUntilMs, validUntilMs);
    expirySource = validUntilMs <= signedAtMs + MAX_INRELEASE_AGE_MS ? 'valid-until' : 'max-age-cap';
  }

  assert(now.getTime() <= effectiveValidUntilMs, 'INRELEASE_EXPIRED', 'InRelease metadata is outside the accepted freshness window');

  return Object.freeze({
    freshnessVerified: true,
    signedAt: signedAt.toISOString(),
    validUntil: validUntil ? validUntil.toISOString() : null,
    effectiveValidUntil: new Date(effectiveValidUntilMs).toISOString(),
    checkedAt: now.toISOString(),
    ageSeconds: Math.max(0, Math.floor((now.getTime() - signedAtMs) / 1000)),
    remainingSeconds: Math.max(0, Math.floor((effectiveValidUntilMs - now.getTime()) / 1000)),
    expirySource,
    maxAgeSeconds: Math.floor(MAX_INRELEASE_AGE_MS / 1000),
    maxFutureSkewSeconds: Math.floor(MAX_FUTURE_SKEW_MS / 1000)
  });
}

function runTool(command, args, options = {}) {
  const result = spawnSync(command, args, { encoding: 'utf8', maxBuffer: 4 * 1024 * 1024, ...options });
  if (result.error) fail('GPG_TOOL_FAILED', `${command} failed to start: ${result.error.message}`);
  if (result.status !== 0) fail('GPG_TOOL_FAILED', `${command} failed with status ${result.status}: ${(result.stderr || '').trim().slice(0, 800)}`);
  return result;
}

export function verifyVendorRepositoryCrypto({ profile, keyBytes, inReleaseBytes, toolRunner = runTool }) {
  validateProfile(profile);
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-vendor-evidence-'));
  try {
    const keyFile = path.join(root, 'vendor-key.asc');
    const keyringFile = path.join(root, 'vendor-keyring.gpg');
    const inReleaseFile = path.join(root, 'InRelease');
    fs.writeFileSync(keyFile, keyBytes, { mode: 0o600 });
    fs.writeFileSync(inReleaseFile, inReleaseBytes, { mode: 0o600 });

    const show = toolRunner('gpg', ['--batch', '--with-colons', '--show-keys', keyFile], { cwd: root });
    const fingerprint = parseGpgPrimaryFingerprint(show.stdout);
    assert(fingerprint && HEX40.test(fingerprint), 'KEY_FINGERPRINT_MISSING', 'vendor key file must contain one parseable primary fingerprint');
    assert(fingerprint === profile.expectedFingerprint, 'KEY_FINGERPRINT_MISMATCH', 'vendor primary signing-key fingerprint does not match the pinned full fingerprint');

    toolRunner('gpg', ['--batch', '--yes', '--dearmor', '--output', keyringFile, keyFile], { cwd: root });
    const verified = toolRunner('gpgv', ['--status-fd=1', '--keyring', keyringFile, inReleaseFile], { cwd: root });
    const validSignatures = parseValidSignatures(verified.stdout);
    assert(validSignatures.length === 1 && validSignatures[0].primaryFingerprint === fingerprint,
      'INRELEASE_SIGNATURE_MISMATCH', 'InRelease signature is not bound to the fetched vendor primary key fingerprint');
    return {
      fingerprint,
      validSignatureFingerprint: validSignatures[0].signerFingerprint,
      validSignaturePrimaryFingerprint: validSignatures[0].primaryFingerprint
    };
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

export async function collectVendorRepositoryEvidence(profileId, options = {}) {
  const profile = getVendorRepositoryEvidenceProfile(profileId);
  const fetchImpl = options.fetchImpl || globalThis.fetch;
  assert(typeof fetchImpl === 'function', 'FETCH_UNAVAILABLE', 'Fetch API is unavailable');
  const keyUrl = normalizeUrl(profile, profile.keyPath);
  const inReleaseUrl = normalizeUrl(profile, profile.inReleasePath);
  const packagesUrl = normalizeUrl(profile, profile.packagesPath);

  const [keyBytes, inReleaseBytes, packagesGz] = await Promise.all([
    fetchBounded(keyUrl, MAX_KEY_BYTES, fetchImpl),
    fetchBounded(inReleaseUrl, MAX_INRELEASE_BYTES, fetchImpl),
    fetchBounded(packagesUrl, MAX_PACKAGES_GZ_BYTES, fetchImpl)
  ]);

  const freshnessEvidence = verifyInReleaseFreshness(inReleaseBytes, { now: options.now ?? new Date() });
  const cryptoEvidence = verifyVendorRepositoryCrypto({
    profile, keyBytes, inReleaseBytes, toolRunner: options.toolRunner || runTool
  });

  let packagesBytes;
  try { packagesBytes = zlib.gunzipSync(packagesGz, { maxOutputLength: MAX_PACKAGES_BYTES }); }
  catch (error) { fail('PACKAGES_GZIP_INVALID', `failed to decode vendor Packages.gz: ${error.message}`); }
  const packages = parsePackagesIndex(packagesBytes.toString('utf8'));
  const missingPackages = profile.requiredPackages.filter(name => !packages.has(name));
  assert(missingPackages.length === 0, 'REQUIRED_PACKAGE_MISSING', `official repository is missing required package probes: ${missingPackages.join(', ')}`);

  return Object.freeze({
    schema: EVIDENCE_SCHEMA,
    qualificationOnly: true,
    authorizesMutation: false,
    authorizesRepositoryEnablement: false,
    profileId: profile.id,
    repositoryId: profile.repositoryId,
    vendor: profile.vendor,
    hardwareVendor: profile.hardwareVendor,
    distribution: profile.distribution,
    source: Object.freeze({
      origin: profile.origin,
      basePath: profile.basePath,
      keyUrl,
      inReleaseUrl,
      packagesUrl
    }),
    key: Object.freeze({
      fingerprint: cryptoEvidence.fingerprint,
      expectedKeyId: profile.expectedKeyId,
      expectedFingerprint: profile.expectedFingerprint,
      sha256: sha256(keyBytes)
    }),
    inRelease: Object.freeze({
      validSignatureFingerprint: cryptoEvidence.validSignatureFingerprint,
      validSignaturePrimaryFingerprint: cryptoEvidence.validSignaturePrimaryFingerprint,
      freshnessVerified: freshnessEvidence.freshnessVerified,
      signedAt: freshnessEvidence.signedAt,
      validUntil: freshnessEvidence.validUntil,
      effectiveValidUntil: freshnessEvidence.effectiveValidUntil,
      checkedAt: freshnessEvidence.checkedAt,
      ageSeconds: freshnessEvidence.ageSeconds,
      remainingSeconds: freshnessEvidence.remainingSeconds,
      expirySource: freshnessEvidence.expirySource,
      maxAgeSeconds: freshnessEvidence.maxAgeSeconds,
      maxFutureSkewSeconds: freshnessEvidence.maxFutureSkewSeconds,
      sha256: sha256(inReleaseBytes)
    }),
    packages: Object.freeze({
      required: [...profile.requiredPackages],
      verified: [...profile.requiredPackages],
      indexSha256: sha256(packagesGz),
      compressedBytes: packagesGz.length,
      uncompressedBytes: packagesBytes.length
    })
  });
}

export const VendorRepositoryEvidencePolicy = Object.freeze({
  schema: EVIDENCE_SCHEMA,
  qualificationOnly: true,
  authorizesMutation: false,
  authorizesRepositoryEnablement: false,
  redirectPolicy: 'forbidden',
  arbitraryUrls: false,
  arbitraryPackages: false,
  fullFingerprintPinning: true,
  signedMetadataFreshnessRequired: true,
  maxInReleaseAgeSeconds: Math.floor(MAX_INRELEASE_AGE_MS / 1000),
  maxFutureSkewSeconds: Math.floor(MAX_FUTURE_SKEW_MS / 1000),
  pinnedProfiles: Object.keys(PROFILES)
});

async function main() {
  const [, , command, profileId] = process.argv;
  if (command !== '--probe' || !profileId) fail('CLI_USAGE', 'usage: vendor-repository-trust-evidence.mjs --probe <profile-id>');
  const evidence = await collectVendorRepositoryEvidence(profileId);
  process.stdout.write(`${JSON.stringify(evidence, null, 2)}\n`);
}

if (process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1])) {
  main().catch(error => {
    process.stderr.write(`${error.name || 'Error'}:${error.code || 'UNKNOWN'}:${error.message}\n`);
    process.exitCode = 64;
  });
}
