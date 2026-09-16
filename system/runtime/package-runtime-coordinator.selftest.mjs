import assert from 'node:assert/strict';
import fs from 'node:fs';
import { EventEmitter, once } from 'node:events';
import { computeManifestSha256 } from './package-launch-broker.mjs';
import {
  SystemPackageRuntimeCoordinator,
  SystemPackageRuntimeCoordinatorPolicy
} from './package-runtime-coordinator.mjs';

const executable = fs.existsSync('/usr/bin/true') ? '/usr/bin/true' : '/bin/true';
const manifest = {
  schema: 'swir.package-provider/0.2',
  id: 'swir.selftest.runtime-coordinator',
  targetEditions: ['system'],
  executionClass: 'linux-native',
  provider: 'swir.package.system',
  package: { name: 'Coordinator Self Test', nativeEntryPoint: executable },
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
  transactionId: 'txn:coordinator:001',
  verifiedAt: new Date().toISOString(),
  trustVerified: true,
  signatureVerified: true,
  artifactVerified: true
};

assert.equal(SystemPackageRuntimeCoordinatorPolicy.providerMustBeReady, true);
assert.equal(SystemPackageRuntimeCoordinatorPolicy.providerPlanAutoExecutable, false);
assert.equal(SystemPackageRuntimeCoordinatorPolicy.windowsKernelDriversAsLinuxDrivers, false);

class StubBroker extends EventEmitter {
  constructor() { super(); this.launches = 0; }
  launch(pkg) {
    this.launches += 1;
    return { schema: 'swir.package-launch-receipt/0.1', appId: pkg.id, provider: pkg.provider, executionClass: pkg.executionClass, state: 'running' };
  }
  get() { return null; }
  list() { return []; }
  stop() { return false; }
  forget() { return false; }
}

const stub = new StubBroker();
const coordinator = new SystemPackageRuntimeCoordinator({ broker: stub });
const ready = coordinator.plan(manifest, { host: { capabilities: { packageManagers: ['apt'] } } });
assert.equal(ready.status, 'ready');
const receipt = coordinator.launch(manifest, verification, { host: { capabilities: { packageManagers: ['apt'] } } });
assert.equal(receipt.schema, 'swir.system-package-runtime-coordinator/0.1');
assert.equal(receipt.providerPlan.status, 'ready');
assert.equal(stub.launches, 1);

assert.throws(
  () => coordinator.launch(manifest, verification, { host: { capabilities: { packageManagers: [] } } }),
  /provider capability unavailable/
);
assert.equal(stub.launches, 1, 'unavailable provider must fail before broker launch');

const unsafe = new SystemPackageRuntimeCoordinator({
  broker: stub,
  providerResolver: () => ({
    schema: 'swir.package-provider-plan/0.1',
    mode: 'preview',
    readOnly: true,
    autoExecutable: true,
    packageId: manifest.id,
    provider: manifest.provider,
    executionClass: manifest.executionClass,
    sourceClass: manifest.trust.sourceClass,
    requiredCapability: 'system-package-manager',
    capabilityAvailable: true,
    status: 'ready',
    packageManagers: ['apt'],
    privilegedMutation: true,
    privilegedMutationRequiresPlan: true,
    privilegedMutationRequiresJournal: true,
    signatureVerificationRequired: true
  })
});
assert.throws(() => unsafe.launch(manifest, verification), /read-only and non-executable/);

if (fs.existsSync(executable)) {
  const live = new SystemPackageRuntimeCoordinator();
  const exited = once(live, 'exited');
  const liveReceipt = live.launch(manifest, verification, { host: { capabilities: { packageManagers: ['apt'] } }, args: [] });
  assert.equal(liveReceipt.executionClass, 'linux-native');
  const [finished] = await exited;
  assert.equal(finished.state, 'exited');
  assert.equal(finished.exitCode, 0);
  assert.equal(live.forget(manifest.id), true);
}

console.log('SWIR System Package Runtime Coordinator self-tests: OK');
