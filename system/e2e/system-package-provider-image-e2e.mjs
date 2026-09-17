import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { createSystemPackageStack } from '../packages/system-package-stack.mjs';
import { createSystemPackageProviderLayer, SystemPackageProviderLayerPolicy } from '../packages/package-provider-layer.mjs';

function fail(code, message) {
  const error = new Error(message);
  error.name = 'SystemPackageProviderImageE2EError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function parseArgs(argv) {
  const out = { output: null, compact: false };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--output') out.output = argv[++i] || null;
    else if (argv[i] === '--compact') out.compact = true;
    else fail('INVALID_ARGUMENT', `Unsupported argument: ${argv[i]}`);
  }
  return out;
}

function readOsRelease() {
  const values = {};
  for (const line of fs.readFileSync('/etc/os-release', 'utf8').split(/\r?\n/)) {
    const match = line.match(/^([A-Z0-9_]+)=(.*)$/);
    if (!match) continue;
    values[match[1]] = match[2].replace(/^"|"$/g, '');
  }
  return values;
}

function trustedRootFile(filePath, code) {
  const stat = fs.lstatSync(filePath);
  assert(stat.isFile() && !stat.isSymbolicLink(), code, `${filePath} must be a regular non-symlink file`);
  assert(stat.uid === 0, code, `${filePath} must be root-owned`);
  assert((stat.mode & 0o022) === 0, code, `${filePath} must not be group/world writable`);
  return { uid: stat.uid, mode: stat.mode & 0o777 };
}

function runReadOnly(command, args) {
  const result = spawnSync(command, args, {
    shell: false,
    encoding: 'utf8',
    timeout: 30_000,
    maxBuffer: 256 * 1024,
    env: { PATH: '/usr/sbin:/usr/bin:/sbin:/bin', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' }
  });
  if (result.error) throw result.error;
  return { status: result.status, stdout: String(result.stdout || ''), stderr: String(result.stderr || '') };
}

function manifest(repositoryId = 'debian-main') {
  return {
    schema: 'swir.package-provider/0.2',
    id: 'swir.e2e.bash',
    targetEditions: ['system'],
    executionClass: 'linux-native',
    provider: 'swir.package.system',
    package: {
      name: 'GNU Bourne Again Shell',
      sourceRef: 'bash',
      nativeEntryPoint: '/usr/bin/bash'
    },
    trust: {
      sourceClass: 'distribution-repository',
      repositoryId,
      signatureRequired: true
    }
  };
}

const args = parseArgs(process.argv.slice(2));
const os = readOsRelease();
assert(os.ID === 'debian', 'WRONG_DISTRIBUTION', 'System image must be Debian');
assert(/^13(?:\.|$)/.test(os.VERSION_ID || ''), 'WRONG_DISTRIBUTION_VERSION', 'System image must be Debian 13');

const aptStat = trustedRootFile('/usr/bin/apt-get', 'UNTRUSTED_APT_BINARY');
const pkcheckStat = trustedRootFile('/usr/bin/pkcheck', 'UNTRUSTED_POLKIT_BINARY');
const policyStat = trustedRootFile('/etc/swir/repository-trust-policy.json', 'UNTRUSTED_REPOSITORY_POLICY');

const aptPolicy = runReadOnly('/usr/bin/apt-cache', ['policy', 'bash']);
assert(aptPolicy.status === 0, 'APT_POLICY_FAILED', 'apt-cache policy bash failed');
assert(/bash:/m.test(aptPolicy.stdout) && /Candidate:/m.test(aptPolicy.stdout), 'APT_POLICY_EMPTY', 'apt-cache did not expose a candidate for bash');

const host = {
  distribution: { id: 'debian-13-trixie', family: 'debian', version: os.VERSION_ID },
  capabilities: { packageManagers: ['apt'] }
};
const stack = createSystemPackageStack({
  host,
  journalDirectory: '/var/lib/swir/package-transactions',
  repositoryPolicyPath: '/etc/swir/repository-trust-policy.json'
});
const layer = createSystemPackageProviderLayer({ distributionStack: stack });
const description = layer.describe();

assert(description.schema === 'swir.system-package-provider-layer/0.1', 'INVALID_LAYER_SCHEMA', 'Unexpected package layer schema');
assert(description.directCommandExecution === false, 'DIRECT_EXECUTION_ENABLED', 'Common provider layer must not execute arbitrary commands');
assert(description.arbitraryProviderRegistration === false, 'ARBITRARY_PROVIDER_REGISTRATION', 'Arbitrary provider registration must remain disabled');
assert(description.privilegedMutationDelegated === true, 'PRIVILEGE_BOUNDARY_MISSING', 'Privileged mutation must stay delegated');
assert(layer.providerState('swir.package.system').state === 'ready', 'DISTRIBUTION_PROVIDER_NOT_READY', 'Distribution provider must be provisioned');
assert(layer.providerState('swir.package.flatpak').state === 'not-provisioned', 'FLATPAK_UNEXPECTEDLY_PROVISIONED', 'Experimental Flatpak must not be silently enabled');
assert(layer.providerState('swir.package.appimage').state === 'not-provisioned', 'APPIMAGE_UNEXPECTEDLY_PROVISIONED', 'Experimental AppImage must not be silently enabled');
assert(SystemPackageProviderLayerPolicy.provisionedByProductionFactory.length === 1 && SystemPackageProviderLayerPolicy.provisionedByProductionFactory[0] === 'swir.package.system', 'PRODUCTION_PROVIDER_POLICY_CHANGED', 'Production provider factory must remain distribution-only');

const plans = {};
for (const operation of ['install', 'update', 'remove']) {
  const plan = layer.plan(operation, manifest());
  assert(plan.provider === 'swir.package.system', 'PROVIDER_MISMATCH', `${operation} plan provider mismatch`);
  assert(plan.operation === operation, 'OPERATION_MISMATCH', `${operation} plan operation mismatch`);
  assert(plan.host?.packageManager === 'apt', 'WRONG_PACKAGE_MANAGER', `${operation} must resolve to apt`);
  assert(plan.source?.repositoryId === 'debian-main', 'WRONG_REPOSITORY', `${operation} must stay bound to debian-main`);
  assert(plan.trust?.signatureVerificationRequired === true, 'SIGNATURES_NOT_REQUIRED', `${operation} must require repository signatures`);
  assert(plan.trust?.arbitraryRepositoryUrlAllowed === false, 'ARBITRARY_REPOSITORY_URL', `${operation} must reject arbitrary repository URLs`);
  assert(plan.transaction?.requiresPrivilege === true && plan.transaction?.journalRequired === true, 'TRANSACTION_BOUNDARY_MISSING', `${operation} must require privilege and a journal`);
  assert(Array.isArray(plan.commandPreview) && plan.commandPreview[0] === 'apt-get', 'INVALID_COMMAND_PREVIEW', `${operation} must resolve to apt-get`);
  assert(plan.commandPreview.includes('--'), 'MISSING_ARGV_TERMINATOR', `${operation} command preview must contain -- argument terminator`);
  plans[operation] = {
    packageManager: plan.host.packageManager,
    repositoryId: plan.source.repositoryId,
    commandPreview: plan.commandPreview,
    requiresPrivilege: plan.transaction.requiresPrivilege,
    journalRequired: plan.transaction.journalRequired,
    healthCheckRequired: plan.transaction.healthCheckRequired
  };
}

let untrustedRepositoryRejected = false;
try {
  layer.plan('install', manifest('untrusted-third-party'));
} catch {
  untrustedRepositoryRejected = true;
}
assert(untrustedRepositoryRejected, 'UNTRUSTED_REPOSITORY_ACCEPTED', 'Non-allowlisted repository must be rejected');

let windowsProviderRejected = false;
try {
  layer.plan('install', { ...manifest(), executionClass: 'windows-compat', provider: 'swir.compat.wine' });
} catch {
  windowsProviderRejected = true;
}
assert(windowsProviderRejected, 'WINDOWS_PROVIDER_ACCEPTED', 'Windows compatibility payload must not enter the Linux package layer');

const evidence = {
  schema: 'swir.system-package-provider-image-e2e/0.1',
  generatedAt: new Date().toISOString(),
  selectedBase: 'debian-13-trixie',
  distribution: { id: os.ID, version: os.VERSION_ID },
  productionProvider: 'swir.package.system',
  providerStates: Object.fromEntries(description.providers.map(item => [item.id, item.state])),
  packageManager: 'apt',
  aptBinary: aptStat,
  polkitBinary: pkcheckStat,
  repositoryPolicy: policyStat,
  aptMetadataReadable: true,
  plans,
  repositorySignaturesRequired: true,
  arbitraryRepositoryUrlsAllowed: false,
  arbitraryProviderRegistration: false,
  directCommandExecution: false,
  privilegedMutationDelegated: true,
  untrustedRepositoryRejected,
  windowsCompatibilitySeparated: windowsProviderRejected,
  experimentalProvidersProductionEnabled: false,
  packageMutationPerformed: false,
  passed: true
};

const serialized = JSON.stringify(evidence, null, args.compact ? 0 : 2);
if (args.output) {
  const output = path.resolve(args.output);
  fs.mkdirSync(path.dirname(output), { recursive: true, mode: 0o700 });
  fs.writeFileSync(output, `${serialized}\n`, { mode: 0o600 });
} else {
  process.stdout.write(`${serialized}\n`);
}
