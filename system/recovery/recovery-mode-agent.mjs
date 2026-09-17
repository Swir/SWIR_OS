import fs from 'node:fs';
import path from 'node:path';
import { spawn } from 'node:child_process';

const SAFE_OUTPUT_ROOT = '/run/swir/recovery';
const MAX_JOURNAL_BYTES = 1024 * 1024;
const PACKAGE_JOURNAL_ROOT = '/var/lib/swir/package-transactions';
const PACKAGE_JOURNAL_SCHEMA = 'swir.system-package-transaction/0.1';
const FIRMWARE_JOURNAL_ROOT = '/var/lib/swir/transactions/firmware';
const FIRMWARE_JOURNAL_SCHEMA = 'swir.firmware-transaction-journal/0.1';
const PENDING_PACKAGE_STATES = new Set(['prepared', 'mutating', 'verifying', 'rolling-back', 'failed-needs-recovery']);
const PENDING_FIRMWARE_STATUSES = new Set(['planned', 'authorized', 'executing', 'staged-reboot-required', 'failed-needs-recovery']);

function fail(code, message, cause) {
  const error = new Error(message, cause ? { cause } : undefined);
  error.name = 'SwirRecoveryModeError';
  error.code = code;
  throw error;
}
function assert(condition, code, message) { if (!condition) fail(code, message); }
function parseArgs(argv) {
  const out = { output: `${SAFE_OUTPUT_ROOT}/recovery-report.json`, compact: false };
  for (let i = 0; i < argv.length; i += 1) {
    if (argv[i] === '--output') out.output = argv[++i] || '';
    else if (argv[i] === '--compact') out.compact = true;
    else fail('INVALID_ARGUMENT', `unsupported argument: ${argv[i]}`);
  }
  const resolved = path.resolve(out.output);
  assert(resolved === SAFE_OUTPUT_ROOT || resolved.startsWith(`${SAFE_OUTPUT_ROOT}${path.sep}`), 'UNSAFE_OUTPUT_PATH', 'recovery report must stay under /run/swir/recovery');
  out.output = resolved;
  return out;
}
function trustedBinary(filePath) {
  const stat = fs.lstatSync(filePath);
  assert(stat.isFile() && !stat.isSymbolicLink(), 'UNTRUSTED_BINARY', `${filePath} must be a regular non-symlink file`);
  assert(stat.uid === 0, 'UNTRUSTED_BINARY_OWNER', `${filePath} must be root-owned`);
  assert((stat.mode & 0o022) === 0, 'UNTRUSTED_BINARY_MODE', `${filePath} must not be group/world writable`);
}
function run(file, args, { timeoutMs = 10_000, maxBytes = 128 * 1024 } = {}) {
  trustedBinary(file);
  return new Promise((resolve, reject) => {
    const child = spawn(file, args, {
      shell: false,
      windowsHide: true,
      stdio: ['ignore', 'pipe', 'pipe'],
      env: { PATH: '/usr/sbin:/usr/bin:/sbin:/bin', LANG: 'C.UTF-8', LC_ALL: 'C.UTF-8' }
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
    const collect = (key, chunk) => {
      const text = Buffer.isBuffer(chunk) ? chunk.toString('utf8') : String(chunk);
      bytes += Buffer.byteLength(text);
      if (bytes > maxBytes) {
        child.kill('SIGKILL');
        finish(reject, Object.assign(new Error('recovery probe output limit exceeded'), { code: 'PROBE_OUTPUT_LIMIT' }));
        return;
      }
      if (key === 'stdout') stdout += text;
      else stderr += text;
    };
    child.stdout?.on('data', chunk => collect('stdout', chunk));
    child.stderr?.on('data', chunk => collect('stderr', chunk));
    child.on('error', error => finish(reject, error));
    child.on('close', (exitCode, signal) => finish(resolve, { exitCode, signal: signal || null, stdout, stderr }));
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      finish(reject, Object.assign(new Error('recovery probe timed out'), { code: 'PROBE_TIMEOUT' }));
    }, timeoutMs);
    timer.unref?.();
  });
}
function parseMountInfo() {
  const lines = fs.readFileSync('/proc/self/mountinfo', 'utf8').trim().split('\n');
  for (const line of lines) {
    const fields = line.split(' ');
    const separator = fields.indexOf('-');
    if (separator < 0 || fields[4] !== '/') continue;
    return {
      mountPoint: fields[4],
      mountOptions: fields[5].split(','),
      filesystem: fields[separator + 1] || '',
      source: fields[separator + 2] || ''
    };
  }
  fail('ROOT_MOUNT_NOT_FOUND', 'root mount was not found in /proc/self/mountinfo');
}
function parseFstab() {
  const entries = [];
  const text = fs.readFileSync('/etc/fstab', 'utf8');
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.replace(/\s+#.*$/, '').trim();
    if (!line || line.startsWith('#')) continue;
    const fields = line.split(/\s+/);
    if (fields.length < 4) continue;
    entries.push({ source: fields[0], target: fields[1], type: fields[2], options: fields[3].split(',') });
  }
  return entries;
}
function scanTransactionDirectory(directory, expectedSchema, { statusField, pendingStates, idFields }) {
  const result = {
    directory,
    schema: expectedSchema,
    statusField,
    exists: false,
    journals: 0,
    pending: 0,
    corrupt: 0,
    pendingIds: []
  };
  if (!fs.existsSync(directory)) return result;
  const directoryStat = fs.lstatSync(directory);
  assert(directoryStat.isDirectory() && !directoryStat.isSymbolicLink(), 'UNSAFE_JOURNAL_DIRECTORY', `unsafe journal directory: ${directory}`);
  assert(directoryStat.uid === 0, 'UNSAFE_JOURNAL_DIRECTORY_OWNER', `journal directory must be root-owned: ${directory}`);
  assert((directoryStat.mode & 0o022) === 0, 'UNSAFE_JOURNAL_DIRECTORY_MODE', `journal directory must not be group/world writable: ${directory}`);
  result.exists = true;
  for (const name of fs.readdirSync(directory).filter(item => item.endsWith('.json')).sort()) {
    const file = path.join(directory, name);
    try {
      const stat = fs.lstatSync(file);
      assert(stat.isFile() && !stat.isSymbolicLink() && stat.size <= MAX_JOURNAL_BYTES, 'UNSAFE_JOURNAL_FILE', `unsafe journal file: ${file}`);
      assert(stat.uid === 0, 'UNSAFE_JOURNAL_FILE_OWNER', `journal file must be root-owned: ${file}`);
      assert((stat.mode & 0o022) === 0, 'UNSAFE_JOURNAL_FILE_MODE', `journal file must not be group/world writable: ${file}`);
      const record = JSON.parse(fs.readFileSync(file, 'utf8'));
      if (record?.schema !== expectedSchema) throw new Error('schema mismatch');
      result.journals += 1;
      const status = String(record?.[statusField] || '');
      if (pendingStates.has(status)) {
        result.pending += 1;
        const recordId = idFields.map(field => record?.[field]).find(value => typeof value === 'string' && value.length > 0);
        result.pendingIds.push(String(recordId || path.basename(name, '.json')).slice(0, 160));
      }
    } catch {
      result.corrupt += 1;
    }
  }
  return result;
}
function atomicWrite(output, payload) {
  fs.mkdirSync(path.dirname(output), { recursive: true, mode: 0o700 });
  const parent = fs.lstatSync(path.dirname(output));
  assert(parent.isDirectory() && !parent.isSymbolicLink(), 'UNSAFE_OUTPUT_DIRECTORY', 'recovery output directory must be a real directory');
  const temp = `${output}.tmp-${process.pid}`;
  fs.writeFileSync(temp, payload, { encoding: 'utf8', mode: 0o600, flag: 'wx' });
  fs.renameSync(temp, output);
}

const args = parseArgs(process.argv.slice(2));
const cmdline = fs.readFileSync('/proc/cmdline', 'utf8').trim();
const cmdlineTokens = new Set(cmdline.split(/\s+/).filter(Boolean));
assert(cmdlineTokens.has('systemd.unit=swir-recovery.target'), 'NOT_RECOVERY_BOOT', 'kernel command line did not select swir-recovery.target');
assert(cmdlineTokens.has('ro'), 'RECOVERY_ROOT_NOT_REQUESTED_READ_ONLY', 'recovery boot must request read-only root');
assert(cmdlineTokens.has('systemd.mask=systemd-remount-fs.service'), 'ROOT_REMOUNT_NOT_BLOCKED', 'recovery boot must mask systemd-remount-fs.service');

const root = parseMountInfo();
const rootReadOnly = root.mountOptions.includes('ro') && !root.mountOptions.includes('rw');
const fstab = parseFstab();
const fstabRoot = fstab.find(item => item.target === '/');
const fstabEsp = fstab.find(item => item.target === '/boot/efi');
const rootFstabIntegrated = fstabRoot?.source === 'LABEL=SWIR_ROOT' && fstabRoot?.type === 'ext4';
const espFstabIntegrated = fstabEsp?.source === 'LABEL=SWIR_ESP' && fstabEsp?.type === 'vfat';

const blkidRoot = await run('/usr/sbin/blkid', ['-L', 'SWIR_ROOT']);
assert(blkidRoot.exitCode === 0 && !blkidRoot.signal, 'ROOT_LABEL_UNRESOLVED', 'SWIR_ROOT label did not resolve');
const rootDevice = blkidRoot.stdout.trim();
assert(/^\/dev\/[A-Za-z0-9._/+:-]+$/.test(rootDevice), 'ROOT_DEVICE_INVALID', 'resolved root device path is invalid');
const blkidType = await run('/usr/sbin/blkid', ['-s', 'TYPE', '-o', 'value', rootDevice]);
const rootFilesystem = blkidType.exitCode === 0 ? blkidType.stdout.trim() : '';
const networkDevices = fs.readdirSync('/sys/class/net').sort();
const nonLoopbackNetworkDevices = networkDevices.filter(name => name !== 'lo');
const packageTransactions = scanTransactionDirectory(PACKAGE_JOURNAL_ROOT, PACKAGE_JOURNAL_SCHEMA, {
  statusField: 'state',
  pendingStates: PENDING_PACKAGE_STATES,
  idFields: ['id']
});
const firmwareTransactions = scanTransactionDirectory(FIRMWARE_JOURNAL_ROOT, FIRMWARE_JOURNAL_SCHEMA, {
  statusField: 'status',
  pendingStates: PENDING_FIRMWARE_STATUSES,
  idFields: ['transactionId']
});

const report = {
  schema: 'swir.recovery-mode-report/0.2',
  generatedAt: new Date().toISOString(),
  bootTarget: 'swir-recovery.target',
  diagnosticMode: true,
  root: {
    source: root.source,
    resolvedLabelDevice: rootDevice,
    filesystem: rootFilesystem || root.filesystem,
    readOnly: rootReadOnly,
    fstabIntegrated: rootFstabIntegrated
  },
  esp: { fstabIntegrated: espFstabIntegrated },
  kernelPolicy: {
    rootRequestedReadOnly: cmdlineTokens.has('ro'),
    remountServiceMasked: cmdlineTokens.has('systemd.mask=systemd-remount-fs.service'),
    fstabGeneratorDisabled: cmdlineTokens.has('fstab=no')
  },
  network: { devices: networkDevices, nonLoopbackDevices: nonLoopbackNetworkDevices, networkActivationRequested: false },
  transactions: { packages: packageTransactions, firmware: firmwareTransactions },
  automaticFilesystemRepairPerformed: false,
  automaticPackageMutationPerformed: false,
  automaticFirmwareMutationPerformed: false,
  safeReadOnlyRecoveryBoot: rootReadOnly && rootFstabIntegrated && espFstabIntegrated && rootFilesystem === 'ext4' && nonLoopbackNetworkDevices.length === 0,
  manualRecoveryRequiredForPendingTransactions: packageTransactions.pending > 0 || firmwareTransactions.pending > 0 || packageTransactions.corrupt > 0 || firmwareTransactions.corrupt > 0
};
assert(report.safeReadOnlyRecoveryBoot, 'RECOVERY_SAFETY_INVARIANT_FAILED', 'recovery environment did not satisfy read-only filesystem/network invariants');
const payload = `${JSON.stringify(report, null, args.compact ? 0 : 2)}\n`;
atomicWrite(args.output, payload);
process.stdout.write(payload);
