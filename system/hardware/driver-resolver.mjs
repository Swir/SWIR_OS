import { assertVendorRepositoryTransactionBinding } from './vendor-repository-transaction-binding.mjs';

const TRUSTED_SOURCE_CLASSES = new Set([
  'kernel-in-tree',
  'linux-firmware',
  'distribution-repository',
  'fwupd-lvfs',
  'vendor-official-repository'
]);
const VENDOR_SOURCE_CLASS = 'vendor-official-repository';
const VENDOR_BINDING_SCHEMA = 'swir.vendor-repository-transaction-binding/0.1';
const HEX64 = /^[a-f0-9]{64}$/;

function uniqueStrings(values) {
  return [...new Set((values || []).filter(value => typeof value === 'string' && value.trim()).map(value => value.trim()))].sort();
}

function normalizeArchitecture(value) {
  const raw = String(value || '').trim().toLowerCase();
  if (raw === 'x64' || raw === 'amd64') return 'x86_64';
  if (raw === 'arm64') return 'aarch64';
  return raw;
}

function verifiedVendorBinding(source, device, snapshot, support, bindings, now) {
  const repositoryId = String(source?.repositoryId || '').trim();
  const vendorId = String(device?.ids?.vendor || '').trim().toLowerCase();
  const distro = snapshot?.host?.distribution || {};
  const architecture = normalizeArchitecture(snapshot?.host?.arch);
  const packageCandidates = new Set(support?.packages || []);
  if (!repositoryId || !/^[a-f0-9]{4}$/.test(vendorId) || !distro.id || !distro.versionId || !architecture || packageCandidates.size === 0) {
    return null;
  }

  for (const candidate of bindings || []) {
    try {
      assertVendorRepositoryTransactionBinding(candidate);
    } catch {
      continue;
    }
    const bound = candidate?.bound;
    if (bound?.repository?.id !== repositoryId || bound?.repository?.sourceClass !== VENDOR_SOURCE_CLASS) continue;
    if (String(bound?.platform?.hardwareVendor || '').toLowerCase() !== vendorId) continue;
    if (String(bound?.platform?.id || '').toLowerCase() !== String(distro.id).toLowerCase()) continue;
    if (String(bound?.platform?.versionId || '') !== String(distro.versionId)) continue;
    if (normalizeArchitecture(bound?.platform?.architecture) !== architecture) continue;
    if (!Array.isArray(bound?.packages) || !bound.packages.some(name => packageCandidates.has(name))) continue;
    if (candidate?.transactionRoute?.repositoryActivationImplementedHere !== false) continue;

    const validUntil = Date.parse(bound?.metadata?.effectiveValidUntil);
    if (!Number.isFinite(validUntil) || validUntil < now.getTime()) continue;
    return candidate;
  }
  return null;
}

function trustedSources(device, snapshot, support, vendorRepositoryBindings, now) {
  const trusted = [];
  for (const source of device?.catalog?.recommendedSources || []) {
    if (!source || !TRUSTED_SOURCE_CLASSES.has(source.class) || typeof source.ref !== 'string' || !source.ref.trim()) continue;
    if (source.class !== VENDOR_SOURCE_CLASS) {
      trusted.push(source);
      continue;
    }

    const binding = verifiedVendorBinding(source, device, snapshot, support, vendorRepositoryBindings, now);
    if (!binding) continue;
    trusted.push(Object.freeze({
      ...source,
      repositoryId: binding.bound.repository.id,
      verification: Object.freeze({
        schema: VENDOR_BINDING_SCHEMA,
        bindingDigest: binding.bindingDigest,
        evidenceValidUntil: binding.bound.metadata.effectiveValidUntil,
        packages: Object.freeze([...binding.bound.packages])
      })
    }));
  }
  return trusted;
}

function aggregateSupport(device, catalog) {
  const ids = new Set(device?.catalog?.entryIds || []);
  const entries = (catalog?.entries || []).filter(entry => ids.has(entry.id));
  return {
    modules: uniqueStrings(entries.flatMap(entry => entry.support?.kernelModules || [])),
    firmware: uniqueStrings(entries.flatMap(entry => entry.support?.firmware || [])),
    packages: uniqueStrings(entries.flatMap(entry => entry.support?.packages || []))
  };
}

function rollbackMode(sources) {
  if (!sources.length) return 'required-before-apply';
  if (sources.some(source => source.rollback === true)) return 'source-supported';
  return 'required-before-apply';
}

function operationId(deviceKey, kind, index) {
  return `${deviceKey}:${kind}:${index}`.replace(/[^A-Za-z0-9._:-]/g, '_');
}

function hostFacts(snapshot) {
  const distro = snapshot?.host?.distribution || {};
  const capabilities = snapshot?.host?.capabilities || {};
  return {
    distribution: {
      id: distro.id || 'unknown',
      versionId: distro.versionId ?? null,
      family: distro.family || 'unknown'
    },
    fwupdAvailable: capabilities.fwupd?.available === true,
    lvfsMetadataPresent: capabilities.fwupd?.lvfsMetadataPresent === true,
    packageManagers: uniqueStrings(capabilities.packageManagers || []),
    repositoryManagers: uniqueStrings((capabilities.repositoryConfig || []).map(item => item?.manager))
  };
}

export function resolveDriverPlan(snapshot, catalog, { now = new Date(), vendorRepositoryBindings = [] } = {}) {
  if (snapshot?.schema !== 'swir.hardware-snapshot/0.2' || snapshot?.host?.readOnly !== true) {
    throw new Error('Driver resolver requires a trusted read-only hardware snapshot');
  }
  const current = now instanceof Date ? new Date(now.getTime()) : new Date(now);
  if (!Number.isFinite(current.getTime())) throw new Error('Driver resolver requires a valid current time');
  if (!Array.isArray(vendorRepositoryBindings)) throw new Error('Vendor repository bindings must be an array');

  const facts = hostFacts(snapshot);
  const operations = [];
  let healthy = 0;
  let attention = 0;
  let matched = 0;

  for (const device of snapshot.devices || []) {
    const isMatched = device?.catalog?.matched === true;
    if (isMatched) matched += 1;
    const support = aggregateSupport(device, catalog);
    const sources = trustedSources(device, snapshot, support, vendorRepositoryBindings, current);
    const moduleLoaded = device?.driver?.status === 'loaded' && typeof device?.driver?.module === 'string';
    const expectedModuleLoaded = moduleLoaded && (support.modules.length === 0 || support.modules.includes(device.driver.module));

    if (expectedModuleLoaded) {
      healthy += 1;
    } else if (isMatched) {
      attention += 1;
    }

    let index = 0;
    const push = (kind, reason, extra = {}) => {
      const requiresPrivilege = kind !== 'diagnose-unbound';
      operations.push({
        id: operationId(device.key, kind, ++index),
        deviceKey: device.key,
        kind,
        state: 'proposed',
        requiresPrivilege,
        reason,
        sources,
        rollback: requiresPrivilege ? rollbackMode(sources) : 'not-required',
        ...extra
      });
    };

    if (device?.driver?.status === 'unbound' && isMatched) {
      push('diagnose-unbound', 'Device exposes a modalias but no driver is currently bound.', {
        modalias: device.driver.modalias || null,
        moduleCandidates: support.modules
      });
    }

    if (support.modules.length && !expectedModuleLoaded) {
      push('review-module', 'Catalog contains Linux kernel module candidates that require review before any privileged change.', {
        modalias: device?.driver?.modalias || null,
        moduleCandidates: support.modules
      });
    }

    if (support.firmware.length) {
      push('review-firmware', 'Catalog contains firmware requirements; verify package/source state before installation.', {
        firmwareCandidates: support.firmware
      });
    }

    if (support.packages.length) {
      const managerHint = facts.packageManagers[0] || null;
      push('review-package', managerHint
        ? `Catalog contains distribution package candidates; resolve through trusted ${managerHint} repositories only.`
        : 'Catalog contains distribution package candidates, but no supported package manager was detected.', {
        packageManager: managerHint,
        packageCandidates: support.packages
      });
    }

    if (sources.some(source => source.class === 'fwupd-lvfs')) {
      push('review-fwupd', facts.fwupdAvailable
        ? 'fwupd is available; query signed LVFS metadata before proposing any firmware mutation.'
        : 'Catalog recommends fwupd/LVFS, but fwupd is not currently available on this host.', {
        capability: facts.fwupdAvailable ? 'available' : 'unavailable'
      });
    }
  }

  return {
    schema: 'swir.driver-plan/0.1',
    generatedAt: current.toISOString(),
    mode: 'preview',
    readOnly: true,
    autoExecutable: false,
    host: facts,
    summary: {
      devices: (snapshot.devices || []).length,
      matched,
      healthy,
      attention,
      operations: operations.length
    },
    operations
  };
}

export function assertSafeDriverPlan(plan) {
  if (plan?.schema !== 'swir.driver-plan/0.1') throw new Error('Driver plan schema mismatch');
  if (plan?.mode !== 'preview' || plan?.readOnly !== true || plan?.autoExecutable !== false) {
    throw new Error('Driver plan must remain preview-only and non-executable');
  }
  for (const operation of plan.operations || []) {
    for (const source of operation.sources || []) {
      if (!TRUSTED_SOURCE_CLASSES.has(source.class)) {
        throw new Error(`Untrusted driver source class: ${source.class}`);
      }
      if (source.class === VENDOR_SOURCE_CLASS) {
        if (!String(source.repositoryId || '').trim()) throw new Error('Vendor driver source requires repositoryId');
        if (source?.verification?.schema !== VENDOR_BINDING_SCHEMA || !HEX64.test(String(source?.verification?.bindingDigest || ''))) {
          throw new Error('Vendor driver source requires a verified transaction binding');
        }
        const expiry = Date.parse(source?.verification?.evidenceValidUntil);
        if (!Number.isFinite(expiry)) throw new Error('Vendor driver source requires bounded evidence expiry');
        if (!Array.isArray(source?.verification?.packages) || source.verification.packages.length === 0) {
          throw new Error('Vendor driver source requires verified package scope');
        }
      }
    }
    if (operation.requiresPrivilege && operation.rollback === 'not-required') {
      throw new Error(`Privileged operation ${operation.id} must declare rollback handling`);
    }
  }
  return true;
}
