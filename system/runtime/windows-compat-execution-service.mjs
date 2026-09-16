import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

const COMPAT_PROVIDERS = new Map([
  ['swir.compat.wine', ['wine', 'wine64']],
  ['swir.compat.proton', ['proton']]
]);

function assertObject(value, name) {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new Error(`${name} must be an object`);
}

function assertAppId(appId) {
  if (!appId || !/^[a-z0-9][a-z0-9._-]{1,127}$/i.test(appId)) throw new Error('invalid app id');
}

function safePrefixName(appId) {
  assertAppId(appId);
  return appId.toLowerCase().replace(/[^a-z0-9._-]/g, '_');
}

export function resolveCompatibilityRuntime(provider, { runtimePaths = {} } = {}) {
  const candidates = COMPAT_PROVIDERS.get(provider);
  if (!candidates) throw new Error('unsupported Windows compatibility provider');
  const explicit = runtimePaths[provider];
  if (explicit) {
    if (!path.isAbsolute(explicit)) throw new Error('compatibility runtime path must be absolute');
    return explicit;
  }
  for (const name of candidates) {
    for (const root of ['/usr/bin', '/usr/local/bin']) {
      const candidate = path.join(root, name);
      try { if (fs.statSync(candidate).isFile()) return candidate; } catch {}
    }
  }
  return null;
}

export function buildWindowsCompatibilityPlan(manifest, options = {}) {
  assertObject(manifest, 'package manifest');
  if (manifest.schema !== 'swir.package-provider/0.2') throw new Error('unsupported package provider schema');
  if (!Array.isArray(manifest.targetEditions) || !manifest.targetEditions.includes('system')) throw new Error('package does not target System Edition');
  if (manifest.executionClass !== 'windows-compat') throw new Error('Windows compatibility service accepts windows-compat only');
  if (!COMPAT_PROVIDERS.has(manifest.provider)) throw new Error('unsupported Windows compatibility provider');
  assertObject(manifest.package, 'package');
  assertAppId(manifest.id);
  if (typeof manifest.package.nativeEntryPoint !== 'string' || !path.isAbsolute(manifest.package.nativeEntryPoint)) throw new Error('Windows entry point must be an absolute path');
  if (!/\.(exe|msi)$/i.test(manifest.package.nativeEntryPoint)) throw new Error('Windows compatibility entry point must be .exe or .msi');
  if (manifest.trust?.signatureRequired !== true || options.trustVerified !== true) throw new Error('package trust must be verified before compatibility execution');
  assertObject(manifest.compatibility, 'compatibility');
  if (manifest.compatibility.prefixPolicy !== 'per-app') throw new Error('System Edition requires a per-app compatibility prefix');

  const prefixRoot = path.resolve(options.prefixRoot || path.join(os.homedir(), '.local', 'share', 'swir-os', 'compat-prefixes'));
  const prefix = path.join(prefixRoot, safePrefixName(manifest.id));
  if (!prefix.startsWith(prefixRoot + path.sep)) throw new Error('invalid compatibility prefix');
  const runtime = resolveCompatibilityRuntime(manifest.provider, options);

  return Object.freeze({
    schema: 'swir.windows-compat-launch/0.1',
    appId: manifest.id,
    provider: manifest.provider,
    runtime,
    runtimeAvailable: Boolean(runtime),
    prefix,
    prefixPolicy: 'per-app',
    windowsArchitecture: manifest.compatibility.windowsArchitecture || 'win64',
    entryPoint: manifest.package.nativeEntryPoint,
    args: Array.isArray(options.args) ? [...options.args] : [],
    shell: false,
    isolatedPrefix: true,
    trustVerified: true
  });
}

export const WindowsCompatibilityPolicy = Object.freeze({
  schema: 'swir.windows-compat-execution/0.1',
  acceptedManifest: 'swir.package-provider/0.2',
  targetEdition: 'system',
  executionClass: 'windows-compat',
  providers: [...COMPAT_PROVIDERS.keys()],
  prefixPolicy: 'per-app',
  trustVerifiedRequired: true,
  signatureRequired: true,
  shellExecution: false,
  windowsKernelDriversSupported: false
});
