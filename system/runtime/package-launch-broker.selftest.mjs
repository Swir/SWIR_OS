import assert from 'node:assert/strict';
import fs from 'node:fs';
import { EventEmitter, once } from 'node:events';
import {
  computeManifestSha256,
  verifyPackageLaunchAuthorization,
  SystemPackageLaunchBroker,
  SystemPackageLaunchPolicy
} from './package-launch-broker.mjs';

const executable = fs.existsSync('/usr/bin/true') ? '/usr/bin/true' : '/bin/true';
const manifest = {
  schema: 'swir.package-provider/0.2',
  id: 'swir.selftest.package-broker',
  targetEditions: ['system'],
  executionClass: 'linux-native',
  provider: 'swir.package.system',
  package: { name: 'Self Test', nativeEntryPoint: executable },
  trust: { sourceClass: 'distribution-repository', repositoryId: 'base-os', signatureRequired: true },
  rollback: true
};

const verification = {
  schema: 'swir.package-verification/0.1',
  packageId: manifest.id,
  manifestSha256: computeManifestSha256(manifest),
  provider: manifest.provider,
  executionClass: manifest.executionClass,
  sourceClass: manifest.trust.sourceClass,
  repositoryId: manifest.trust.repositoryId,
  transactionId: 'txn:selftest:001',
  verifiedAt: new Date().toISOString(),
  trustVerified: true,
  signatureVerified: true,
  artifactVerified: true
};

assert.equal(SystemPackageLaunchPolicy.manifestDigest, 'SHA-256');
assert.equal(SystemPackageLaunchPolicy.windowsKernelDriversAsLinuxDrivers, false);
const authorization = verifyPackageLaunchAuthorization(manifest, verification);
assert.equal(authorization.packageId, manifest.id);
assert.equal(authorization.manifestSha256, verification.manifestSha256);
assert.throws(() => verifyPackageLaunchAuthorization(manifest, { ...verification, manifestSha256: '0'.repeat(64) }), /digest does not match/);
assert.throws(() => verifyPackageLaunchAuthorization(manifest, { ...verification, signatureVerified: false }), /signature is not verified/);
assert.throws(() => verifyPackageLaunchAuthorization(manifest, { ...verification, artifactVerified: false }), /artifact is not verified/);
assert.throws(() => verifyPackageLaunchAuthorization(manifest, { ...verification, repositoryId: 'other' }), /repositoryId/);
assert.throws(() => verifyPackageLaunchAuthorization({ ...manifest, executionClass: 'swir-web', provider: 'swir.package.web' }, verification), /unsupported System Edition execution class/);

class CapturingRuntime extends EventEmitter {
  constructor() { super(); this.options = null; this.records = new Map(); }
  launch(pkg, options) {
    this.options = options;
    const record = { appId: pkg.id, state: 'running', startedAt: new Date().toISOString() };
    this.records.set(pkg.id, record);
    this.emit('started', record);
    return record;
  }
  get(id) { return this.records.get(id) || null; }
  list() { return [...this.records.values()]; }
  stop() { return false; }
  forget(id) { return this.records.delete(id); }
}

const capture = new CapturingRuntime();
const guarded = new SystemPackageLaunchBroker({ runtime: capture });
const receipt = guarded.launch(manifest, verification, { trustVerified: false, args: ['--ignored-by-stub'] });
assert.equal(receipt.schema, 'swir.package-launch-receipt/0.1');
assert.equal(receipt.authorization.transactionId, verification.transactionId);
assert.equal(capture.options.trustVerified, true);
assert.equal(guarded.forget(manifest.id), true);

if (fs.existsSync(executable)) {
  const broker = new SystemPackageLaunchBroker();
  const exited = once(broker, 'exited');
  const liveReceipt = broker.launch(manifest, verification, { args: [] });
  assert.equal(liveReceipt.executionClass, 'linux-native');
  const [finished] = await exited;
  assert.equal(finished.state, 'exited');
  assert.equal(finished.exitCode, 0);
  assert.equal(broker.forget(manifest.id), true);
}

console.log('SWIR System Package Launch Broker self-tests: OK');
