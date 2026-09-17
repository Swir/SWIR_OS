import fs from 'node:fs';
import { spawn } from 'node:child_process';

const PACKAGE_NAME = /^[A-Za-z0-9][A-Za-z0-9+._:@-]{0,127}$/;
const OPERATIONS = new Set(['install', 'update', 'remove']);
const SAFE_ENVIRONMENT = Object.freeze({
  PATH: '/usr/sbin:/usr/bin:/sbin:/bin',
  LANG: 'C.UTF-8',
  LC_ALL: 'C.UTF-8',
  DEBIAN_FRONTEND: 'noninteractive'
});

function fail(code, message) {
  const error = new Error(message);
  error.name = 'AptDependencyResolverError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function unique(values) {
  return [...new Set(values)];
}

function simulationArgs(operation, packageName) {
  assert(OPERATIONS.has(operation), 'UNSUPPORTED_OPERATION', 'unsupported apt dependency operation');
  assert(typeof packageName === 'string' && PACKAGE_NAME.test(packageName), 'INVALID_PACKAGE_NAME', 'invalid apt package name');
  if (operation === 'install') return ['-s', 'install', '--', packageName];
  if (operation === 'update') return ['-s', 'install', '--only-upgrade', '--', packageName];
  return ['-s', 'remove', '--', packageName];
}

function assertTrustedExecutable(filePath, statSync = fs.statSync) {
  const stat = statSync(filePath);
  assert(stat?.isFile?.() === true, 'APT_NOT_FILE', 'apt-get must be a regular file');
  if (Number.isInteger(stat.uid)) assert(stat.uid === 0, 'APT_NOT_ROOT_OWNED', 'apt-get must be root-owned');
  if (Number.isInteger(stat.mode)) assert((stat.mode & 0o022) === 0, 'APT_WRITABLE_BY_NON_ROOT', 'apt-get must not be group/world writable');
}

function defaultRunner(file, args, { timeoutMs = 60_000, maxOutputBytes = 1024 * 1024 } = {}) {
  return new Promise((resolve, reject) => {
    const child = spawn(file, args, {
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { ...SAFE_ENVIRONMENT }
    });
    let stdout = '';
    let stderr = '';
    let bytes = 0;
    let settled = false;
    const finish = (fn, value) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      fn(value);
    };
    const collect = (kind, chunk) => {
      const text = Buffer.isBuffer(chunk) ? chunk.toString('utf8') : String(chunk);
      bytes += Buffer.byteLength(text);
      if (bytes > maxOutputBytes) {
        child.kill('SIGKILL');
        finish(reject, Object.assign(new Error('apt simulation output limit exceeded'), { code: 'APT_SIMULATION_OUTPUT_LIMIT' }));
        return;
      }
      if (kind === 'stdout') stdout += text;
      else stderr += text;
    };
    child.stdout?.on('data', chunk => collect('stdout', chunk));
    child.stderr?.on('data', chunk => collect('stderr', chunk));
    child.on('error', error => finish(reject, error));
    child.on('close', (exitCode, signal) => finish(resolve, { exitCode, signal: signal || null, stdout, stderr }));
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      finish(reject, Object.assign(new Error('apt simulation timed out'), { code: 'APT_SIMULATION_TIMEOUT' }));
    }, timeoutMs);
    timer.unref?.();
  });
}

export function parseAptSimulation(output) {
  const install = [];
  const remove = [];
  const configure = [];
  for (const rawLine of String(output || '').split(/\r?\n/)) {
    const line = rawLine.trim();
    let match = line.match(/^Inst\s+([^\s:]+(?::[^\s]+)?)(?:\s|$)/);
    if (match) {
      install.push(match[1]);
      continue;
    }
    match = line.match(/^Remv\s+([^\s:]+(?::[^\s]+)?)(?:\s|$)/);
    if (match) {
      remove.push(match[1]);
      continue;
    }
    match = line.match(/^Conf\s+([^\s:]+(?::[^\s]+)?)(?:\s|$)/);
    if (match) configure.push(match[1]);
  }
  return {
    install: unique(install),
    remove: unique(remove),
    configure: unique(configure),
    affected: unique([...install, ...remove, ...configure])
  };
}

export function validateAptDependencyPlan(plan, { operation, packageName } = {}) {
  assert(plan && typeof plan === 'object' && !Array.isArray(plan), 'INVALID_DEPENDENCY_PLAN', 'dependency plan must be an object');
  assert(plan.schema === 'swir.apt-dependency-plan/0.1', 'INVALID_DEPENDENCY_PLAN_SCHEMA', 'unsupported apt dependency plan schema');
  assert(plan.manager === 'apt', 'INVALID_DEPENDENCY_MANAGER', 'dependency plan manager must be apt');
  assert(plan.operation === operation, 'DEPENDENCY_OPERATION_MISMATCH', 'dependency plan operation mismatch');
  assert(plan.packageName === packageName, 'DEPENDENCY_PACKAGE_MISMATCH', 'dependency plan package mismatch');
  assert(plan.simulation === true && plan.mutationPerformed === false, 'DEPENDENCY_PLAN_MUTATED', 'dependency resolution must remain simulation-only');
  assert(plan.repositorySignatureVerificationBypassed === false, 'DEPENDENCY_PLAN_UNSAFE_TRUST', 'dependency resolution may not bypass repository signatures');
  for (const key of ['install', 'remove', 'configure', 'affected']) {
    assert(Array.isArray(plan.packages?.[key]), 'INVALID_DEPENDENCY_PACKAGES', `dependency plan packages.${key} must be an array`);
    assert(plan.packages[key].every(value => typeof value === 'string' && value.length > 0), 'INVALID_DEPENDENCY_PACKAGES', `dependency plan packages.${key} contains invalid values`);
  }
  return plan;
}

export class AptDependencyResolver {
  #aptGetPath;
  #runner;
  #statSync;
  #timeoutMs;
  #maxOutputBytes;

  constructor({
    aptGetPath = '/usr/bin/apt-get',
    runner = defaultRunner,
    statSync = fs.statSync,
    timeoutMs = 60_000,
    maxOutputBytes = 1024 * 1024
  } = {}) {
    assert(typeof aptGetPath === 'string' && aptGetPath.startsWith('/'), 'APT_PATH_REQUIRED', 'apt-get path must be absolute');
    assert(typeof runner === 'function', 'INVALID_RUNNER', 'apt dependency runner must be a function');
    assert(Number.isInteger(timeoutMs) && timeoutMs >= 1000 && timeoutMs <= 5 * 60_000, 'INVALID_TIMEOUT', 'apt dependency timeout outside policy bounds');
    assert(Number.isInteger(maxOutputBytes) && maxOutputBytes >= 4096 && maxOutputBytes <= 8 * 1024 * 1024, 'INVALID_OUTPUT_LIMIT', 'apt dependency output limit outside policy bounds');
    this.#aptGetPath = aptGetPath;
    this.#runner = runner;
    this.#statSync = statSync;
    this.#timeoutMs = timeoutMs;
    this.#maxOutputBytes = maxOutputBytes;
  }

  async resolve({ operation, packageName } = {}) {
    const args = simulationArgs(operation, packageName);
    assertTrustedExecutable(this.#aptGetPath, this.#statSync);
    const result = await this.#runner(this.#aptGetPath, args, {
      timeoutMs: this.#timeoutMs,
      maxOutputBytes: this.#maxOutputBytes
    });
    assert(result && Number.isInteger(result.exitCode), 'INVALID_APT_RESULT', 'apt dependency runner returned invalid result');
    if (result.exitCode !== 0) {
      const error = new Error(`apt dependency simulation exited with code ${result.exitCode}`);
      error.name = 'AptDependencyResolverError';
      error.code = 'APT_SIMULATION_FAILED';
      error.exitCode = result.exitCode;
      error.stderr = String(result.stderr || '').slice(0, 4096);
      throw error;
    }
    const packages = parseAptSimulation(result.stdout);
    return validateAptDependencyPlan({
      schema: 'swir.apt-dependency-plan/0.1',
      manager: 'apt',
      operation,
      packageName,
      simulation: true,
      mutationPerformed: false,
      repositorySignatureVerificationBypassed: false,
      command: ['apt-get', ...args],
      packages,
      exitCode: 0,
      signal: result.signal || null
    }, { operation, packageName });
  }
}

export const AptDependencyResolverPolicy = Object.freeze({
  schema: 'swir.apt-dependency-plan/0.1',
  manager: 'apt',
  simulationOnly: true,
  shell: false,
  inheritedEnvironment: false,
  rootOwnedExecutableRequired: true,
  groupWorldWritableExecutableForbidden: true,
  arbitraryRepositoryUrls: false,
  repositorySignatureVerificationBypassed: false
});
