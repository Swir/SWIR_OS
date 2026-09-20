#!/usr/bin/env node
import readline from 'node:readline/promises';
import process from 'node:process';
import { stdin as input, stdout as output } from 'node:process';
import { FwupdLvfsService } from './fwupd-lvfs-service.mjs';
import { FileFirmwareUpdateJournal, FirmwareUpdateTransactionService } from './firmware-update-transaction-service.mjs';
import { FirmwareUpdateVerificationService } from './firmware-update-verification-service.mjs';
import {
  FileFirmwarePhysicalQualificationJournal,
  FirmwarePhysicalQualificationService,
  PhysicalFirmwareHostProbe
} from './firmware-physical-qualification-service.mjs';

function fail(message, code = 2) {
  console.error(`SWIR firmware qualification: ${message}`);
  process.exitCode = code;
}

function usage() {
  console.log(`SWIR OS physical firmware qualification (dedicated lab hardware only)

Usage:
  firmware-physical-qualification-cli.mjs preflight --device <fwupd-device-id>
  firmware-physical-qualification-cli.mjs apply --session <qualification-id>
  firmware-physical-qualification-cli.mjs verify --session <qualification-id>
  firmware-physical-qualification-cli.mjs finalize --session <qualification-id>
  firmware-physical-qualification-cli.mjs status --session <qualification-id>

Safety:
  preflight does not flash firmware; apply and finalize require an interactive TTY.
  No command automatically reboots, rolls back, downloads an arbitrary firmware file,
  or turns CI/emulation evidence into physical-hardware qualification.`);
}

function parseArgs(argv) {
  const [command, ...rest] = argv;
  const options = {};
  for (let index = 0; index < rest.length; index += 1) {
    const token = rest[index];
    if (!token.startsWith('--')) throw new Error(`unexpected argument: ${token}`);
    const key = token.slice(2);
    if (!['device', 'session'].includes(key)) throw new Error(`unsupported option: ${token}`);
    const value = rest[index + 1];
    if (!value || value.startsWith('--')) throw new Error(`${token} requires a value`);
    options[key] = value;
    index += 1;
  }
  return { command, options };
}

function requireRoot() {
  if (typeof process.getuid === 'function' && process.getuid() !== 0) {
    throw new Error('run the qualification harness as root on the dedicated lab machine so owner-only journals stay protected');
  }
}

function requireInteractive() {
  if (input.isTTY !== true || output.isTTY !== true) {
    throw new Error('this step requires an interactive terminal; non-interactive/CI mutation is forbidden');
  }
}

function actorId() {
  return String(process.env.SUDO_USER || process.env.USER || 'root').replace(/[\u0000-\u001f\u007f]/g, '').slice(0, 128);
}

function createServices() {
  const inventory = new FwupdLvfsService();
  const transactionJournal = new FileFirmwareUpdateJournal();
  const transactions = new FirmwareUpdateTransactionService({ inventoryService: inventory, journal: transactionJournal });
  const verification = new FirmwareUpdateVerificationService({ inventoryService: inventory, journal: transactionJournal });
  const qualificationJournal = new FileFirmwarePhysicalQualificationJournal();
  const qualification = new FirmwarePhysicalQualificationService({
    transactionService: transactions,
    verificationService: verification,
    hostProbe: new PhysicalFirmwareHostProbe(),
    journal: qualificationJournal
  });
  return { inventory, qualification };
}

function safeSummary(session) {
  return {
    schema: session.schema,
    qualificationId: session.qualificationId,
    state: session.state,
    deviceId: session.plan?.binding?.deviceId ?? null,
    deviceName: session.plan?.binding?.deviceName ?? null,
    fromVersion: session.plan?.binding?.currentVersion ?? null,
    targetVersion: session.plan?.binding?.targetVersion ?? null,
    requiresReboot: session.plan?.binding?.requiresReboot === true,
    planDigest: session.planDigest,
    transactionId: session.transactionId,
    transactionStatus: session.transactionStatus,
    verificationStatus: session.verification?.status ?? null,
    rebootEvidenceSatisfied: session.assessment?.requiredRebootObserved ?? null,
    eligibleForOperatorFinalize: session.assessment?.eligible ?? false,
    physicalHardwareQualification: session.physicalHardwareQualification === true,
    automaticReboot: false,
    automaticRollback: false
  };
}

async function askExact(promptText, expected) {
  const rl = readline.createInterface({ input, output, terminal: true });
  try {
    console.log(`Type exactly:\n${expected}`);
    const answer = await rl.question(`${promptText}: `);
    if (answer !== expected) throw new Error('typed confirmation did not match exactly; no mutation/qualification was performed');
    return answer;
  } finally {
    rl.close();
  }
}

async function main() {
  const { command, options } = parseArgs(process.argv.slice(2));
  if (!command || ['help', '--help', '-h'].includes(command)) {
    usage();
    return;
  }
  if (!['preflight', 'apply', 'verify', 'finalize', 'status'].includes(command)) throw new Error(`unknown command: ${command}`);

  requireRoot();
  const { inventory, qualification } = createServices();

  if (command === 'preflight') {
    if (!options.device) throw new Error('preflight requires --device <fwupd-device-id>');
    const snapshot = await inventory.inventory();
    if (snapshot.available !== true) throw new Error('trusted fwupd/LVFS inventory is unavailable');
    const candidates = snapshot.candidates.filter(candidate => candidate?.deviceId === options.device);
    if (candidates.length !== 1) throw new Error('preflight requires exactly one trusted LVFS update candidate for the selected device');
    const session = await qualification.prepare(candidates[0], { actorId: actorId() });
    console.log(JSON.stringify(safeSummary(session), null, 2));
    console.log('\nPreflight only created reviewed owner-only evidence. Firmware has NOT been mutated.');
    console.log('Before apply, confirm this is disposable/dedicated physical lab hardware and review vendor recovery guidance.');
    return;
  }

  if (!options.session) throw new Error(`${command} requires --session <qualification-id>`);

  if (command === 'status') {
    console.log(JSON.stringify(safeSummary(qualification.status(options.session)), null, 2));
    return;
  }

  if (command === 'apply') {
    requireInteractive();
    const session = qualification.status(options.session);
    console.log(JSON.stringify(safeSummary(session), null, 2));
    console.log('\nWARNING: the next confirmed step may flash firmware on the bound device.');
    console.log('SWIR will not reboot automatically and cannot promise automatic firmware rollback.');
    await askExact('Dedicated hardware attestation', 'DEDICATED PHYSICAL LAB HARDWARE');
    const typedPhrase = await askExact('Firmware apply confirmation', session.expectedApplyPhrase);
    const updated = await qualification.apply(options.session, {
      interactive: true,
      operatorPresent: true,
      physicalDedicatedHardware: true,
      confirmationDigest: session.planDigest,
      typedPhrase,
      actorId: actorId()
    });
    console.log(JSON.stringify(safeSummary(updated), null, 2));
    if (updated.plan?.binding?.requiresReboot === true) {
      console.log('\nA reboot/power-cycle is required by the reviewed LVFS metadata. Perform it explicitly, then run verify.');
    } else {
      console.log('\nRun verify before any final physical-hardware qualification.');
    }
    return;
  }

  if (command === 'verify') {
    const updated = await qualification.verify(options.session);
    console.log(JSON.stringify(safeSummary(updated), null, 2));
    if (updated.state === 'ready-for-finalize') {
      console.log('\nSoftware evidence is internally consistent. It is NOT yet physical-hardware qualification; use interactive finalize after physical inspection.');
    } else {
      console.log('\nEvidence is still incomplete/pending. Do not force-flash, retry blindly, or claim qualification.');
    }
    return;
  }

  requireInteractive();
  const session = qualification.status(options.session);
  console.log(JSON.stringify(safeSummary(session), null, 2));
  await askExact('Physical observation attestation', 'I OBSERVED THE DEDICATED PHYSICAL HARDWARE');
  await askExact('Recovery review attestation', 'DEVICE RECOVERY GUIDANCE REVIEWED');
  const typedPhrase = await askExact('Final qualification confirmation', session.expectedFinalizePhrase);
  const finalized = await qualification.finalize(options.session, {
    interactive: true,
    operatorPresent: true,
    physicalHardwareObserved: true,
    dedicatedHardware: true,
    recoveryReviewed: true,
    typedPhrase,
    actorId: actorId()
  });
  console.log(JSON.stringify(safeSummary(finalized), null, 2));
  console.log('\nPhysical firmware qualification evidence was finalized for this exact device/release/session only.');
}

main().catch(error => {
  fail(`${error?.code ? `${error.code}: ` : ''}${error?.message || error}`);
});