import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const SCHEMA = 'swir.fwupd-debian13-runtime-qualification/0.1';
const MAX_TEXT_BYTES = 1024 * 1024;
const REQUIRED_FILES = Object.freeze([
  Object.freeze({ path: '/usr/bin/fwupdmgr', executable: true }),
  Object.freeze({ path: '/usr/libexec/fwupd/fwupd', executable: true }),
  Object.freeze({ path: '/etc/fwupd/remotes.d/lvfs.conf', executable: false }),
]);

function fail(code, message) {
  const error = new Error(message);
  error.name = 'FwupdDebianRuntimeQualificationError';
  error.code = code;
  throw error;
}

function assert(condition, code, message) {
  if (!condition) fail(code, message);
}

function parseOsRelease(text) {
  assert(typeof text === 'string' && Buffer.byteLength(text) <= MAX_TEXT_BYTES, 'OS_RELEASE_INVALID', 'os-release content is invalid or excessive');
  const out = Object.create(null);
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const match = /^([A-Z0-9_]+)=(.*)$/.exec(line);
    if (!match) continue;
    let value = match[2];
    if ((value.startsWith('"') && value.endsWith('"')) || (value.startsWith("'") && value.endsWith("'"))) value = value.slice(1, -1);
    out[match[1]] = value.replace(/\\([\\"'$`])/g, '$1');
  }
  return out;
}

function rootPath(root, absolutePath) {
  assert(typeof root === 'string' && path.isAbsolute(root), 'ROOT_INVALID', 'qualification root must be absolute');
  assert(typeof absolutePath === 'string' && absolutePath.startsWith('/') && !absolutePath.includes('\0'), 'PATH_INVALID', 'qualified path must be absolute');
  const pathParts = absolutePath.split('/').filter(Boolean);
  assert(pathParts.every(part => part !== '.' && part !== '..'), 'PATH_ESCAPE', `qualified path contains traversal: ${absolutePath}`);
  const resolvedRoot = path.resolve(root);
  const target = path.resolve(resolvedRoot, `.${absolutePath}`);
  assert(resolvedRoot === '/' || target === resolvedRoot || target.startsWith(`${resolvedRoot}${path.sep}`), 'PATH_ESCAPE', `qualified path escaped root: ${absolutePath}`);
  return target;
}

function sha256File(file) {
  const stat = fs.statSync(file);
  assert(stat.size <= 64 * 1024 * 1024, 'TRUSTED_FILE_TOO_LARGE', `trusted file unexpectedly large: ${file}`);
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}

function inspectTrustedFile(root, spec, expectedOwnerUid) {
  const target = rootPath(root, spec.path);
  const lstat = fs.lstatSync(target);
  assert(!lstat.isSymbolicLink(), 'TRUSTED_FILE_SYMLINKED', `${spec.path} must not be a symlink`);
  assert(lstat.isFile(), 'TRUSTED_FILE_INVALID', `${spec.path} must be a regular file`);
  const real = fs.realpathSync(target);
  assert(real === target, 'TRUSTED_FILE_REDIRECTED', `${spec.path} must resolve exactly inside the qualified root`);
  assert(typeof lstat.uid !== 'number' || lstat.uid === expectedOwnerUid, 'TRUSTED_FILE_OWNER_INVALID', `${spec.path} owner uid does not match the qualification authority`);
  assert((lstat.mode & 0o022) === 0, 'TRUSTED_FILE_WRITABLE', `${spec.path} must not be group/world writable`);
  if (spec.executable) assert((lstat.mode & 0o111) !== 0, 'TRUSTED_FILE_NOT_EXECUTABLE', `${spec.path} must be executable`);
  return Object.freeze({
    path: spec.path,
    ownerUid: typeof lstat.uid === 'number' ? lstat.uid : null,
    mode: (lstat.mode & 0o777).toString(8).padStart(3, '0'),
    size: lstat.size,
    sha256: sha256File(target),
  });
}

function defaultCommandRunner(binary, args) {
  const stdout = execFileSync(binary, args, {
    encoding: 'utf8',
    env: { PATH: '/usr/sbin:/usr/bin:/sbin:/bin', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' },
    maxBuffer: MAX_TEXT_BYTES,
    timeout: 15000,
    windowsHide: true,
    shell: false,
  });
  assert(Buffer.byteLength(stdout) <= MAX_TEXT_BYTES, 'COMMAND_OUTPUT_EXCESSIVE', `${binary} returned excessive output`);
  return stdout;
}

function parseDpkgStatus(output) {
  assert(typeof output === 'string' && Buffer.byteLength(output) <= MAX_TEXT_BYTES, 'DPKG_OUTPUT_INVALID', 'dpkg-query output is invalid');
  const line = output.trim();
  const match = /^(ii )\t([^\s]+)$/.exec(line);
  assert(match, 'FWUPD_PACKAGE_NOT_INSTALLED', 'fwupd must be installed in dpkg state ii');
  return match[2];
}

export function qualifyFwupdDebian13Runtime({ root = '/', commandRunner = defaultCommandRunner, expectedOwnerUid = 0 } = {}) {
  assert(typeof commandRunner === 'function', 'COMMAND_RUNNER_REQUIRED', 'command runner is required');
  assert(Number.isInteger(expectedOwnerUid) && expectedOwnerUid >= 0, 'OWNER_UID_INVALID', 'expected owner uid must be a non-negative integer');
  const resolvedRoot = path.resolve(root);
  const osReleasePath = rootPath(resolvedRoot, '/etc/os-release');
  const osReleaseStat = fs.lstatSync(osReleasePath);
  assert(osReleaseStat.isFile() && !osReleaseStat.isSymbolicLink(), 'OS_RELEASE_UNSAFE', '/etc/os-release must be a regular non-symlink file in the qualified image');
  const release = parseOsRelease(fs.readFileSync(osReleasePath, 'utf8'));
  assert(release.ID === 'debian', 'DISTRO_UNSUPPORTED', 'fwupd runtime qualification is pinned to Debian');
  assert(release.VERSION_ID === '13', 'DISTRO_VERSION_UNSUPPORTED', 'fwupd runtime qualification is pinned to Debian 13');

  const files = REQUIRED_FILES.map(spec => inspectTrustedFile(resolvedRoot, spec, expectedOwnerUid));
  const packageQuery = rootPath(resolvedRoot, '/usr/bin/dpkg-query');
  const dpkgStat = fs.lstatSync(packageQuery);
  assert(dpkgStat.isFile() && !dpkgStat.isSymbolicLink() && (dpkgStat.mode & 0o111) !== 0, 'DPKG_QUERY_UNTRUSTED', 'dpkg-query must be a regular executable file');
  assert(typeof dpkgStat.uid !== 'number' || dpkgStat.uid === expectedOwnerUid, 'DPKG_QUERY_OWNER_INVALID', 'dpkg-query owner uid does not match the qualification authority');
  assert((dpkgStat.mode & 0o022) === 0, 'DPKG_QUERY_WRITABLE', 'dpkg-query must not be group/world writable');

  const packageVersion = parseDpkgStatus(commandRunner(packageQuery, ['-W', '-f=${db:Status-Abbrev}\t${Version}\n', 'fwupd']));
  const help = commandRunner(rootPath(resolvedRoot, '/usr/bin/fwupdmgr'), ['--help']);
  assert(/fwupdmgr/i.test(help), 'FWUPDMGR_EXECUTION_INVALID', 'trusted fwupdmgr did not return its help surface');

  return Object.freeze({
    schema: SCHEMA,
    passed: true,
    distribution: Object.freeze({ id: release.ID, versionId: release.VERSION_ID, versionCodename: release.VERSION_CODENAME || null }),
    package: Object.freeze({ name: 'fwupd', version: packageVersion, manager: 'dpkg' }),
    files,
    runtime: Object.freeze({ fwupdmgrExecuted: true, command: '--help', daemonMutationAttempted: false }),
    policy: Object.freeze({
      readOnlyQualification: true,
      networkAccessRequired: false,
      refreshRemoteAllowed: false,
      firmwareMutationAllowed: false,
      remoteMutationAllowed: false,
      arbitraryFirmwareFileOrUrlAllowed: false,
      physicalHardwareQualification: false,
      secureBootQualification: false,
    }),
  });
}

function makeFile(root, rel, content, mode = 0o644) {
  const target = rootPath(root, rel);
  fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o755 });
  fs.writeFileSync(target, content, { mode });
  fs.chmodSync(target, mode);
}

function selfTest() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-fwupd-runtime-'));
  const expectedOwnerUid = process.getuid();
  try {
    makeFile(root, '/etc/os-release', 'ID=debian\nVERSION_ID="13"\nVERSION_CODENAME=trixie\n');
    makeFile(root, '/usr/bin/fwupdmgr', '#!/bin/sh\necho fwupdmgr\n', 0o755);
    makeFile(root, '/usr/libexec/fwupd/fwupd', '#!/bin/sh\nexit 0\n', 0o755);
    makeFile(root, '/etc/fwupd/remotes.d/lvfs.conf', '[fwupd Remote]\nEnabled=true\n', 0o644);
    makeFile(root, '/usr/bin/dpkg-query', '#!/bin/sh\nexit 0\n', 0o755);
    const fakeRunner = (binary, args) => {
      if (binary.endsWith('/dpkg-query')) {
        assert(args.join('\0') === ['-W', '-f=${db:Status-Abbrev}\t${Version}\n', 'fwupd'].join('\0'), 'SELFTEST_DPKG_ARGS', 'unexpected dpkg args');
        return 'ii \t2.0.20-1~deb13u1\n';
      }
      assert(binary.endsWith('/fwupdmgr') && args.length === 1 && args[0] === '--help', 'SELFTEST_FWUPDMGR_ARGS', 'unexpected fwupdmgr args');
      return 'Usage: fwupdmgr [OPTION…]\n';
    };
    const options = { root, commandRunner: fakeRunner, expectedOwnerUid };
    const result = qualifyFwupdDebian13Runtime(options);
    assert(result.passed && result.files.length === 3, 'SELFTEST_RESULT_INVALID', 'qualification result failed');
    assert(result.package.version === '2.0.20-1~deb13u1', 'SELFTEST_VERSION_INVALID', 'package version was not preserved');
    assert(result.policy.firmwareMutationAllowed === false && result.policy.physicalHardwareQualification === false, 'SELFTEST_POLICY_INVALID', 'safety policy weakened');

    fs.chmodSync(rootPath(root, '/etc/fwupd/remotes.d/lvfs.conf'), 0o666);
    let blocked = false;
    try { qualifyFwupdDebian13Runtime(options); } catch (error) { blocked = error?.code === 'TRUSTED_FILE_WRITABLE'; }
    assert(blocked, 'SELFTEST_WRITABLE_NOT_BLOCKED', 'writable LVFS config was not rejected');

    fs.chmodSync(rootPath(root, '/etc/fwupd/remotes.d/lvfs.conf'), 0o644);
    fs.writeFileSync(rootPath(root, '/etc/os-release'), 'ID=ubuntu\nVERSION_ID="24.04"\n');
    blocked = false;
    try { qualifyFwupdDebian13Runtime(options); } catch (error) { blocked = error?.code === 'DISTRO_UNSUPPORTED'; }
    assert(blocked, 'SELFTEST_DISTRO_NOT_BLOCKED', 'unexpected distro was not rejected');
    console.log('SWIR Debian 13 fwupd runtime qualification self-test: OK');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
}

function main() {
  if (process.argv.includes('--self-test')) {
    selfTest();
    return;
  }
  const result = qualifyFwupdDebian13Runtime();
  process.stdout.write(`${JSON.stringify(result)}\n`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) main();
