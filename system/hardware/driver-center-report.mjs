#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';
import process from 'node:process';
import { fileURLToPath } from 'node:url';
import { assertReadOnlyContract, collectHardwareSnapshot, loadCatalog } from './hardware-service.mjs';
import { assertSafeDriverPlan, resolveDriverPlan } from './driver-resolver.mjs';
import { assertSafeDriverCenterReport, createDriverCenterReport } from './driver-center-service.mjs';
import { FwupdLvfsService, assertSafeFwupdLvfsInventory } from './fwupd-lvfs-service.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const args = process.argv.slice(2);
let catalogPath = path.join(here, 'hardware-catalog.json');
let trustedSourcesPath = path.join(here, '..', 'contracts', 'trusted-sources.json');
let snapshotPath = null;
let pretty = true;

for (let i = 0; i < args.length; i += 1) {
  const arg = args[i];
  if (arg === '--catalog') {
    if (!args[i + 1]) throw new Error('--catalog requires a path');
    catalogPath = path.resolve(args[++i]);
  } else if (arg === '--trusted-sources') {
    if (!args[i + 1]) throw new Error('--trusted-sources requires a path');
    trustedSourcesPath = path.resolve(args[++i]);
  } else if (arg === '--snapshot') {
    if (!args[i + 1]) throw new Error('--snapshot requires a path');
    snapshotPath = path.resolve(args[++i]);
  } else if (arg === '--compact') {
    pretty = false;
  } else if (arg === '--help') {
    console.log('Usage: node system/hardware/driver-center-report.mjs [--catalog PATH] [--trusted-sources PATH] [--snapshot PATH] [--compact]');
    process.exit(0);
  } else {
    throw new Error(`Unknown argument: ${arg}`);
  }
}

function firmwareFallback(probe, error = null) {
  return Object.freeze({
    provider: 'fwupd-lvfs',
    readOnly: true,
    mutationAuthorized: false,
    available: probe?.available === true,
    binaryTrusted: probe?.trustedBinary === true,
    inventoryReady: false,
    updates: [],
    ignoredNonLvfsCandidates: 0,
    errorCode: error?.code || error?.name || null
  });
}

async function collectFirmware() {
  const service = new FwupdLvfsService();
  const probe = await service.probe();
  if (!probe.available) return firmwareFallback(probe);
  if (probe.trustedBinary !== true) return firmwareFallback(probe, { code: 'FWUPD_BINARY_UNTRUSTED' });
  try {
    const inventory = await service.inventory();
    assertSafeFwupdLvfsInventory(inventory);
    return Object.freeze({
      provider: 'fwupd-lvfs',
      readOnly: true,
      mutationAuthorized: false,
      available: inventory.available === true,
      binaryTrusted: inventory.probe?.trustedBinary === true,
      inventoryReady: true,
      updates: inventory.candidates,
      ignoredNonLvfsCandidates: inventory.ignoredNonLvfsCandidates,
      errorCode: null
    });
  } catch (error) {
    return firmwareFallback(probe, error);
  }
}

const catalog = loadCatalog(catalogPath);
const trustedSources = JSON.parse(fs.readFileSync(trustedSourcesPath, 'utf8'));
if (trustedSources?.schema !== 'swir.trusted-sources/0.1') throw new Error('Unsupported trusted source policy');
const snapshot = snapshotPath
  ? JSON.parse(fs.readFileSync(snapshotPath, 'utf8'))
  : collectHardwareSnapshot({ catalog });
assertReadOnlyContract(snapshot);
const plan = resolveDriverPlan(snapshot, catalog);
assertSafeDriverPlan(plan);
const baseReport = createDriverCenterReport(snapshot, plan, trustedSources);
const firmware = await collectFirmware();
const report = { ...baseReport, firmware };
assertSafeDriverCenterReport(report);
process.stdout.write(`${JSON.stringify(report, null, pretty ? 2 : 0)}\n`);
