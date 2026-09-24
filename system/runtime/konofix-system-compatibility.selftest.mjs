import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { EventEmitter } from 'node:events';
import {
  KonofixSystemCompatibilityAdapter,
  KonofixSystemCompatibilityIdentity,
  KonofixSystemCompatibilityPolicy,
  createKonofixSystemManifest,
  validateKonofixSystemInstallEvidence
} from './konofix-system-compatibility.mjs';
import { WindowsCompatibilityService, managedPrefixPath, prepareManagedPrefix } from './windows-compatibility-service.mjs';

const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-konofix-system-'));
const prefixRoot = path.join(temp, 'prefixes');
const prefix = managedPrefixPath(KonofixSystemCompatibilityIdentity.appId, { prefixRoot });
const executable = path.join(prefix, 'drive_c', 'users', 'swir', 'AppData', 'Local', 'Konofix Chat', 'konofix-chat.exe');
fs.mkdirSync(path.dirname(executable), { recursive: true });
fs.writeFileSync(executable, Buffer.from('MZ\0synthetic-konofix-user-application'));
const executableSha256 = crypto.createHash('sha256').update(fs.readFileSync(executable)).digest('hex');

const evidence = {
  schema: 'swir.konofix-system-install/0.1',
  upstreamRepository: 'Swir/Konofix',
  version: '0.5.1',
  sourceCommit: '31298cc732c97ff90230c3743cd1c3be17f40b6c',
  installerSha256: '9d0ae79d32d49272ec597cfaae19023a5d0a3a1c8dc23d622b987bb2bc250de6',
  installerVerified: true,
  explicitInstallApproved: true,
  legacyDataImported: false,
  installedExecutable: executable,
  installedExecutableSha256: executableSha256
};

assert.equal(KonofixSystemCompatibilityPolicy.packageTrustVerifiedRequired, true);
assert.equal(KonofixSystemCompatibilityPolicy.explicitInstallApprovalRequired, true);
assert.equal(KonofixSystemCompatibilityPolicy.explicitLaunchApprovalRequired, true);
assert.equal(KonofixSystemCompatibilityPolicy.silentLegacyDataImportAllowed, false);
assert.equal(KonofixSystemCompatibilityPolicy.nativeLinuxGuiQualified, false);
assert.equal(KonofixSystemCompatibilityPolicy.protonQualified, false);
assert.equal(KonofixSystemCompatibilityPolicy.realPeerInteroperabilityQualified, false);

const verified = validateKonofixSystemInstallEvidence(evidence, { prefixRoot });
assert.equal(verified.executable, fs.realpathSync(executable));
assert.equal(verified.executableSha256, executableSha256);
const manifest = createKonofixSystemManifest(evidence, { prefixRoot });
assert.equal(manifest.id, 'info.swir.konofixchat');
assert.equal(manifest.executionClass, 'windows-compat');
assert.equal(manifest.provider, 'swir.compat.wine');
assert.equal(manifest.package.sourceRef, KonofixSystemCompatibilityIdentity.sourceCommit);
assert.equal(manifest.package.sha256, executableSha256);
assert.equal(manifest.trust.sourceClass, 'swir-signed');
assert.equal(manifest.trust.repositoryId, 'official');
assert.equal(manifest.trust.signatureRequired, true);
assert.deepEqual(Object.keys(manifest.trust).sort(), ['repositoryId', 'signatureRequired', 'sourceClass']);

prepareManagedPrefix(manifest, { trustVerified: true, prefixRoot });
const runtimeRoot = path.join(temp, 'runtimes');
fs.mkdirSync(runtimeRoot, { recursive: true });
const runtime = path.join(runtimeRoot, 'wine');
fs.writeFileSync(runtime, '#!/bin/sh\nexit 0\n', { mode: 0o755 });

let captured = null;
class FakeChild extends EventEmitter {
  constructor() { super(); this.pid = 5150; }
  kill() { return true; }
}
const child = new FakeChild();
const service = new WindowsCompatibilityService({
  prefixRoot,
  runtimePaths: { 'swir.compat.wine': runtime },
  runtimeRoots: [runtimeRoot],
  spawnImpl(command, args, options) { captured = { command, args, options }; return child; }
});
const adapter = new KonofixSystemCompatibilityAdapter({ stack: service, prefixRoot });
const plan = adapter.plan(evidence, {
  packageTrustVerified: true,
  environment: { PATH: '/usr/bin', LANG: 'en_US.UTF-8', LD_PRELOAD: '/tmp/evil.so', NODE_OPTIONS: '--require evil' }
});
assert.equal(plan.application.executable, fs.realpathSync(executable));
assert.equal(plan.runtime.family, 'wine');
assert.equal(plan.environment.WINEPREFIX, fs.realpathSync(prefix));
assert.equal('LD_PRELOAD' in plan.environment, false);
assert.equal('NODE_OPTIONS' in plan.environment, false);
assert.equal(plan.shell, false);
assert.equal(plan.brokerRequired, true);
assert.throws(() => adapter.plan(evidence), error => error.code === 'PACKAGE_TRUST_REQUIRED');
assert.throws(() => adapter.launch(evidence, { packageTrustVerified: true }), error => error.code === 'USER_APPROVAL_REQUIRED');
const started = adapter.launch(evidence, { packageTrustVerified: true, userApprovedLaunch: true });
assert.equal(started.state, 'running');
assert.equal(started.pid, 5150);
assert.equal(captured.command, fs.realpathSync(runtime));
assert.equal(captured.options.shell, false);
child.emit('exit', 0, null);

for (const [field, value, code] of [
  ['upstreamRepository', 'Other/Konofix', 'UNSUPPORTED_UPSTREAM'],
  ['version', '0.5.2', 'UNSUPPORTED_VERSION'],
  ['sourceCommit', '0'.repeat(40), 'SOURCE_COMMIT_MISMATCH'],
  ['installerSha256', '0'.repeat(64), 'INSTALLER_DIGEST_MISMATCH'],
  ['installerVerified', false, 'INSTALLER_NOT_VERIFIED'],
  ['explicitInstallApproved', false, 'INSTALL_NOT_APPROVED'],
  ['legacyDataImported', true, 'LEGACY_IMPORT_FORBIDDEN'],
  ['installedExecutableSha256', '0'.repeat(64), 'EXECUTABLE_DIGEST_MISMATCH']
]) {
  assert.throws(() => validateKonofixSystemInstallEvidence({ ...evidence, [field]: value }, { prefixRoot }), error => error.code === code);
}

const outside = path.join(temp, 'outside', 'konofix-chat.exe');
fs.mkdirSync(path.dirname(outside), { recursive: true });
fs.writeFileSync(outside, 'MZ-outside');
assert.throws(() => validateKonofixSystemInstallEvidence({ ...evidence, installedExecutable: outside,
  installedExecutableSha256: crypto.createHash('sha256').update(fs.readFileSync(outside)).digest('hex') }, { prefixRoot }), error => error.code === 'EXECUTABLE_OUTSIDE_PREFIX');

const linkDir = path.join(prefix, 'drive_c', 'linked');
fs.mkdirSync(linkDir, { recursive: true });
const linked = path.join(linkDir, 'konofix-chat.exe');
try {
  fs.symlinkSync(executable, linked);
  assert.throws(() => validateKonofixSystemInstallEvidence({ ...evidence, installedExecutable: linked }, { prefixRoot }), error => error.code === 'INVALID_EXECUTABLE');
} catch (error) {
  if (error?.code !== 'EPERM' && error?.code !== 'EACCES') throw error;
}

fs.rmSync(temp, { recursive: true, force: true });
console.log('SWIR Konofix System compatibility adapter self-tests: OK');
