import assert from 'node:assert/strict';
import {
  listSystemPackageProviders,
  normalizeProviderCapabilities,
  resolveSystemPackageProvider,
  SystemPackageProviderPolicy
} from './package-provider-registry.mjs';

function manifest(overrides = {}) {
  return {
    schema: 'swir.package-provider/0.2',
    id: 'swir.selftest.provider',
    targetEditions: ['system'],
    executionClass: 'linux-native',
    provider: 'swir.package.system',
    package: { nativeEntryPoint: '/usr/bin/true' },
    trust: { sourceClass: 'distribution-repository', signatureRequired: true },
    ...overrides
  };
}

assert.equal(SystemPackageProviderPolicy.webProviderAllowed, false);
assert.equal(SystemPackageProviderPolicy.privilegedMutationRequiresJournal, true);
assert.equal(SystemPackageProviderPolicy.windowsKernelDriversAsLinuxDrivers, false);
assert(!SystemPackageProviderPolicy.providerIds.includes('swir.package.web'));
assert.equal(listSystemPackageProviders().length, 5);

const caps = normalizeProviderCapabilities({ capabilities: { packageManagers: ['apt', 'unknown'], tools: { wine: true, flatpak: false } } });
assert.equal(caps['system-package-manager'], true);
assert.deepEqual(caps.packageManagers, ['apt']);
assert.equal(caps.wine, true);
assert.equal(caps.flatpak, false);

const systemPlan = resolveSystemPackageProvider(manifest(), { capabilities: { packageManagers: ['apt'] } });
assert.equal(systemPlan.status, 'ready');
assert.equal(systemPlan.autoExecutable, false);
assert.equal(systemPlan.privilegedMutationRequiresPlan, true);
assert.equal(systemPlan.privilegedMutationRequiresJournal, true);

const flatpakPlan = resolveSystemPackageProvider(manifest({
  provider: 'swir.package.flatpak',
  trust: { sourceClass: 'flatpak-remote', signatureRequired: true }
}), { capabilities: { packageManagers: ['apt'], tools: { flatpak: false } } });
assert.equal(flatpakPlan.status, 'unavailable');
assert.equal(flatpakPlan.requiredCapability, 'flatpak');

const winePlan = resolveSystemPackageProvider(manifest({
  executionClass: 'windows-compat',
  provider: 'swir.compat.wine',
  trust: { sourceClass: 'distribution-repository', signatureRequired: true }
}), { capabilities: { tools: { wine: true } } });
assert.equal(winePlan.status, 'ready');
assert.equal(winePlan.executionClass, 'windows-compat');

assert.throws(() => resolveSystemPackageProvider(manifest({ provider: 'swir.package.web' }), {}), /not available/);
assert.throws(() => resolveSystemPackageProvider(manifest({ executionClass: 'windows-compat' }), {}), /executionClass mismatch/);
assert.throws(() => resolveSystemPackageProvider(manifest({ trust: { sourceClass: 'local-user-selected', signatureRequired: true } }), { capabilities: { packageManagers: ['apt'] } }), /sourceClass/);
assert.throws(() => resolveSystemPackageProvider(manifest({ trust: { sourceClass: 'distribution-repository', signatureRequired: false } }), { capabilities: { packageManagers: ['apt'] } }), /signature verification/);

console.log('SWIR System Package Provider Registry self-tests: OK');
