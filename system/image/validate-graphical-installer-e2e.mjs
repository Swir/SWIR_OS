#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const input = process.argv[2];
if (!input) {
  console.error('Usage: validate-graphical-installer-e2e.mjs <evidence.json>');
  process.exit(2);
}

const resolved = path.resolve(input);
const data = JSON.parse(fs.readFileSync(resolved, 'utf8'));
const fail = (message) => { throw new Error(`invalid graphical installer E2E evidence: ${message}`); };
const requireTrue = (key) => { if (data[key] !== true) fail(`${key} must be true`); };
const requireFalse = (key) => { if (data[key] !== false) fail(`${key} must be false`); };

if (data.schema !== 'swir.graphical-installer-full-e2e/0.1') fail('schema mismatch');
if (data.distribution !== 'debian-13-trixie') fail('distribution mismatch');
if (data.architecture !== 'amd64') fail('architecture mismatch');
if (data.firmware !== 'uefi-ovmf') fail('firmware mismatch');
if (data.liveUsbTransport !== 'qemu-usb-storage') fail('USB transport mismatch');
for (const key of ['liveImageSha256', 'installedDiskSha256']) {
  if (typeof data[key] !== 'string' || !/^[0-9a-f]{64}$/.test(data[key])) fail(`${key} is not SHA-256`);
}
for (const key of [
  'gtkWindowCreated',
  'uiSelectedStableTarget',
  'uiPreviewReadOnly',
  'uiWrongTokenBlocked',
  'uiIdentityReviewPassed',
  'uiTriggeredPrivilegedInstall',
  'sourceMediaTargetRejected',
  'installedUserCreated',
  'installedLocaleVerified',
  'installedKeyboardVerified',
  'installedTimezoneVerified',
  'sourceUsbDetachedBeforeInstalledBoot',
  'installedDiskBooted',
  'installedGraphicalSessionPassed',
  'installedPersistencePassed',
]) requireTrue(key);
for (const key of ['passwordStoredInEvidence', 'physicalHardwareQualificationClaim', 'secureBootClaim']) requireFalse(key);
if (Number.isNaN(Date.parse(data.generatedAt))) fail('generatedAt is not an ISO timestamp');

console.log('SWIR graphical installer full-path E2E evidence is valid');
