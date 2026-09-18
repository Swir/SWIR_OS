#!/usr/bin/env node
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import net from 'node:net';

import { PackageTransactionBroker, servePackageBroker } from './swir-package-transaction-broker.mjs';
import { digestPackagePlan } from '../packages/package-transaction-service.mjs';

function fakePlan(operation, manifest) {
  return {
    schema: 'swir.system-package-plan/0.1',
    mode: 'preview',
    readOnly: true,
    autoExecutable: false,
    provider: 'swir.package.system',
    executionClass: 'linux-native',
    operation,
    package: { id: manifest.id, sourceRef: manifest.package.sourceRef, nativeEntryPoint: null },
    host: {
      distribution: { id: 'debian', family: 'debian' },
      packageManager: 'apt',
      availablePackageManagers: ['apt']
    },
    source: { class: 'distribution-repository', repositoryId: null },
    trust: { signatureVerificationRequired: true, arbitraryRepositoryUrlAllowed: false },
    transaction: {
      requiresPrivilege: true,
      journalRequired: true,
      healthCheckRequired: operation !== 'remove',
      rollback: { supported: false, mechanism: null, note: 'selftest' }
    },
    commandPreview: operation === 'install'
      ? ['apt-get', 'install', '--', manifest.package.sourceRef]
      : operation === 'update'
        ? ['apt-get', 'install', '--only-upgrade', '--', manifest.package.sourceRef]
        : ['apt-get', 'remove', '--', manifest.package.sourceRef],
    dependencies: { schema: 'swir.apt-dependency-plan/0.1', changes: [] }
  };
}

const calls = [];
const stack = {
  async planWithDependencies(operation, manifest) {
    calls.push({ type: 'preview', operation, manifest });
    return fakePlan(operation, manifest);
  },
  async execute(operation, manifest, context) {
    calls.push({ type: 'commit', operation, manifest, context });
    const plan = fakePlan(operation, manifest);
    return {
      id: 'txn-selftest-0001',
      state: 'committed',
      planDigest: digestPackagePlan(plan),
      plan
    };
  }
};

const broker = new PackageTransactionBroker({ stack });
const previewResponse = await broker.handle({
  schema: 'swir.package-transaction-broker-request/0.1',
  action: 'preview',
  operation: 'install',
  packageName: 'nano'
});
assert.equal(previewResponse.ok, true);
assert.equal(previewResponse.action, 'preview');
assert.equal(previewResponse.preview.packageId, 'system:nano');
assert.equal(previewResponse.preview.packageName, 'nano');
assert.equal(previewResponse.preview.operation, 'install');
assert.match(previewResponse.preview.planDigest, /^[a-f0-9]{64}$/);
assert.deepEqual(previewResponse.preview.commandPreview, ['apt-get', 'install', '--', 'nano']);
assert.equal(previewResponse.preview.autoExecutable, false);
assert.equal(previewResponse.preview.requiresPrivilege, true);

const envelope = { schema: 'swir.peer-authorization-envelope/0.1', payload: { grantId: 'test' }, mac: '0'.repeat(64) };
const commitResponse = await broker.handle({
  schema: 'swir.package-transaction-broker-request/0.1',
  action: 'commit',
  operation: 'install',
  packageName: 'nano',
  peerAuthorizationEnvelope: envelope
});
assert.equal(commitResponse.ok, true);
assert.equal(commitResponse.transaction.id, 'txn-selftest-0001');
assert.equal(commitResponse.transaction.state, 'committed');
const commitCall = calls.find(item => item.type === 'commit');
assert.deepEqual(commitCall.context.peerAuthorizationEnvelope, envelope);
assert.equal(commitCall.context.allowUserInteraction, true);
assert.equal(commitCall.manifest.trust.repositoryId, null);
assert.equal(commitCall.manifest.trust.signatureRequired, true);

for (const invalid of [
  { schema: 'swir.package-transaction-broker-request/0.1', action: 'preview', operation: 'install', packageName: 'bad;rm' },
  { schema: 'swir.package-transaction-broker-request/0.1', action: 'preview', operation: 'upgrade-all', packageName: 'nano' },
  { schema: 'swir.package-transaction-broker-request/0.1', action: 'preview', operation: 'install', packageName: 'nano', uid: 1000 },
  { schema: 'swir.package-transaction-broker-request/0.1', action: 'commit', operation: 'install', packageName: 'nano' }
]) {
  await assert.rejects(() => broker.handle(invalid));
}

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-package-broker-'));
fs.chmodSync(root, 0o700);
const socketPath = path.join(root, 'broker.sock');
const server = await servePackageBroker({ broker, socketPath, testMode: true, once: true });

const response = await new Promise((resolve, reject) => {
  const socket = net.createConnection({ path: socketPath });
  let buffer = '';
  socket.once('error', reject);
  socket.once('connect', () => socket.write(`${JSON.stringify({
    schema: 'swir.package-transaction-broker-request/0.1',
    action: 'preview',
    operation: 'update',
    packageName: 'bash'
  })}\n`));
  socket.on('data', chunk => { buffer += chunk.toString('utf8'); });
  socket.on('end', () => {
    try { resolve(JSON.parse(buffer.trim())); } catch (error) { reject(error); }
  });
});
assert.equal(response.schema, 'swir.package-transaction-broker-response/0.1');
assert.equal(response.ok, true);
assert.equal(response.preview.packageName, 'bash');
assert.equal(response.preview.operation, 'update');
await new Promise(resolve => server.once('close', resolve));
fs.rmSync(root, { recursive: true, force: true });

console.log('SWIR package transaction broker self-test OK');
