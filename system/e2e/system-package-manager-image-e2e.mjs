import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { DistributionPackageProvider } from '../packages/distribution-package-provider.mjs';
import { AptDependencyResolver } from '../packages/apt-dependency-resolver.mjs';
import { SystemPackageTransactionService } from '../packages/package-transaction-service.mjs';
import { DistributionPackageSnapshotProvider, NativePackageHealthVerifier } from '../packages/distribution-package-state.mjs';
import { SystemPackageStack } from '../packages/system-package-stack.mjs';
import { validatePackageExecutorRequest } from '../packages/privileged-package-executor.mjs';
import { AptDatabaseConsistencyProbe, AptInterruptedTransactionRecoveryService } from '../packages/apt-interrupted-recovery.mjs';

function fail(code, message) {
  const error = new Error(message);
  error.name = 'SystemPackageManagerImageE2EError';
  error.code = code;
  throw error;
}
function assert(condition, code, message) { if (!condition) fail(code, message); }
function parseArgs(argv) {
  const out = { output: null };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--output') out.output = argv[++i] || null;
    else fail('INVALID_ARGUMENT', `Unsupported argument: ${argv[i]}`);
  }
  return out;
}
function readOsRelease() {
  const out = {};
  for (const line of fs.readFileSync('/etc/os-release', 'utf8').split(/\r?\n/)) {
    const match = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (match) out[match[1]] = match[2].replace(/^"|"$/g, '');
  }
  return out;
}
function trustedRootFile(filePath) {
  const stat = fs.lstatSync(filePath);
  assert(stat.isFile() && !stat.isSymbolicLink(), 'UNTRUSTED_FILE', `${filePath} must be a regular non-symlink file`);
  assert(stat.uid === 0, 'UNTRUSTED_FILE_OWNER', `${filePath} must be root-owned`);
  assert((stat.mode & 0o022) === 0, 'UNTRUSTED_FILE_MODE', `${filePath} must not be group/world writable`);
  return { uid: stat.uid, mode: stat.mode & 0o777 };
}
function run(file, args, { timeout = 180_000 } = {}) {
  const result = spawnSync(file, args, {
    shell: false,
    encoding: 'utf8',
    timeout,
    maxBuffer: 2 * 1024 * 1024,
    env: { PATH: '/usr/sbin:/usr/bin:/sbin:/bin', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8', DEBIAN_FRONTEND: 'noninteractive' }
  });
  if (result.error) throw result.error;
  return { exitCode: result.status, signal: result.signal || null, stdout: String(result.stdout || ''), stderr: String(result.stderr || '') };
}
function manifest() {
  return {
    schema: 'swir.package-provider/0.2', id: 'swir.e2e.cowsay', targetEditions: ['system'], executionClass: 'linux-native', provider: 'swir.package.system',
    package: { name: 'cowsay', sourceRef: 'cowsay', nativeEntryPoint: '/usr/games/cowsay' },
    trust: { sourceClass: 'distribution-repository', repositoryId: 'debian-main', signatureRequired: true }
  };
}

const args = parseArgs(process.argv.slice(2));
const os = readOsRelease();
assert(os.ID === 'debian' && /^13(?:\.|$)/.test(os.VERSION_ID || ''), 'WRONG_BASE', 'E2E requires Debian 13');
const aptFile = trustedRootFile('/usr/bin/apt-get');
const dpkgFile = trustedRootFile('/usr/bin/dpkg-query');
const dpkgAdminFile = trustedRootFile('/usr/bin/dpkg');
const policyFile = trustedRootFile('/etc/swir/repository-trust-policy.json');
const policy = JSON.parse(fs.readFileSync('/etc/swir/repository-trust-policy.json', 'utf8'));
assert(policy.repositories?.some(item => item.id === 'debian-main' && item.manager === 'apt' && item.signatureVerification === 'native-required' && item.allowInsecure === false), 'TRUST_POLICY_MISSING', 'debian-main signed APT policy missing');

const before = run('/usr/bin/dpkg-query', ['-W', '-f=${Status}\t${Version}\n', 'cowsay']);
assert(before.exitCode !== 0, 'FIXTURE_ALREADY_INSTALLED', 'cowsay must not be preinstalled in disposable image');

const host = { distribution: { id: 'debian', family: 'debian', version: os.VERSION_ID }, capabilities: { packageManagers: ['apt'] } };
const allowlistedRepositories = ['debian-main'];
const provider = new DistributionPackageProvider({ host, allowlistedRepositories });
const dependencyResolver = new AptDependencyResolver();
const dependencyPreview = await dependencyResolver.resolve({ operation: 'install', packageName: 'cowsay' });
assert(dependencyPreview.packages.affected.includes('cowsay'), 'FIXTURE_NOT_IN_PLAN', 'APT simulation must include cowsay');
assert(dependencyPreview.packages.affected.length >= 2, 'NO_DEPENDENCY_CLOSURE', 'Fixture must exercise at least one additional dependency/configuration package');

const authorizationEvents = [];
const authorizationBroker = {
  async authorize(request) {
    authorizationEvents.push(request);
    return { authorized: true, grantId: `ci-contained-root-grant-${authorizationEvents.length}`, actorId: 'ci-root-contained' };
  }
};
const trustVerifier = {
  async verifyRepository(request) {
    assert(request.repositoryId === 'debian-main', 'UNTRUSTED_REPOSITORY', 'E2E transaction escaped debian-main');
    return { verified: true, proofId: 'ci-image-policy-proof' };
  }
};
const executionEvents = [];
const executor = {
  async execute(request) {
    const { command } = validatePackageExecutorRequest(request);
    assert(request.manager === 'apt', 'WRONG_MANAGER', 'E2E root executor only permits apt');
    const result = run('/usr/bin/apt-get', ['-y', ...command.slice(1)], { timeout: 300_000 });
    executionEvents.push({ command, transportArgs: ['-y', ...command.slice(1)], exitCode: result.exitCode });
    assert(result.exitCode === 0, 'APT_MUTATION_FAILED', result.stderr.slice(0, 1000) || 'apt mutation failed');
    return { schema: 'swir.package-executor-result/0.1', ok: true, transactionId: request.transactionId, manager: 'apt', operation: request.operation, exitCode: 0, signal: result.signal, stdout: result.stdout.slice(0, 256 * 1024), stderr: result.stderr.slice(0, 256 * 1024) };
  }
};
const journalDirectory = '/var/lib/swir/package-manager-e2e';
fs.rmSync(journalDirectory, { recursive: true, force: true });
const transactionService = new SystemPackageTransactionService({
  journalDirectory, executor, authorizationBroker, trustVerifier,
  snapshotProvider: new DistributionPackageSnapshotProvider(), healthVerifier: new NativePackageHealthVerifier(),
  allowlistedRepositories, idFactory: () => 'apt-image-e2e-0001'
});
const securityBoundary = { allowlistedRepositories, describe: () => ({ schema: 'swir.system-package-security-boundary/0.1', ciHarness: true }) };
const stack = new SystemPackageStack({ provider, transactionService, securityBoundary, dependencyResolver });
const record = await stack.execute('install', manifest(), { reason: 'contained Debian image E2E' });
assert(record.state === 'committed', 'TRANSACTION_NOT_COMMITTED', 'APT package transaction did not commit');
assert(record.plan.dependencies?.schema === 'swir.apt-dependency-plan/0.1', 'DEPENDENCIES_NOT_JOURNALED', 'dependency plan missing from transaction journal');
assert(record.plan.dependencies.packages.affected.length >= 2, 'DEPENDENCIES_NOT_JOURNALED', 'dependency closure was not bound into journaled plan');
assert(record.snapshot?.installed === false, 'PRESTATE_NOT_CAPTURED', 'pre-mutation snapshot must prove fixture absent');
assert(record.health?.healthy === true, 'HEALTH_NOT_VERIFIED', 'post-mutation native entry point health must pass');
assert(authorizationEvents.length === 1 && authorizationEvents[0].scope === 'packages.mutate', 'AUTHORIZATION_NOT_BOUND', 'mutation authorization was not requested');
assert(executionEvents.length === 1, 'UNEXPECTED_EXECUTION_COUNT', 'exactly one privileged mutation expected');

const afterInstall = run('/usr/bin/dpkg-query', ['-W', '-f=${Status}\t${Version}\n', 'cowsay']);
assert(afterInstall.exitCode === 0 && /^install ok installed\t/m.test(afterInstall.stdout), 'PACKAGE_NOT_INSTALLED', 'cowsay must be installed after transaction');
const entryStat = fs.lstatSync('/usr/games/cowsay');
assert(entryStat.isFile() || entryStat.isSymbolicLink(), 'ENTRYPOINT_MISSING', 'cowsay entry point missing');
const journalPath = path.join(journalDirectory, 'apt-image-e2e-0001.json');
const journalStat = fs.lstatSync(journalPath);
assert(journalStat.isFile() && (journalStat.mode & 0o077) === 0, 'UNSAFE_JOURNAL', 'transaction journal must be owner-only');
const persisted = JSON.parse(fs.readFileSync(journalPath, 'utf8'));
assert(persisted.state === 'committed' && persisted.plan?.dependencies?.packages?.affected?.length >= 2, 'JOURNAL_BINDING_FAILED', 'persisted journal missing dependency plan/committed state');

const updatePlan = await stack.planWithDependencies('update', manifest());
const removePlan = await stack.planWithDependencies('remove', manifest());
assert(updatePlan.dependencies?.operation === 'update', 'UPDATE_PLAN_MISSING', 'dependency-aware update plan missing');
assert(removePlan.dependencies?.operation === 'remove' && removePlan.dependencies.packages.affected.includes('cowsay'), 'REMOVE_PLAN_MISSING', 'dependency-aware remove plan missing');

// Simulate the difficult crash class: APT completes the mutation, but the caller loses the
// acknowledgement before execution evidence can be persisted. The original service must fail
// closed into failed-needs-recovery; a fresh recovery service may only reconcile read-only state.
const interruptedExecutionEvents = [];
const acknowledgementLossExecutor = {
  async execute(request) {
    const { command } = validatePackageExecutorRequest(request);
    assert(request.manager === 'apt' && request.operation === 'remove', 'UNEXPECTED_RECOVERY_FIXTURE_OPERATION', 'recovery fixture must be an APT remove');
    const result = run('/usr/bin/apt-get', ['-y', ...command.slice(1)], { timeout: 300_000 });
    interruptedExecutionEvents.push({ command, exitCode: result.exitCode });
    assert(result.exitCode === 0, 'APT_INTERRUPTED_FIXTURE_MUTATION_FAILED', result.stderr.slice(0, 1000) || 'APT remove fixture failed');
    const error = new Error('simulated process interruption after successful APT mutation');
    error.code = 'E2E_ACKNOWLEDGEMENT_LOST';
    throw error;
  }
};
const interruptedService = new SystemPackageTransactionService({
  journalDirectory, executor: acknowledgementLossExecutor, authorizationBroker, trustVerifier,
  snapshotProvider: new DistributionPackageSnapshotProvider(), healthVerifier: new NativePackageHealthVerifier(),
  allowlistedRepositories, idFactory: () => 'apt-image-e2e-0002'
});
const interruptedStack = new SystemPackageStack({ provider, transactionService: interruptedService, securityBoundary, dependencyResolver });
let interruptedError = null;
try {
  await interruptedStack.execute('remove', manifest(), { reason: 'simulate post-APT acknowledgement loss' });
} catch (error) {
  interruptedError = error;
}
assert(interruptedError?.code === 'E2E_ACKNOWLEDGEMENT_LOST', 'INTERRUPTION_NOT_OBSERVED', 'fault injection must surface lost APT acknowledgement');
assert(interruptedExecutionEvents.length === 1, 'INTERRUPTED_MUTATION_COUNT', 'exactly one interrupted APT mutation expected');
const interruptedBeforeRecovery = interruptedService.readJournal('apt-image-e2e-0002');
assert(interruptedBeforeRecovery.state === 'failed-needs-recovery', 'INTERRUPTED_STATE_NOT_DURABLE', 'interrupted transaction must persist failed-needs-recovery');
assert(interruptedBeforeRecovery.snapshot?.installed === true, 'INTERRUPTED_PRESTATE_MISSING', 'interrupted remove must persist installed pre-state');
const afterInterruptedMutation = run('/usr/bin/dpkg-query', ['-W', '-f=${Status}\t${Version}\n', 'cowsay']);
assert(afterInterruptedMutation.exitCode !== 0, 'INTERRUPTED_MUTATION_NOT_APPLIED', 'fault injection requires the APT mutation to have completed before acknowledgement loss');

const recoveryService = new AptInterruptedTransactionRecoveryService({
  journalDirectory,
  authorizationBroker,
  snapshotProvider: new DistributionPackageSnapshotProvider(),
  healthVerifier: new NativePackageHealthVerifier(),
  consistencyProbe: new AptDatabaseConsistencyProbe(),
  allowlistedRepositories
});
const recoveryOutcomes = await recoveryService.recoverPending({ reason: 'contained Debian image recovery E2E' });
const recoveryOutcome = recoveryOutcomes.find(item => item.id === 'apt-image-e2e-0002');
assert(recoveryOutcome?.status === 'committed' && recoveryOutcome.reconciled === true, 'RECOVERY_NOT_RECONCILED', 'interrupted APT transaction was not safely reconciled');
assert(recoveryOutcome.mutationPerformed === false, 'RECOVERY_MUTATED_PACKAGES', 'recovery must not perform an inverse APT mutation');
const recovered = recoveryService.readJournal('apt-image-e2e-0002');
assert(recovered.state === 'committed', 'RECOVERY_JOURNAL_NOT_COMMITTED', 'reconciled journal must reach committed');
assert(recovered.recovery?.reconciliation?.schema === 'swir.apt-interrupted-recovery/0.1', 'RECOVERY_EVIDENCE_MISSING', 'journal must contain recovery evidence');
assert(recovered.recovery.reconciliation.commitSafe === true, 'RECOVERY_NOT_COMMIT_SAFE', 'recovery evidence must prove commit-safe state');
assert(recovered.recovery.reconciliation.packageMutationPerformedByRecovery === false, 'RECOVERY_MUTATION_CLAIM', 'recovery evidence must prove no package mutation');
assert(recovered.recovery.reconciliation.desiredStateReached === true, 'RECOVERY_TARGET_NOT_VERIFIED', 'recovery must prove the intended remove state');
assert(recovered.recovery.reconciliation.consistency?.healthy === true, 'PACKAGE_DATABASE_NOT_HEALTHY', 'dpkg/APT database consistency must pass');
assert(recovered.recovery.reconciliation.consistency.checks?.some(check => check.id === 'dpkg-audit' && check.ok === true), 'DPKG_AUDIT_NOT_PROVEN', 'dpkg --audit must pass');
assert(recovered.recovery.reconciliation.consistency.checks?.some(check => check.id === 'apt-get-check' && check.ok === true), 'APT_CHECK_NOT_PROVEN', 'apt-get check must pass');
const recoveryAuthorization = authorizationEvents.find(event => event.scope === 'packages.recover');
assert(recoveryAuthorization?.planDigest === recovered.planDigest, 'RECOVERY_AUTHORIZATION_NOT_BOUND', 'recovery authorization must bind the exact original plan digest');

const evidence = {
  schema: 'swir.system-package-manager-image-e2e/0.2', generatedAt: new Date().toISOString(), selectedBase: 'debian-13-trixie', distribution: { id: os.ID, version: os.VERSION_ID },
  packageManager: 'apt', fixturePackage: 'cowsay', aptBinary: aptFile, dpkgQueryBinary: dpkgFile, dpkgAdminBinary: dpkgAdminFile, repositoryPolicy: policyFile, repositoryId: 'debian-main',
  repositorySignaturesRequired: true, arbitraryRepositoryUrlsAllowed: false, dependencyResolutionMode: 'apt-get-simulation', dependencyAffectedPackages: record.plan.dependencies.packages.affected,
  dependencyClosureObserved: record.plan.dependencies.packages.affected.length >= 2, dependencyPlanPersistedBeforeMutation: persisted.plan?.dependencies?.schema === 'swir.apt-dependency-plan/0.1',
  mutationAuthorized: authorizationEvents.some(event => event.scope === 'packages.mutate'), authorizationHarness: 'contained-ci-root', packageMutationPerformed: true, preMutationInstalled: record.snapshot.installed,
  transactionState: record.state, journalMode: journalStat.mode & 0o777, journalCommitted: persisted.state === 'committed', nativeHealthVerified: record.health.healthy,
  installVerified: afterInstall.exitCode === 0, updatePlanVerified: updatePlan.dependencies?.operation === 'update', removePlanVerified: removePlan.dependencies?.operation === 'remove',
  interruptedTransactionRecoveryProven: recovered.state === 'committed', interruptedStateBeforeRecovery: interruptedBeforeRecovery.state, recoveredTransactionState: recovered.state,
  recoveryAuthorizationBound: recoveryAuthorization?.planDigest === recovered.planDigest, recoveryNoPackageMutation: recovered.recovery.reconciliation.packageMutationPerformedByRecovery === false,
  desiredStateVerifiedDuringRecovery: recovered.recovery.reconciliation.desiredStateReached === true, dpkgAuditClean: recovered.recovery.reconciliation.consistency.checks.some(check => check.id === 'dpkg-audit' && check.ok === true),
  aptCheckClean: recovered.recovery.reconciliation.consistency.checks.some(check => check.id === 'apt-get-check' && check.ok === true), failClosedRecoveryMode: 'read-only-state-reconciliation',
  passed: true
};
const output = path.resolve(args.output || '/tmp/system-package-manager-image-e2e.json');
fs.mkdirSync(path.dirname(output), { recursive: true, mode: 0o700 });
fs.writeFileSync(output, `${JSON.stringify(evidence, null, 2)}\n`, { mode: 0o600 });
console.log(JSON.stringify({ passed: true, affected: evidence.dependencyAffectedPackages, transactionState: record.state, recoveryState: recovered.state }));
