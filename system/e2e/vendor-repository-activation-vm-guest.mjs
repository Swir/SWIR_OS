import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import {
  loadVendorOfficialRepositoryPolicy,
  resolveVendorOfficialRepositories,
  assertSafeVendorRepositoryReview
} from '../hardware/vendor-official-repository-service.mjs';
import {
  collectVendorRepositoryEvidence,
  getVendorRepositoryEvidenceProfile,
  parseGpgPrimaryFingerprint
} from '../hardware/vendor-repository-trust-evidence.mjs';
import { bindVendorRepositoryTransaction } from '../hardware/vendor-repository-transaction-binding.mjs';
import { resolveDriverPlan, assertSafeDriverPlan } from '../hardware/driver-resolver.mjs';
import {
  FileVendorRepositoryActivationJournal,
  FileVendorRepositorySourceStore,
  GpgVendorKeyringVerifier,
  VendorRepositoryActivationTransactionService
} from '../hardware/vendor-repository-activation-transaction-service.mjs';
import {
  createVendorRepositoryActivationReview,
  DriverCenterVendorRepositoryCoordinator
} from '../hardware/vendor-repository-driver-center-integration.mjs';

const OUTPUT = '/var/lib/swir/e2e/vendor-repository-activation-vm-evidence.json';
const POLICY = '/etc/swir/hardware/vendor-repositories.json';
const CATALOG = '/opt/swir/system/hardware/hardware-catalog.json';
const SOURCE_ROOT = '/etc/apt/sources.list.d';
const JOURNAL_ROOT = '/var/lib/swir/transactions/vendor-repositories';
const PROFILE_ID = 'nvidia-debian13-amd64';
const PACKAGE = 'nvidia-open';
const EXPECTED_FINGERPRINT = '02182E60104FCDC26EAE1B8597A5D4CB8793F200';

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function sha256(bytes) {
  return crypto.createHash('sha256').update(bytes).digest('hex');
}

function command(file, args, { timeout = 120000, env = {} } = {}) {
  const result = spawnSync(file, args, {
    encoding: 'utf8',
    maxBuffer: 2 * 1024 * 1024,
    timeout,
    shell: false,
    env: { PATH: '/usr/sbin:/usr/bin:/sbin:/bin', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8', ...env }
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const error = new Error(`${path.basename(file)} exited ${result.status}: ${String(result.stderr || '').slice(0, 1000)}`);
    error.exitCode = result.status;
    throw error;
  }
  return result;
}

async function fetchPinnedKey(profile, evidence) {
  const url = new URL(profile.keyPath, profile.origin).toString();
  assert(url === evidence.source.keyUrl, 'key URL no longer matches qualified evidence');
  const response = await fetch(url, {
    redirect: 'manual',
    headers: { 'user-agent': 'SWIR-OS-vendor-repository-vm-e2e/0.1' },
    signal: AbortSignal.timeout(20000)
  });
  assert(response.status === 200 && !response.headers.get('location'), 'pinned signing key fetch failed or redirected');
  const declared = Number(response.headers.get('content-length') || 0);
  assert(!Number.isFinite(declared) || declared <= 128 * 1024, 'pinned signing key exceeds size bound');
  const bytes = Buffer.from(await response.arrayBuffer());
  assert(bytes.length > 0 && bytes.length <= 128 * 1024, 'pinned signing key is empty or oversized');
  assert(sha256(bytes) === evidence.key.sha256, 'signing key changed after qualification evidence was collected');
  return bytes;
}

function installQualifiedKeyring(profile, evidence, review, keyBytes) {
  const scratchRoot = '/run/swir-vendor-e2e';
  const targetDir = path.dirname(review.keyring.path);
  fs.mkdirSync(scratchRoot, { recursive: true, mode: 0o700 });
  fs.mkdirSync(targetDir, { recursive: true, mode: 0o755 });
  const armored = path.join(scratchRoot, 'vendor-key.asc');
  const temporary = path.join(targetDir, `.${path.basename(review.keyring.path)}.${process.pid}.${crypto.randomBytes(6).toString('hex')}.tmp`);
  fs.writeFileSync(armored, keyBytes, { mode: 0o600 });
  const shown = command('/usr/bin/gpg', ['--batch', '--no-options', '--with-colons', '--show-keys', armored]);
  const fingerprint = parseGpgPrimaryFingerprint(shown.stdout);
  assert(fingerprint === EXPECTED_FINGERPRINT, 'downloaded signing key does not match pinned full fingerprint');
  assert(fingerprint === evidence.key.fingerprint && fingerprint === review.keyring.fingerprint, 'policy/evidence/signing-key fingerprint mismatch');
  try {
    command('/usr/bin/gpg', ['--batch', '--no-options', '--yes', '--dearmor', '--output', temporary, armored]);
    const tempStat = fs.lstatSync(temporary);
    assert(tempStat.isFile() && !tempStat.isSymbolicLink(), 'temporary vendor keyring is not a regular file');
    fs.chownSync(temporary, 0, 0);
    fs.chmodSync(temporary, 0o644);
    if (fs.existsSync(review.keyring.path)) {
      const stat = fs.lstatSync(review.keyring.path);
      assert(stat.isFile() && !stat.isSymbolicLink(), 'pre-existing vendor keyring path is unsafe');
      assert((stat.mode & 0o022) === 0, 'pre-existing vendor keyring path is group/world writable');
    }
    fs.renameSync(temporary, review.keyring.path);
    const finalStat = fs.lstatSync(review.keyring.path);
    assert(finalStat.isFile() && !finalStat.isSymbolicLink() && finalStat.uid === 0 && (finalStat.mode & 0o777) === 0o644, 'qualified vendor keyring final state is unsafe');
  } finally {
    try { fs.unlinkSync(temporary); } catch {}
  }
}

function rootPolicyMode(pathname) {
  const stat = fs.lstatSync(pathname);
  return { uid: stat.uid, mode: stat.mode & 0o777, regular: stat.isFile(), symlink: stat.isSymbolicLink() };
}

function buildSnapshot(catalog) {
  const entry = catalog.entries.find(candidate => candidate.id === 'pci.nvidia.2684');
  assert(entry, 'NVIDIA catalog entry missing');
  return {
    schema: 'swir.hardware-snapshot/0.2',
    generatedAt: new Date().toISOString(),
    host: {
      readOnly: true,
      arch: 'x86_64',
      distribution: { id: 'debian', versionId: '13', family: 'debian' },
      capabilities: {
        fwupd: { available: false, lvfsMetadataPresent: false },
        packageManagers: ['apt'],
        repositoryConfig: [{ manager: 'apt' }]
      }
    },
    devices: [{
      key: 'pci:0000:01:00.0',
      bus: 'pci',
      ids: { vendor: '10de', device: '2684' },
      driver: { status: 'unbound', module: null, modalias: 'pci:v000010DEd00002684sv00000000sd00000000bc03sc00i00' },
      catalog: { matched: true, entryIds: [entry.id], recommendedSources: entry.sources }
    }]
  };
}

function realMetadataExecutor() {
  return {
    async run(argv) {
      assert(Array.isArray(argv) && argv[0] === 'apt-get' && argv.at(-1) === 'update', 'unexpected metadata refresh argv');
      const result = spawnSync('/usr/bin/apt-get', argv.slice(1), {
        encoding: 'utf8',
        maxBuffer: 4 * 1024 * 1024,
        timeout: 180000,
        shell: false,
        env: { PATH: '/usr/sbin:/usr/bin:/sbin:/bin', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8', DEBIAN_FRONTEND: 'noninteractive' }
      });
      if (result.error) throw result.error;
      return { exitCode: result.status ?? 127, signal: result.signal || null, stdout: String(result.stdout || ''), stderr: String(result.stderr || '') };
    }
  };
}

function fixedAuthorizationBroker(events) {
  return {
    async authorize(request, context) {
      assert(context?.actorId === 'swir-vendor-vm-e2e', 'unexpected authorization actor');
      assert(typeof request?.schema === 'string' && request.schema.startsWith('swir.vendor-repository-'), 'unexpected authorization request');
      events.push(request.schema);
      return { authorized: true, authorizationId: `vm-auth-${events.length}` };
    }
  };
}

function packageVisible(sourcePath) {
  const result = command('/usr/bin/apt-cache', [
    '-o', `Dir::Etc::sourcelist=${sourcePath}`,
    '-o', 'Dir::Etc::sourceparts=-',
    'policy', PACKAGE
  ], { timeout: 60000 });
  const output = `${result.stdout}\n${result.stderr}`;
  return /Candidate:\s*(?!\(none\))\S+/.test(output) && output.includes(`${PACKAGE}:`);
}

function createService({ id, journal, sourceStore, keyringVerifier, authorizationBroker, executor }) {
  return new VendorRepositoryActivationTransactionService({
    journal,
    sourceStore,
    keyringVerifier,
    authorizationBroker,
    executor,
    allowedSourceRoot: SOURCE_ROOT,
    enforceRoot: true,
    idFactory: () => id
  });
}

async function run() {
  assert(typeof process.geteuid !== 'function' || process.geteuid() === 0, 'VM E2E guest must run as root');
  const virt = command('/usr/bin/systemd-detect-virt', []).stdout.trim();
  assert(virt && virt !== 'none', 'disposable vendor repository E2E must run inside a VM');

  const policyMode = rootPolicyMode(POLICY);
  assert(policyMode.regular && !policyMode.symlink && policyMode.uid === 0 && (policyMode.mode & 0o022) === 0, 'vendor repository policy is not root-owned/read-only');
  const policy = await loadVendorOfficialRepositoryPolicy(POLICY);
  const reviews = resolveVendorOfficialRepositories(policy, { hardwareVendor: '10de', distributionId: 'debian', versionId: '13', architecture: 'x86_64' });
  assert(reviews.length === 1, 'root-owned policy did not resolve exactly one NVIDIA Debian 13 repository');
  const repositoryReview = reviews[0];
  assertSafeVendorRepositoryReview(repositoryReview);

  const evidence = await collectVendorRepositoryEvidence(PROFILE_ID);
  assert(evidence.repositoryId === repositoryReview.repositoryId, 'qualified evidence repository does not match root-owned policy');
  assert(evidence.inRelease.freshnessVerified === true && Date.parse(evidence.inRelease.effectiveValidUntil) >= Date.now(), 'qualified repository evidence is stale');
  assert(evidence.packages.verified.includes(PACKAGE), 'qualified repository evidence does not include the selected driver package');
  const profile = getVendorRepositoryEvidenceProfile(PROFILE_ID);
  const keyBytes = await fetchPinnedKey(profile, evidence);
  installQualifiedKeyring(profile, evidence, repositoryReview, keyBytes);

  const binding = bindVendorRepositoryTransaction({
    review: repositoryReview,
    evidence,
    requestedPackages: [PACKAGE],
    now: new Date()
  });
  const catalog = JSON.parse(fs.readFileSync(CATALOG, 'utf8'));
  const snapshot = buildSnapshot(catalog);
  const driverPlan = resolveDriverPlan(snapshot, catalog, { now: new Date(), vendorRepositoryBindings: [binding] });
  assertSafeDriverPlan(driverPlan);
  const packageOperations = driverPlan.operations.filter(operation => operation.kind === 'review-package');
  assert(packageOperations.length === 1, 'Driver Center did not produce exactly one package review operation');
  const packageOperation = packageOperations[0];
  assert(packageOperation.packageCandidates.includes(PACKAGE), 'Driver Center package review omitted qualified vendor package');
  assert(packageOperation.sources.some(source => source.class === 'vendor-official-repository' && source.repositoryId === repositoryReview.repositoryId), 'Driver Center omitted verified vendor source');

  const driverReview = createVendorRepositoryActivationReview({
    driverPlan,
    operationId: packageOperation.id,
    vendorRepositoryBindings: [binding],
    sourceRoot: SOURCE_ROOT,
    now: new Date()
  });
  fs.mkdirSync(JOURNAL_ROOT, { recursive: true, mode: 0o700 });
  fs.chmodSync(JOURNAL_ROOT, 0o700);
  const journal = new FileVendorRepositoryActivationJournal({ root: JOURNAL_ROOT, enforceOwnership: true });
  const sourceStore = new FileVendorRepositorySourceStore({ root: SOURCE_ROOT, enforceOwnership: true });
  const keyringVerifier = new GpgVendorKeyringVerifier({ enforceOwnership: true });
  const authorizationEvents = [];
  const broker = fixedAuthorizationBroker(authorizationEvents);

  const activationService = createService({
    id: 'vendor-vm-activation-0001', journal, sourceStore, keyringVerifier, authorizationBroker: broker, executor: realMetadataExecutor()
  });
  const coordinator = new DriverCenterVendorRepositoryCoordinator({ activationService });
  const committed = await coordinator.activate(driverReview, {
    actorId: 'swir-vendor-vm-e2e', confirmationDigest: driverReview.activationPlan.activationDigest, sourceRoot: SOURCE_ROOT, now: new Date()
  });
  assert(committed.state === 'committed', 'vendor repository activation did not commit');
  assert(packageVisible(driverReview.activationPlan.source.path), 'signed vendor metadata did not expose selected package after activation');
  const deactivated = await coordinator.deactivate(committed.transactionId, driverReview, {
    actorId: 'swir-vendor-vm-e2e', confirmationDigest: driverReview.activationPlan.activationDigest, sourceRoot: SOURCE_ROOT, now: new Date()
  });
  assert(deactivated.state === 'rolled-back' && deactivated.result?.explicitDeactivation === true, 'explicit vendor repository deactivation did not restore pre-activation state');
  assert(sourceStore.inspect(driverReview.activationPlan.source.path).existed === false, 'vendor repository source remained after explicit deactivation');

  let rollbackFaultArmed = true;
  const interruptedSourceStore = {
    inspect: file => sourceStore.inspect(file),
    write: (file, content) => sourceStore.write(file, content),
    restore(file, previous) {
      if (rollbackFaultArmed) {
        rollbackFaultArmed = false;
        const error = new Error('fault-injected interrupted rollback');
        error.code = 'VM_FAULT_INJECTED_ROLLBACK_INTERRUPTION';
        throw error;
      }
      return sourceStore.restore(file, previous);
    }
  };
  const failingExecutor = { async run() { return { exitCode: 75, signal: null, stdout: '', stderr: 'fault-injected metadata refresh interruption' }; } };
  const interruptedService = createService({
    id: 'vendor-vm-interrupted-0001', journal, sourceStore: interruptedSourceStore, keyringVerifier, authorizationBroker: broker, executor: failingExecutor
  });
  const interruptedCoordinator = new DriverCenterVendorRepositoryCoordinator({ activationService: interruptedService });
  await assert.rejects(() => interruptedCoordinator.activate(driverReview, {
    actorId: 'swir-vendor-vm-e2e', confirmationDigest: driverReview.activationPlan.activationDigest, sourceRoot: SOURCE_ROOT, now: new Date()
  }));
  const interruptedRecord = journal.read('vendor-vm-interrupted-0001');
  assert(interruptedRecord.state === 'failed-needs-recovery', 'fault injection did not leave durable failed-needs-recovery state');
  assert(sourceStore.inspect(driverReview.activationPlan.source.path).sha256 === driverReview.activationPlan.source.sha256, 'interrupted source state is not bound to activation plan');

  const recoveryService = createService({
    id: 'unused-recovery-id', journal, sourceStore, keyringVerifier, authorizationBroker: broker, executor: realMetadataExecutor()
  });
  const recoveryCoordinator = new DriverCenterVendorRepositoryCoordinator({ activationService: recoveryService });
  const recoveryAssessments = recoveryService.inspectRecovery();
  assert(recoveryAssessments.some(item => item.transactionId === 'vendor-vm-interrupted-0001' && item.sourceRestoreRequired === true), 'durable recovery assessment did not expose interrupted source');
  const recovered = await recoveryCoordinator.recover('vendor-vm-interrupted-0001', driverReview, {
    actorId: 'swir-vendor-vm-e2e', confirmationDigest: driverReview.activationPlan.activationDigest, sourceRoot: SOURCE_ROOT, now: new Date()
  });
  assert(recovered.state === 'rolled-back', 'operator-authorized source recovery did not finish rolled-back');
  assert(sourceStore.inspect(driverReview.activationPlan.source.path).existed === false, 'source was not restored after interrupted transaction recovery');
  assert(recoveryService.inspectRecovery().length === 0, 'recovery queue was not cleared after successful source restoration');

  return {
    schema: 'swir.vendor-repository-activation-vm-e2e/0.1',
    passed: true,
    observedAt: new Date().toISOString(),
    environment: { virtualization: virt, distribution: 'debian-13', architecture: 'x86_64', physicalHardwareClaim: false, liveUsbClaim: false },
    policy: { path: POLICY, rootOwned: policyMode.uid === 0, groupWorldWritable: (policyMode.mode & 0o022) !== 0, repositoryId: repositoryReview.repositoryId, automaticEnable: repositoryReview.automaticEnable },
    trust: { fingerprint: evidence.key.fingerprint, evidenceFresh: true, evidenceValidUntil: evidence.inRelease.effectiveValidUntil, inReleaseSha256: evidence.inRelease.sha256, packagesIndexSha256: evidence.packages.indexSha256 },
    driverCenter: { operationId: packageOperation.id, bindingDigest: binding.bindingDigest, activationDigest: driverReview.activationPlan.activationDigest, package: PACKAGE, vendorSourceVerified: true },
    activation: { transactionId: committed.transactionId, state: committed.state, metadataRefreshExitCode: committed.result?.metadataRefreshExitCode, packageVisible: true, explicitDeactivationState: deactivated.state, sourceRestoredAfterDeactivation: true },
    interruptionRecovery: { mode: 'fault-injected-rollback-interruption', transactionId: interruptedRecord.transactionId, interruptedState: interruptedRecord.state, operatorAssessmentObserved: true, recoveredState: recovered.state, sourceRestored: true },
    authorization: { harness: 'disposable-vm-root-broker-stub', requestSchemas: authorizationEvents },
    safety: { packageInstalled: false, automaticRepositoryEnablement: false, directPkexecPath: false, arbitraryRepositoryUrl: false, arbitraryKeyDownload: false }
  };
}

async function main() {
  fs.mkdirSync(path.dirname(OUTPUT), { recursive: true, mode: 0o700 });
  let output;
  let exitCode = 0;
  try {
    output = await run();
  } catch (error) {
    exitCode = 1;
    output = {
      schema: 'swir.vendor-repository-activation-vm-e2e/0.1',
      passed: false,
      observedAt: new Date().toISOString(),
      error: { name: error?.name || 'Error', code: error?.code || null, message: String(error?.message || error).slice(0, 2000) },
      environment: { physicalHardwareClaim: false, liveUsbClaim: false }
    };
  }
  fs.writeFileSync(OUTPUT, `${JSON.stringify(output, null, 2)}\n`, { mode: 0o600 });
  try { command('/usr/bin/sync', []); } catch {}
  spawnSync('/usr/bin/systemctl', ['poweroff', '--no-block'], { shell: false, stdio: 'ignore' });
  process.exitCode = exitCode;
}

await main();
