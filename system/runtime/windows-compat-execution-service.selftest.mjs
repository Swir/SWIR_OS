import assert from 'node:assert/strict';
import { buildWindowsCompatibilityPlan, WindowsCompatibilityPolicy } from './windows-compat-execution-service.mjs';

const base = {
  schema: 'swir.package-provider/0.2',
  id: 'com.swir.test-winapp',
  targetEditions: ['system'],
  executionClass: 'windows-compat',
  provider: 'swir.compat.wine',
  package: { nativeEntryPoint: '/opt/swir/windows/test/app.exe' },
  compatibility: { prefixPolicy: 'per-app', windowsArchitecture: 'win64' },
  trust: { sourceClass: 'swir-signed', signatureRequired: true }
};

const runtime = '/usr/bin/wine';
const plan = buildWindowsCompatibilityPlan(base, {
  trustVerified: true,
  prefixRoot: '/tmp/swir-prefixes',
  runtimePaths: { 'swir.compat.wine': runtime }
});
assert.equal(plan.runtime, runtime);
assert.equal(plan.runtimeAvailable, true);
assert.equal(plan.prefix, '/tmp/swir-prefixes/com.swir.test-winapp');
assert.equal(plan.shell, false);
assert.equal(plan.isolatedPrefix, true);
assert.equal(WindowsCompatibilityPolicy.windowsKernelDriversSupported, false);

assert.throws(() => buildWindowsCompatibilityPlan({ ...base, executionClass: 'linux-native' }, { trustVerified: true }), /windows-compat only/i);
assert.throws(() => buildWindowsCompatibilityPlan(base, {}), /trust must be verified/i);
assert.throws(() => buildWindowsCompatibilityPlan({ ...base, trust: { ...base.trust, signatureRequired: false } }, { trustVerified: true }), /trust must be verified/i);
assert.throws(() => buildWindowsCompatibilityPlan({ ...base, package: { nativeEntryPoint: '/opt/swir/windows/test/app.sh' } }, { trustVerified: true }), /must be \.exe or \.msi/i);
assert.throws(() => buildWindowsCompatibilityPlan({ ...base, compatibility: { ...base.compatibility, prefixPolicy: 'shared-explicit' } }, { trustVerified: true }), /per-app compatibility prefix/i);
assert.throws(() => buildWindowsCompatibilityPlan({ ...base, targetEditions: ['desktop'] }, { trustVerified: true }), /does not target System Edition/i);
assert.throws(() => buildWindowsCompatibilityPlan(base, { trustVerified: true, runtimePaths: { 'swir.compat.wine': 'wine' } }), /runtime path must be absolute/i);

const unavailable = buildWindowsCompatibilityPlan({ ...base, provider: 'swir.compat.proton' }, {
  trustVerified: true,
  prefixRoot: '/tmp/swir-prefixes',
  runtimePaths: {}
});
assert.equal(typeof unavailable.runtimeAvailable, 'boolean');

console.log('Windows compatibility execution self-tests passed');
