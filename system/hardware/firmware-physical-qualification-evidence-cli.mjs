#!/usr/bin/env node
import process from 'node:process';
import {
  createPhysicalQualificationEvidenceBundle,
  readPhysicalQualificationEvidenceFile,
  verifyPhysicalQualificationEvidenceBundle,
  writePhysicalQualificationEvidenceFile
} from './firmware-physical-qualification-evidence.mjs';
import { FileFirmwarePhysicalQualificationJournal } from './firmware-physical-qualification-service.mjs';

function fail(message, code = 2) {
  console.error(`SWIR firmware qualification evidence: ${message}`);
  process.exitCode = code;
}

function usage() {
  console.log(`SWIR OS physical firmware qualification evidence export/verification

Usage:
  firmware-physical-qualification-evidence-cli.mjs export --session <qualification-id> --output <absolute-json-path>
  firmware-physical-qualification-evidence-cli.mjs verify --file <absolute-json-path> [expected bindings]

Expected bindings for verify:
  --expect-qualification <id>
  --expect-device <fwupd-device-id>
  --expect-target <firmware-version>
  --expect-plan-digest <sha256>
  --expect-transaction <transaction-id>
  --expect-machine-hash <sha256>

Trust boundary:
  export is allowed only for an already-finalized real-hardware qualification session.
  The bundle carries a deterministic SHA-256 integrity digest and privacy-minimized bindings,
  but it is not a cryptographic signature and does not authenticate its own origin.
  For provenance, compare expected bindings against a separately trusted record.
  This tool never flashes firmware, reboots the host, enables remotes or accepts firmware files/URLs.`);
}

function parseArgs(argv) {
  const [command, ...rest] = argv;
  const allowed = new Set([
    'session', 'output', 'file', 'expect-qualification', 'expect-device', 'expect-target',
    'expect-plan-digest', 'expect-transaction', 'expect-machine-hash'
  ]);
  const options = {};
  for (let index = 0; index < rest.length; index += 1) {
    const token = rest[index];
    if (!token.startsWith('--')) throw new Error(`unexpected argument: ${token}`);
    const key = token.slice(2);
    if (!allowed.has(key)) throw new Error(`unsupported option: ${token}`);
    const value = rest[index + 1];
    if (!value || value.startsWith('--')) throw new Error(`${token} requires a value`);
    if (options[key] !== undefined) throw new Error(`${token} may be supplied only once`);
    options[key] = value;
    index += 1;
  }
  return { command, options };
}

function requireRootForJournalExport() {
  if (typeof process.getuid === 'function' && process.getuid() !== 0) {
    throw new Error('export reads the protected qualification journal and must run as root on the qualification machine');
  }
}

function expectedBindings(options) {
  return {
    qualificationId: options['expect-qualification'],
    deviceId: options['expect-device'],
    targetVersion: options['expect-target'],
    planDigest: options['expect-plan-digest'],
    transactionId: options['expect-transaction'],
    machineIdHash: options['expect-machine-hash']
  };
}

function summary(result) {
  return {
    schema: result.schema,
    integrityVerified: result.integrityVerified,
    expectedBindingsSatisfied: result.expectedBindingsSatisfied,
    qualificationId: result.qualificationId,
    deviceId: result.deviceId,
    targetVersion: result.targetVersion,
    planDigest: result.planDigest,
    transactionId: result.transactionId,
    machineIdHash: result.machineIdHash,
    payloadDigest: result.payloadDigest,
    cryptographicOriginAuthentication: false,
    physicalityProvenByBundle: false,
    trustedComparisonRequiredForProvenance: true
  };
}

async function main() {
  const { command, options } = parseArgs(process.argv.slice(2));
  if (!command || ['help', '--help', '-h'].includes(command)) {
    usage();
    return;
  }
  if (!['export', 'verify'].includes(command)) throw new Error(`unknown command: ${command}`);

  if (command === 'export') {
    if (!options.session || !options.output) throw new Error('export requires --session <qualification-id> and --output <absolute-json-path>');
    requireRootForJournalExport();
    const journal = new FileFirmwarePhysicalQualificationJournal();
    const session = journal.read(options.session);
    const bundle = createPhysicalQualificationEvidenceBundle(session);
    const target = writePhysicalQualificationEvidenceFile(options.output, bundle);
    const verified = verifyPhysicalQualificationEvidenceBundle(bundle, {
      qualificationId: session.qualificationId,
      deviceId: session.plan.binding.deviceId,
      targetVersion: session.plan.binding.targetVersion,
      planDigest: session.planDigest,
      transactionId: session.transactionId,
      machineIdHash: session.hostBefore.machineIdHash
    });
    console.log(JSON.stringify({ output: target, ...summary(verified) }, null, 2));
    console.log('\nEvidence exported from an already-finalized qualification session. No firmware mutation was performed.');
    console.log('Keep the payload digest and expected bindings in a separately trusted record when provenance matters.');
    return;
  }

  if (!options.file) throw new Error('verify requires --file <absolute-json-path>');
  const bundle = readPhysicalQualificationEvidenceFile(options.file);
  const verified = verifyPhysicalQualificationEvidenceBundle(bundle, expectedBindings(options));
  console.log(JSON.stringify(summary(verified), null, 2));
  console.log('\nIntegrity and supplied bindings verified. This is not cryptographic origin authentication and does not independently prove physical hardware.');
}

main().catch(error => {
  fail(`${error?.code ? `${error.code}: ` : ''}${error?.message || error}`);
});
