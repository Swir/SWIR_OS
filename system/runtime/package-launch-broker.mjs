import crypto from 'node:crypto';
import { EventEmitter } from 'node:events';
import { SystemApplicationRuntime } from './application-runtime.mjs';

const VERIFICATION_SCHEMA = 'swir.package-verification/0.1';
const RECEIPT_SCHEMA = 'swir.package-launch-receipt/0.1';
const TRUSTED_SOURCE_CLASSES = new Set([
  'swir-signed',
  'distribution-repository',
  'flatpak-remote',
  'vendor-official-repository',
  'local-user-selected'
]);
const LINUX_PROVIDERS = new Set(['swir.package.system', 'swir.package.flatpak', 'swir.package.appimage']);
const WINDOWS_PROVIDERS = new Set(['swir.compat.wine', 'swir.compat.proton']);

function assertObject(value, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${name} must be an object`);
}

function canonicalize(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(',')}]`;
  if (value && typeof value === 'object') {
    const keys = Object.keys(value).sort();
    return `{${keys.map(key => `${JSON.stringify(key)}:${canonicalize(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function normalizeSha256(value, field) {
  const digest = String(value || '').trim().toLowerCase();
  if (!/^[a-f0-9]{64}$/.test(digest)) throw new Error(`${field} must be a 64-character SHA-256 digest`);
  return digest;
}

function fixedTimeDigestEqual(left, right) {
  const a = Buffer.from(normalizeSha256(left, 'manifestSha256'), 'hex');
  const b = Buffer.from(normalizeSha256(right, 'computed manifest digest'), 'hex');
  return crypto.timingSafeEqual(a, b);
}

export function computeManifestSha256(manifest) {
  assertObject(manifest, 'package manifest');
  return crypto.createHash('sha256').update(canonicalize(manifest), 'utf8').digest('hex');
}

export function verifyPackageLaunchAuthorization(manifest, verification) {
  assertObject(manifest, 'package manifest');
  assertObject(verification, 'package verification');
  if (manifest.schema !== 'swir.package-provider/0.2') throw new Error('unsupported package provider schema');
  if (!Array.isArray(manifest.targetEditions) || !manifest.targetEditions.includes('system')) throw new Error('package does not target System Edition');
  if (!['linux-native', 'windows-compat'].includes(manifest.executionClass)) throw new Error('unsupported System Edition execution class');
  if (verification.schema !== VERIFICATION_SCHEMA) throw new Error('unsupported package verification schema');
  if (verification.packageId !== manifest.id) throw new Error('verification packageId does not match manifest');
  if (verification.provider !== manifest.provider) throw new Error('verification provider does not match manifest');
  if (verification.executionClass !== manifest.executionClass) throw new Error('verification executionClass does not match manifest');
  if (!TRUSTED_SOURCE_CLASSES.has(verification.sourceClass)) throw new Error('verification sourceClass is not trusted by policy');
  if (verification.sourceClass !== manifest.trust?.sourceClass) throw new Error('verification sourceClass does not match manifest trust policy');
  if (manifest.trust?.signatureRequired !== true) throw new Error('System Edition package must require signature verification');
  if (verification.trustVerified !== true) throw new Error('package trust is not verified');
  if (verification.signatureVerified !== true) throw new Error('package signature is not verified');
  if (verification.artifactVerified !== true) throw new Error('package artifact is not verified');
  if (typeof verification.transactionId !== 'string' || !/^[a-z0-9][a-z0-9._:-]{2,127}$/i.test(verification.transactionId)) throw new Error('verification transactionId is invalid');
  const verifiedAtMs = Date.parse(verification.verifiedAt);
  if (!Number.isFinite(verifiedAtMs)) throw new Error('verification verifiedAt is invalid');

  if (manifest.executionClass === 'linux-native' && !LINUX_PROVIDERS.has(manifest.provider)) throw new Error('linux-native package uses an unsupported provider');
  if (manifest.executionClass === 'windows-compat' && !WINDOWS_PROVIDERS.has(manifest.provider)) throw new Error('windows-compat package uses an unsupported provider');
  if (manifest.trust?.repositoryId && verification.repositoryId !== manifest.trust.repositoryId) throw new Error('verification repositoryId does not match manifest trust policy');

  const computed = computeManifestSha256(manifest);
  if (!fixedTimeDigestEqual(verification.manifestSha256, computed)) throw new Error('verified manifest digest does not match package manifest');

  return Object.freeze({
    schema: VERIFICATION_SCHEMA,
    packageId: manifest.id,
    manifestSha256: computed,
    provider: manifest.provider,
    executionClass: manifest.executionClass,
    sourceClass: verification.sourceClass,
    repositoryId: verification.repositoryId || null,
    transactionId: verification.transactionId,
    verifiedAt: new Date(verifiedAtMs).toISOString(),
    trustVerified: true,
    signatureVerified: true,
    artifactVerified: true
  });
}

export class SystemPackageLaunchBroker extends EventEmitter {
  #runtime;

  constructor({ runtime = new SystemApplicationRuntime() } = {}) {
    super();
    this.#runtime = runtime;
    for (const event of ['started', 'exited', 'processError']) {
      this.#runtime.on(event, record => this.emit(event, record));
    }
  }

  launch(manifest, verification, options = {}) {
    const authorization = verifyPackageLaunchAuthorization(manifest, verification);
    const record = this.#runtime.launch(manifest, { ...options, trustVerified: true });
    return {
      schema: RECEIPT_SCHEMA,
      authorization,
      executionClass: manifest.executionClass,
      provider: manifest.provider,
      ...record
    };
  }

  get(appId) { return this.#runtime.get(appId); }
  list(options) { return this.#runtime.list(options); }
  stop(appId, options) { return this.#runtime.stop(appId, options); }
  forget(appId) { return this.#runtime.forget(appId); }
}

export const SystemPackageLaunchPolicy = Object.freeze({
  schema: 'swir.system-package-launch/0.1',
  verificationSchema: VERIFICATION_SCHEMA,
  receiptSchema: RECEIPT_SCHEMA,
  targetEdition: 'system',
  executionClasses: ['linux-native', 'windows-compat'],
  linuxProviders: [...LINUX_PROVIDERS],
  windowsProviders: [...WINDOWS_PROVIDERS],
  trustedSourceClasses: [...TRUSTED_SOURCE_CLASSES],
  manifestDigest: 'SHA-256',
  trustVerifiedRequired: true,
  signatureVerifiedRequired: true,
  artifactVerifiedRequired: true,
  windowsKernelDriversAsLinuxDrivers: false
});
