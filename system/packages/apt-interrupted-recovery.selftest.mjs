import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { DistributionPackageProvider } from './distribution-package-provider.mjs';
import { SystemPackageTransactionService } from './package-transaction-service.mjs';
import { AptInterruptedTransactionRecoveryService } from './apt-interrupted-recovery.mjs';

function manifest() {
  return {
    schema: 'swir.package-provider/0.2',
    id: 'swir.test.fixture',
    targetEditions: ['system'],
    executionClass: 'linux-native',
    provider: 'swir.package.system',
    package: { name: 'fixture', sourceRef: 'fixture', nativeEntryPoint: '/usr/bin/fixture' },
    trust: { sourceClass: 'distribution-repository', repositoryId: 'debian-main', signatureRequired: true }
  };
}

const host = {
  distribution: { id: 'debian', family: 'debian', version: '13' },
  capabilities: { packageManagers: ['apt'] }
};
const allowlistedRepositories = ['debian-main'];
const provider = new DistributionPackageProvider({ host, allowlistedRepositories });
const journalDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-apt-recovery-'));
fs.chmodSync(journalDirectory, 0o700);

const authorizationRequests = [];
const authorizationBroker = {
  async authorize(request) {
    authorizationRequests.push(request);
    return { authorized: true, grantId: `grant-${authorizationRequests.length}`, actorId: 'uid:1000' };
  }
};
const trustVerifier = { async verifyRepository() { return { verified: true, proofId: 'test-proof' }; } };
const failingExecutor = {
  async execute() {
    const error = new Error('simulated acknowledgement loss after mutation handoff');
    error.code = 'ACK_LOST';
    throw error;
  }
};
const installedSnapshot = {
  async capture({ manager, packageName, packageId }) {
    return {
      schema: 'swir.package-snapshot/0.1', capturedAt: '2026-09-17T15:00:00.000Z', packageId,
      manager, packageName, installed: true, version: '1.0', query: { source: 'dpkg-query', exitCode: 0, signal: null }
    };
  }
};
const absentSnapshot = {
  async capture({ manager, packageName, packageId }) {
    return {
      schema: 'swir.package-snapshot/0.1', capturedAt: '2026-09-17T15:01:00.000Z', packageId,
      manager, packageName, installed: false, version: null, query: { source: 'dpkg-query', exitCode: 1, signal: null }
    };
  }
};
const healthyRemoved = {
  async verify({ packageId, packageName }) {
    return { schema: 'swir.package-health/0.1', packageId, packageName, healthy: true, checks: [{ id: 'removed', ok: true }] };
  }
};
const cleanDatabase = {
  async verify() {
    return {
      schema: 'swir.apt-database-consistency/0.1', healthy: true, mutationPerformed: false,
      checks: [
        { id: 'dpkg-audit', ok: true, exitCode: 0, signal: null },
        { id: 'apt-get-check', ok: true, exitCode: 0, signal: null }
      ]
    };
  }
};

const transactionService = new SystemPackageTransactionService({
  journalDirectory,
  executor: failingExecutor,
  authorizationBroker,
  trustVerifier,
  snapshotProvider: installedSnapshot,
  healthVerifier: healthyRemoved,
  allowlistedRepositories,
  idFactory: () => 'apt-recovery-test-0001',
  clock: (() => {
    let n = 0;
    return () => `2026-09-17T15:00:${String(n++).padStart(2, '0')}.000Z`;
  })()
});

await assert.rejects(
  () => transactionService.execute(provider.planRemove(manifest()), { actorId: 'uid:1000' }),
  error => error?.code === 'ACK_LOST'
);
const failed = transactionService.readJournal('apt-recovery-test-0001');
assert.equal(failed.state, 'failed-needs-recovery');

const recovery = new AptInterruptedTransactionRecoveryService({
  journalDirectory,
  authorizationBroker,
  snapshotProvider: absentSnapshot,
  healthVerifier: healthyRemoved,
  consistencyProbe: cleanDatabase,
  allowlistedRepositories,
  clock: () => '2026-09-17T15:02:00.000Z'
});
const outcomes = await recovery.recoverPending({ actorId: 'uid:1000' });
assert.deepEqual(outcomes, [{ id: 'apt-recovery-test-0001', status: 'committed', reconciled: true, mutationPerformed: false }]);
const recovered = recovery.readJournal('apt-recovery-test-0001');
assert.equal(recovered.state, 'committed');
assert.equal(recovered.error, null);
assert.equal(recovered.recovery.reconciliation.commitSafe, true);
assert.equal(recovered.recovery.reconciliation.packageMutationPerformedByRecovery, false);
assert.equal(recovered.recovery.reconciliation.desiredStateReached, true);
assert.equal(recovered.recovery.reconciliation.consistency.healthy, true);
assert.equal(recovered.recovery.reconciliation.authorization.scope, 'packages.recover');
assert.equal(authorizationRequests.at(-1).scope, 'packages.recover');
assert.equal(authorizationRequests.at(-1).planDigest, recovered.planDigest);

const ambiguousDirectory = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-apt-recovery-ambiguous-'));
fs.chmodSync(ambiguousDirectory, 0o700);
const absentBefore = {
  async capture({ manager, packageName, packageId }) {
    return {
      schema: 'swir.package-snapshot/0.1', capturedAt: '2026-09-17T16:00:00.000Z', packageId,
      manager, packageName, installed: false, version: null, query: { source: 'dpkg-query', exitCode: 1, signal: null }
    };
  }
};
const installService = new SystemPackageTransactionService({
  journalDirectory: ambiguousDirectory,
  executor: failingExecutor,
  authorizationBroker,
  trustVerifier,
  snapshotProvider: absentBefore,
  healthVerifier: healthyRemoved,
  allowlistedRepositories,
  idFactory: () => 'apt-recovery-test-0002'
});
await assert.rejects(
  () => installService.execute(provider.planInstall(manifest()), { actorId: 'uid:1000' }),
  error => error?.code === 'ACK_LOST'
);
const ambiguousRecovery = new AptInterruptedTransactionRecoveryService({
  journalDirectory: ambiguousDirectory,
  authorizationBroker,
  snapshotProvider: absentBefore,
  healthVerifier: {
    async verify({ packageId, packageName }) {
      return { schema: 'swir.package-health/0.1', packageId, packageName, healthy: false, checks: [{ id: 'native-entry-point', ok: false, reason: 'ENTRY_POINT_NOT_FOUND' }] };
    }
  },
  consistencyProbe: cleanDatabase,
  allowlistedRepositories
});
const ambiguous = await ambiguousRecovery.recoverPending({ actorId: 'uid:1000' });
assert.equal(ambiguous[0].status, 'failed-needs-recovery');
assert.equal(ambiguous[0].mutationPerformed, false);
const ambiguousJournal = ambiguousRecovery.readJournal('apt-recovery-test-0002');
assert.equal(ambiguousJournal.state, 'failed-needs-recovery');
assert.equal(ambiguousJournal.recovery.reconciliation.commitSafe, false);
assert.equal(ambiguousJournal.recovery.reconciliation.desiredStateReached, false);
assert.equal(ambiguousJournal.error.code, 'RECOVERY_REQUIRES_MANUAL_INTERVENTION');

fs.rmSync(journalDirectory, { recursive: true, force: true });
fs.rmSync(ambiguousDirectory, { recursive: true, force: true });
console.log('apt-interrupted-recovery self-test passed');
