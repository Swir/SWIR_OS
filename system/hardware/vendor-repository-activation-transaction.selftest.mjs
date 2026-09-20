import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  buildVendorRepositoryActivationPlan,
  assertVendorRepositoryActivationPlan,
  FileVendorRepositoryActivationJournal,
  FileVendorRepositorySourceStore,
  VendorRepositoryActivationTransactionService,
  VendorRepositoryActivationPolicy
} from './vendor-repository-activation-transaction-service.mjs';
import { bindVendorRepositoryTransaction } from './vendor-repository-transaction-binding.mjs';

const fingerprint = '02182E60104FCDC26EAE1B8597A5D4CB8793F200';
const review = {
  schema: 'swir.vendor-official-repository-review/0.1', repositoryId: 'nvidia-cuda-debian13-x86_64', vendor: 'NVIDIA',
  source: { class: 'vendor-official-repository', ref: 'vendor-repo:nvidia-cuda-debian13-x86_64' }, packageManager: 'apt',
  baseUrl: 'https://developer.download.nvidia.com/compute/cuda/repos/debian13/x86_64/', suites: ['./'], components: [],
  packages: ['cuda-keyring', 'nvidia-open'], keyring: { path: '/usr/share/keyrings/nvidia-cuda-archive-keyring.gpg', fingerprint },
  hardwareVendor: '10de', distribution: { id: 'debian', versionId: '13', architecture: 'x86_64' }, trustedSource: true,
  directBinaryDownloads: false, mutationAuthorized: false, automaticEnable: false
};
const evidence = {
  schema: 'swir.vendor-repository-evidence/0.1', qualificationOnly: true, authorizesMutation: false, authorizesRepositoryEnablement: false,
  profileId: 'nvidia-debian13-amd64', repositoryId: review.repositoryId, vendor: 'NVIDIA', hardwareVendor: '10de',
  distribution: { id: 'debian', versionId: '13', architecture: 'x86_64' },
  source: { origin: 'https://developer.download.nvidia.com', basePath: '/compute/cuda/repos/debian13/x86_64/' },
  key: { fingerprint, expectedFingerprint: fingerprint, sha256: 'a'.repeat(64) },
  inRelease: { validSignaturePrimaryFingerprint: fingerprint, freshnessVerified: true, signedAt: '2026-09-18T00:00:00.000Z', effectiveValidUntil: '2026-09-30T00:00:00.000Z', checkedAt: '2026-09-19T00:00:00.000Z', sha256: 'b'.repeat(64) },
  packages: { verified: ['cuda-keyring', 'nvidia-open'], indexSha256: 'c'.repeat(64) }
};
const binding = bindVendorRepositoryTransaction({ review, evidence, requestedPackages: ['nvidia-open'], now: new Date('2026-09-19T01:00:00.000Z') });

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-vendor-activation-'));
const sourceRoot = path.join(root, 'sources.list.d');
const journalRoot = path.join(root, 'journal');
fs.mkdirSync(sourceRoot, { mode: 0o755 });
const plan = buildVendorRepositoryActivationPlan(binding, { sourceRoot, now: new Date('2026-09-19T02:00:00.000Z') });
assert.equal(assertVendorRepositoryActivationPlan(plan, { allowedSourceRoot: sourceRoot, now: new Date('2026-09-19T02:00:00.000Z') }), true);
assert.match(plan.source.content, /^Types: deb$/m);
assert.match(plan.source.content, /^Architectures: amd64$/m);
assert.match(plan.source.content, /^Signed-By: \/usr\/share\/keyrings\/nvidia-cuda-archive-keyring\.gpg$/m);
assert.match(plan.source.content, /^Trusted: no$/m);
assert.deepEqual(plan.updateCommand, ['apt-get', '-o', `Dir::Etc::sourcelist=${plan.source.path}`, '-o', 'Dir::Etc::sourceparts=-', '-o', 'APT::Get::List-Cleanup=0', 'update']);

const journal = new FileVendorRepositoryActivationJournal({ root: journalRoot, enforceOwnership: false });
const sourceStore = new FileVendorRepositorySourceStore({ root: sourceRoot, enforceOwnership: false });
const calls = [];
const service = new VendorRepositoryActivationTransactionService({
  journal, sourceStore, allowedSourceRoot: sourceRoot, enforceRoot: false,
  keyringVerifier: { verify(keyring) { assert.equal(keyring.fingerprint, fingerprint); return { verified: true, fingerprint }; } },
  authorizationBroker: { async authorize(request) { calls.push(['authorize', request]); return { authorized: true, authorizationId: 'auth-test-001' }; } },
  executor: { async run(argv) { calls.push(['run', argv]); return { exitCode: 0, signal: null }; } },
  clock: () => '2026-09-19T03:00:00.000Z', idFactory: () => 'vendor-tx-0001'
});

await assert.rejects(() => service.execute(plan, { confirmationDigest: '0'.repeat(64) }), error => error?.code === 'ACTIVATION_CONFIRMATION_MISMATCH');
const committed = await service.execute(plan, { actorId: 'tester', confirmationDigest: plan.activationDigest });
assert.equal(committed.state, 'committed');
assert.equal(fs.readFileSync(plan.source.path, 'utf8'), plan.source.content);
assert.equal(calls.filter(item => item[0] === 'run').length, 1);
assert.equal(service.inspectRecovery().length, 0);

const failingRoot = path.join(root, 'failing-sources');
const failingJournalRoot = path.join(root, 'failing-journal');
fs.mkdirSync(failingRoot, { mode: 0o755 });
const failingPlan = buildVendorRepositoryActivationPlan(binding, { sourceRoot: failingRoot, now: new Date('2026-09-19T02:00:00.000Z') });
const previous = '# previous trusted config\n';
fs.writeFileSync(failingPlan.source.path, previous, { mode: 0o644 });
const failingService = new VendorRepositoryActivationTransactionService({
  journal: new FileVendorRepositoryActivationJournal({ root: failingJournalRoot, enforceOwnership: false }),
  sourceStore: new FileVendorRepositorySourceStore({ root: failingRoot, enforceOwnership: false }),
  allowedSourceRoot: failingRoot, enforceRoot: false,
  keyringVerifier: { verify() { return { verified: true }; } },
  authorizationBroker: { async authorize() { return { authorized: true, authorizationId: 'auth-test-002' }; } },
  executor: { async run() { return { exitCode: 100, signal: null }; } },
  clock: () => '2026-09-19T03:00:00.000Z', idFactory: () => 'vendor-tx-0002'
});
await assert.rejects(() => failingService.execute(failingPlan, { confirmationDigest: failingPlan.activationDigest }), error => error?.code === 'ACTIVATION_METADATA_REFRESH_FAILED');
assert.equal(fs.readFileSync(failingPlan.source.path, 'utf8'), previous, 'synchronous metadata failure must restore previous source state');
assert.equal(failingService.inspectRecovery().length, 0);

const symlinkRoot = path.join(root, 'symlink-sources');
fs.mkdirSync(symlinkRoot, { mode: 0o755 });
const symlinkPlan = buildVendorRepositoryActivationPlan(binding, { sourceRoot: symlinkRoot, now: new Date('2026-09-19T02:00:00.000Z') });
const victim = path.join(root, 'victim');
fs.writeFileSync(victim, 'victim\n');
fs.symlinkSync(victim, symlinkPlan.source.path);
const symlinkStore = new FileVendorRepositorySourceStore({ root: symlinkRoot, enforceOwnership: false });
assert.throws(() => symlinkStore.inspect(symlinkPlan.source.path), error => error?.code === 'ACTIVATION_SOURCE_FILE_UNSAFE');
assert.equal(fs.readFileSync(victim, 'utf8'), 'victim\n');

const recoveryRoot = path.join(root, 'recovery-sources');
const recoveryJournalRoot = path.join(root, 'recovery-journal');
fs.mkdirSync(recoveryRoot, { mode: 0o755 });
const recoveryPlan = buildVendorRepositoryActivationPlan(binding, { sourceRoot: recoveryRoot, now: new Date('2026-09-19T02:00:00.000Z') });
const realRecoveryStore = new FileVendorRepositorySourceStore({ root: recoveryRoot, enforceOwnership: false });
let restoreAttempts = 0;
const flakyRecoveryStore = {
  inspect: (...args) => realRecoveryStore.inspect(...args),
  write: (...args) => realRecoveryStore.write(...args),
  restore: (...args) => {
    restoreAttempts += 1;
    if (restoreAttempts === 1) {
      const error = new Error('simulated interrupted rollback');
      error.code = 'SIMULATED_ROLLBACK_INTERRUPTION';
      throw error;
    }
    return realRecoveryStore.restore(...args);
  }
};
const recoveryService = new VendorRepositoryActivationTransactionService({
  journal: new FileVendorRepositoryActivationJournal({ root: recoveryJournalRoot, enforceOwnership: false }),
  sourceStore: flakyRecoveryStore, allowedSourceRoot: recoveryRoot, enforceRoot: false,
  keyringVerifier: { verify() { return { verified: true }; } },
  authorizationBroker: { async authorize(request) { return { authorized: true, authorizationId: request.schema.includes('recovery') ? 'auth-recovery-001' : 'auth-test-003' }; } },
  executor: { async run() { return { exitCode: 100, signal: null }; } },
  clock: () => '2026-09-19T03:00:00.000Z', idFactory: () => 'vendor-tx-0003'
});
await assert.rejects(() => recoveryService.execute(recoveryPlan, { confirmationDigest: recoveryPlan.activationDigest }), error => error?.code === 'ACTIVATION_METADATA_REFRESH_FAILED');
assert.equal(recoveryService.inspectRecovery().length, 1, 'failed rollback must surface explicit recovery evidence');
assert.equal(fs.readFileSync(recoveryPlan.source.path, 'utf8'), recoveryPlan.source.content, 'interrupted rollback leaves only the exact staged source for later review');
const recovered = await recoveryService.recoverSource('vendor-tx-0003', { confirmationDigest: recoveryPlan.activationDigest });
assert.equal(recovered.state, 'rolled-back');
assert.equal(fs.existsSync(recoveryPlan.source.path), false, 'operator recovery must restore the previously absent source');
assert.equal(recoveryService.inspectRecovery().length, 0);

assert.throws(
  () => assertVendorRepositoryActivationPlan(plan, { allowedSourceRoot: sourceRoot, now: new Date('2026-10-01T00:00:00.000Z') }),
  error => error?.code === 'ACTIVATION_EVIDENCE_EXPIRED',
  'expired qualification evidence must fail closed at mutation time'
);

assert.equal(VendorRepositoryActivationPolicy.existingPrivilegeBrokerRequired, true);
assert.equal(VendorRepositoryActivationPolicy.directPackageInstall, false);
assert.equal(VendorRepositoryActivationPolicy.arbitraryRepositoryUrl, false);
assert.equal(VendorRepositoryActivationPolicy.arbitraryKeyDownload, false);
assert.equal(VendorRepositoryActivationPolicy.shellExecution, false);
console.log(`vendor repository activation transaction self-test passed digest=${plan.activationDigest}`);
