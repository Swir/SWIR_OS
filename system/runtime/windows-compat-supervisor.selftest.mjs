import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { once } from 'node:events';
import { WindowsCompatibilitySupervisor, WindowsCompatibilitySupervisorPolicy } from './windows-compat-supervisor.mjs';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-wincompat-'));
const prefixRoot = path.join(root, 'prefixes');
const appRoot = path.join(root, 'apps');
fs.mkdirSync(appRoot, { recursive: true });
const entryPoint = path.join(appRoot, 'test.exe');
fs.writeFileSync(entryPoint, 'test');

const manifest = {
  schema: 'swir.package-provider/0.2',
  id: 'com.swir.compat-selftest',
  targetEditions: ['system'],
  executionClass: 'windows-compat',
  provider: 'swir.compat.wine',
  package: { nativeEntryPoint: entryPoint },
  compatibility: { prefixPolicy: 'per-app', windowsArchitecture: 'win64' },
  trust: { sourceClass: 'swir-signed', signatureRequired: true }
};

const supervisor = new WindowsCompatibilitySupervisor();
const runtime = '/usr/bin/true';
const record = supervisor.launch(manifest, {
  trustVerified: true,
  prefixRoot,
  runtimePaths: { 'swir.compat.wine': runtime },
  stdio: 'ignore'
});
assert.equal(record.appId, manifest.id);
assert.equal(record.provider, 'swir.compat.wine');
assert.equal(record.state, 'running');
assert.equal(record.prefix, path.join(prefixRoot, manifest.id));
assert.equal(fs.statSync(record.prefix).isDirectory(), true);
assert.throws(() => supervisor.launch(manifest, { trustVerified: true, prefixRoot, runtimePaths: { 'swir.compat.wine': runtime } }), /already running/i);
await once(supervisor, 'exited');
const exited = supervisor.get(manifest.id);
assert.equal(exited.state, 'exited');
assert.equal(exited.exitCode, 0);
assert.equal(supervisor.forget(manifest.id), true);
assert.equal(supervisor.get(manifest.id), null);
assert.equal(WindowsCompatibilitySupervisorPolicy.perAppPrefixRequired, true);
assert.equal(WindowsCompatibilitySupervisorPolicy.shellExecution, false);

assert.throws(() => supervisor.launch({ ...manifest, trust: { ...manifest.trust, signatureRequired: false } }, { trustVerified: true, prefixRoot, runtimePaths: { 'swir.compat.wine': runtime } }), /trust must be verified/i);
assert.throws(() => supervisor.launch({ ...manifest, id: 'com.swir.bad-runtime' }, { trustVerified: true, prefixRoot, runtimePaths: { 'swir.compat.wine': path.join(root, 'missing-wine') } }), /ENOENT|unavailable/i);

fs.rmSync(root, { recursive: true, force: true });
console.log('Windows compatibility supervisor self-tests passed');
