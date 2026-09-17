import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { DistributionPackageProvider } from '../packages/distribution-package-provider.mjs';
import { AptDependencyResolver } from '../packages/apt-dependency-resolver.mjs';
import { SystemPackageTransactionService } from '../packages/package-transaction-service.mjs';
import { DistributionPackageSnapshotProvider, NativePackageHealthVerifier } from '../packages/distribution-package-state.mjs';
import { SystemPackageStack } from '../packages/system-package-stack.mjs';
import { validatePackageExecutorRequest } from '../packages/privileged-package-executor.mjs';

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
    return { authorized: true, grantId: 'ci-contained-root-grant', actorId: 'ci-root-contained' };
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

const after = run('/usr/bin/dpkg-query', ['-W', '-f=${Status}\t${Version}\n', 'cowsay']);
assert(after.exitCode === 0 && /^install ok installed\t/m.test(after.stdout), 'PACKAGE_NOT_INSTALLED', 'cowsay must be installed after transaction');
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

const evidence = {
  schema: 'swir.system-package-manager-image-e2e/0.1', generatedAt: new Date().toISOString(), selectedBase: 'debian-13-trixie', distribution: { id: os.ID, version: os.VERSION_ID },
  packageManager: 'apt', fixturePackage: 'cowsay', aptBinary: aptFile, dpkgQueryBinary: dpkgFile, repositoryPolicy: policyFile, repositoryId: 'debian-main',
  repositorySignaturesRequired: true, arbitraryRepositoryUrlsAllowed: false, dependencyResolutionMode: 'apt-get-simulation', dependencyAffectedPackages: record.plan.dependencies.packages.affected,
  dependencyClosureObserved: record.plan.dependencies.packages.affected.length >= 2, dependencyPlanPersistedBeforeMutation: persisted.plan?.dependencies?.schema === 'swir.apt-dependency-plan/0.1',
  mutationAuthorized: authorizationEvents.length === 1, authorizationHarness: 'contained-ci-root', packageMutationPerformed: true, preMutationInstalled: record.snapshot.installed,
  transactionState: record.state, journalMode: journalStat.mode & 0o777, journalCommitted: persisted.state === 'committed', nativeHealthVerified: record.health.healthy,
  installVerified: after.exitCode === 0, updatePlanVerified: updatePlan.dependencies?.operation === 'update', removePlanVerified: removePlan.dependencies?.operation === 'remove',
  interruptedUpdateRecoveryProven: false, passed: true
};
const output = path.resolve(args.output || '/tmp/system-package-manager-image-e2e.json');
fs.mkdirSync(path.dirname(output), { recursive: true, mode: 0o700 });
fs.writeFileSync(output, `${JSON.stringify(evidence, null, 2)}\n`, { mode: 0o600 });
console.log(JSON.stringify({ passed: true, affected: evidence.dependencyAffectedPackages, transactionState: record.state }));
