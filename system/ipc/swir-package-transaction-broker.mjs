#!/usr/bin/env node
import fs from 'node:fs';
import net from 'node:net';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';

import { DistributionPackageProvider } from '../packages/distribution-package-provider.mjs';
import { SystemPackageTransactionService, digestPackagePlan } from '../packages/package-transaction-service.mjs';
import { GuardedPkexecPackageExecutor } from '../packages/privileged-package-executor.mjs';
import { DistributionPackageSnapshotProvider, NativePackageHealthVerifier } from '../packages/distribution-package-state.mjs';
import { AptDependencyResolver } from '../packages/apt-dependency-resolver.mjs';
import { SystemPackageStack } from '../packages/system-package-stack.mjs';
import { createPeerAuthorizedSystemPackageSecurityBoundary } from '../security/peer-package-security-boundary.mjs';

const REQUEST_SCHEMA = 'swir.package-transaction-broker-request/0.1';
const RESPONSE_SCHEMA = 'swir.package-transaction-broker-response/0.1';
const DEFAULT_SOCKET = '/run/swir/package-transaction.sock';
const DEFAULT_JOURNAL = '/var/lib/swir/package-transactions';
const DEFAULT_REPOSITORY_POLICY = '/etc/swir/repository-trust-policy.json';
const MAX_WIRE_BYTES = 64 * 1024;
const PACKAGE_NAME = /^[A-Za-z0-9][A-Za-z0-9+._:@-]{0,127}$/;
const OPERATIONS = new Set(['install', 'update', 'remove']);
const ALLOWED_REQUEST_KEYS = Object.freeze({
  preview: new Set(['schema', 'action', 'operation', 'packageName']),
  commit: new Set(['schema', 'action', 'operation', 'packageName', 'peerAuthorizationEnvelope'])
});

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'PackageTransactionBrokerError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function isObject(value) {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function clone(value) {
  return JSON.parse(JSON.stringify(value));
}

function validateRequest(input) {
  assert(isObject(input), 'INVALID_REQUEST', 'package broker request must be an object');
  assert(input.schema === REQUEST_SCHEMA, 'INVALID_REQUEST_SCHEMA', `request schema must be ${REQUEST_SCHEMA}`);
  assert(input.action === 'preview' || input.action === 'commit', 'INVALID_ACTION', 'action must be preview or commit');
  assert(OPERATIONS.has(input.operation), 'INVALID_OPERATION', 'unsupported package operation');
  assert(typeof input.packageName === 'string' && PACKAGE_NAME.test(input.packageName), 'INVALID_PACKAGE_NAME', 'invalid package name');
  const allowed = ALLOWED_REQUEST_KEYS[input.action];
  for (const key of Object.keys(input)) assert(allowed.has(key), 'UNEXPECTED_REQUEST_FIELD', `unexpected request field: ${key}`);
  if (input.action === 'commit') {
    assert(isObject(input.peerAuthorizationEnvelope), 'PEER_AUTHORIZATION_REQUIRED', 'commit requires a peer authorization envelope');
  }
  return Object.freeze({
    schema: REQUEST_SCHEMA,
    action: input.action,
    operation: input.operation,
    packageName: input.packageName,
    ...(input.action === 'commit' ? { peerAuthorizationEnvelope: clone(input.peerAuthorizationEnvelope) } : {})
  });
}

function manifestForPackage(packageName) {
  return Object.freeze({
    schema: 'swir.package-provider/0.2',
    id: `system:${packageName}`,
    targetEditions: ['system'],
    executionClass: 'linux-native',
    provider: 'swir.package.system',
    package: { sourceRef: packageName, nativeEntryPoint: null },
    trust: {
      sourceClass: 'distribution-repository',
      signatureRequired: true,
      repositoryId: null
    }
  });
}

function summarizePlan(plan) {
  return Object.freeze({
    planDigest: digestPackagePlan(plan),
    packageId: plan.package.id,
    packageName: plan.package.sourceRef,
    operation: plan.operation,
    packageManager: plan.host.packageManager,
    repositoryId: plan.source.repositoryId,
    commandPreview: [...plan.commandPreview],
    dependencyResolution: plan.dependencies?.schema || null,
    autoExecutable: false,
    requiresPrivilege: true,
    journalRequired: true
  });
}

export class PackageTransactionBroker {
  #stack;
  constructor({ stack } = {}) {
    assert(stack && typeof stack.planWithDependencies === 'function' && typeof stack.execute === 'function', 'PACKAGE_STACK_REQUIRED', 'package stack with preview and execute is required');
    this.#stack = stack;
  }

  async handle(rawRequest) {
    const request = validateRequest(rawRequest);
    const manifest = manifestForPackage(request.packageName);
    if (request.action === 'preview') {
      const plan = await this.#stack.planWithDependencies(request.operation, manifest);
      return Object.freeze({
        schema: RESPONSE_SCHEMA,
        ok: true,
        action: 'preview',
        preview: summarizePlan(plan)
      });
    }

    const transaction = await this.#stack.execute(request.operation, manifest, {
      peerAuthorizationEnvelope: request.peerAuthorizationEnvelope,
      allowUserInteraction: true
    });
    return Object.freeze({
      schema: RESPONSE_SCHEMA,
      ok: true,
      action: 'commit',
      transaction: {
        id: transaction.id,
        state: transaction.state,
        planDigest: transaction.planDigest,
        packageId: transaction.plan?.package?.id || `system:${request.packageName}`,
        packageName: request.packageName,
        operation: request.operation
      }
    });
  }
}

export function createProductionPackageBroker({
  journalDirectory = DEFAULT_JOURNAL,
  repositoryPolicyPath = DEFAULT_REPOSITORY_POLICY,
  peerGrantOptions
} = {}) {
  const host = Object.freeze({
    distribution: { id: 'debian', family: 'debian' },
    capabilities: { packageManagers: ['apt'] }
  });
  const security = createPeerAuthorizedSystemPackageSecurityBoundary({ repositoryPolicyPath, peerGrantOptions });
  const provider = new DistributionPackageProvider({ host, allowlistedRepositories: security.allowlistedRepositories });
  const transactions = new SystemPackageTransactionService({
    journalDirectory,
    executor: new GuardedPkexecPackageExecutor(),
    authorizationBroker: security.authorizationBroker,
    trustVerifier: security.trustVerifier,
    snapshotProvider: new DistributionPackageSnapshotProvider(),
    healthVerifier: new NativePackageHealthVerifier(),
    allowlistedRepositories: security.allowlistedRepositories
  });
  return new PackageTransactionBroker({
    stack: new SystemPackageStack({
      provider,
      transactionService: transactions,
      securityBoundary: security,
      dependencyResolver: new AptDependencyResolver()
    })
  });
}

function safeError(error) {
  return {
    schema: RESPONSE_SCHEMA,
    ok: false,
    error: {
      code: typeof error?.code === 'string' ? error.code : 'PACKAGE_BROKER_FAILED',
      message: typeof error?.message === 'string' ? error.message.slice(0, 300) : 'package transaction broker failed closed'
    }
  };
}

function ensureSocketParent(socketPath, testMode) {
  assert(typeof socketPath === 'string' && path.isAbsolute(socketPath), 'SOCKET_PATH_INVALID', 'socket path must be absolute');
  const parent = path.dirname(socketPath);
  fs.mkdirSync(parent, { recursive: true, mode: 0o755 });
  const stat = fs.lstatSync(parent);
  assert(stat.isDirectory() && !stat.isSymbolicLink(), 'SOCKET_PARENT_UNSAFE', 'socket parent must be a real directory');
  const expectedUid = testMode ? process.geteuid?.() : 0;
  if (Number.isInteger(expectedUid) && Number.isInteger(stat.uid)) assert(stat.uid === expectedUid, 'SOCKET_PARENT_OWNER_INVALID', 'socket parent owner is invalid');
  assert((stat.mode & 0o022) === 0, 'SOCKET_PARENT_MODE_INVALID', 'socket parent must not be group/world writable');
}

function removeTrustedStaleSocket(socketPath, testMode) {
  try {
    const stat = fs.lstatSync(socketPath);
    const expectedUid = testMode ? process.geteuid?.() : 0;
    assert(stat.isSocket() && !stat.isSymbolicLink(), 'STALE_SOCKET_UNTRUSTED', 'refusing to replace a non-socket package broker path');
    if (Number.isInteger(expectedUid) && Number.isInteger(stat.uid)) assert(stat.uid === expectedUid, 'STALE_SOCKET_OWNER_INVALID', 'refusing to replace a foreign package broker socket');
    fs.unlinkSync(socketPath);
  } catch (error) {
    if (error?.code !== 'ENOENT') throw error;
  }
}

export async function servePackageBroker({ broker, socketPath = DEFAULT_SOCKET, testMode = false, once = false } = {}) {
  assert(broker && typeof broker.handle === 'function', 'BROKER_REQUIRED', 'broker.handle is required');
  if (!testMode) assert(typeof process.geteuid === 'function' && process.geteuid() === 0, 'PRODUCTION_REQUIRES_ROOT', 'production package transaction broker must run as root');
  ensureSocketParent(socketPath, testMode);
  removeTrustedStaleSocket(socketPath, testMode);

  let served = 0;
  const server = net.createServer(socket => {
    let buffer = Buffer.alloc(0);
    let answered = false;
    const respond = value => {
      if (answered) return;
      answered = true;
      let wire = `${JSON.stringify(value)}\n`;
      if (Buffer.byteLength(wire) > MAX_WIRE_BYTES) wire = `${JSON.stringify(safeError(Object.assign(new Error('response too large'), { code: 'RESPONSE_TOO_LARGE' })))}\n`;
      socket.end(wire);
      served += 1;
      if (once && served >= 1) server.close();
    };
    socket.setTimeout(45_000, () => respond(safeError(Object.assign(new Error('request timed out'), { code: 'REQUEST_TIMEOUT' }))));
    socket.on('data', chunk => {
      if (answered) return;
      buffer = Buffer.concat([buffer, chunk]);
      if (buffer.length > MAX_WIRE_BYTES) return respond(safeError(Object.assign(new Error('request too large'), { code: 'REQUEST_TOO_LARGE' })));
      const newline = buffer.indexOf(0x0a);
      if (newline < 0) return;
      const trailing = buffer.subarray(newline + 1).toString('utf8');
      if (trailing.trim()) return respond(safeError(Object.assign(new Error('one request per connection'), { code: 'MULTIPLE_REQUESTS_FORBIDDEN' })));
      let parsed;
      try { parsed = JSON.parse(buffer.subarray(0, newline).toString('utf8')); }
      catch { return respond(safeError(Object.assign(new Error('request is not valid JSON'), { code: 'REQUEST_JSON_INVALID' }))); }
      Promise.resolve(broker.handle(parsed)).then(respond, error => respond(safeError(error)));
    });
    socket.on('error', () => {});
  });
  server.maxConnections = 32;

  await new Promise((resolve, reject) => {
    server.once('error', reject);
    server.listen(socketPath, () => {
      try { fs.chmodSync(socketPath, 0o666); resolve(); }
      catch (error) { reject(error); }
    });
  });

  const cleanup = () => {
    try { server.close(); } catch {}
    try {
      const stat = fs.lstatSync(socketPath);
      if (stat.isSocket()) fs.unlinkSync(socketPath);
    } catch {}
  };
  process.once('SIGTERM', cleanup);
  process.once('SIGINT', cleanup);
  return server;
}

async function main() {
  const testMode = process.env.SWIR_PACKAGE_BROKER_TEST_MODE === '1';
  const socketPath = process.env.SWIR_PACKAGE_BROKER_SOCKET || DEFAULT_SOCKET;
  const broker = createProductionPackageBroker();
  const server = await servePackageBroker({ broker, socketPath, testMode });
  await new Promise(resolve => server.once('close', resolve));
}

const direct = process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);
if (direct) {
  main().catch(error => {
    console.error(`${error?.code || 'PACKAGE_BROKER_START_FAILED'}: ${error?.message || error}`);
    process.exitCode = 2;
  });
}

export const PackageTransactionBrokerPolicy = Object.freeze({
  schema: REQUEST_SCHEMA,
  transport: 'unix-stream-json-line',
  socketPath: DEFAULT_SOCKET,
  callerSuppliedUnixIdentity: false,
  peerAuthorizationEnvelopeRequiredForCommit: true,
  interactivePolkitRequiredForCommit: true,
  planRecomputedBeforeCommit: true,
  oneRequestPerConnection: true,
  directPackageToolInvocationByUi: false,
  arbitraryRepositoryInputAllowed: false,
  arbitraryCommandInputAllowed: false,
  maxWireBytes: MAX_WIRE_BYTES
});
