#!/usr/bin/env node
import fs from 'node:fs';
import path from 'node:path';

const input = process.argv[2];
if (!input) {
  console.error('Usage: validate-live-usb-install-evidence.mjs <evidence.json>');
  process.exit(2);
}
const resolved = path.resolve(input);
const data = JSON.parse(fs.readFileSync(resolved, 'utf8'));
const fail = (message) => { throw new Error(`invalid Live USB/install evidence: ${message}`); };
const requireTrue = (key) => { if (data[key] !== true) fail(`${key} must be true`); };
const requireFalse = (key) => { if (data[key] !== false) fail(`${key} must be false`); };

if (data.schema !== 'swir.system-live-usb-install-e2e/0.1') fail('schema mismatch');
if (data.distribution !== 'debian-13-trixie') fail('distribution mismatch');
if (data.architecture !== 'amd64') fail('architecture mismatch');
if (data.firmware !== 'uefi-ovmf') fail('firmware mismatch');
if (data.liveMediaFormat !== 'raw-gpt-img') fail('Live media format mismatch');
if (data.liveUsbTransport !== 'qemu-usb-storage') fail('USB transport mismatch');
for (const key of ['liveImageSha256', 'installedDiskSha256']) {
  if (typeof data[key] !== 'string' || !/^[0-9a-f]{64}$/.test(data[key])) fail(`${key} is not SHA-256`);
}
for (const key of [
  'liveUsbBooted',
  'liveGraphicalSessionPassed',
  'graphicalInstallerUiSmokePassed',
  'internalDiskUnchangedBeforeExplicitInstall',
  'installerPreviewReadOnly',
  'installerCancellationReadOnly',
  'wrongConfirmationRejectedWithoutWrite',
  'sourceMediaTargetRejected',
  'explicitConfirmationRequired',
  'installToSeparateDiskPassed',
  'sourceUsbDetachedBeforeInstalledBoot',
  'installedDiskBooted',
  'installedGraphicalSessionPassed',
  'persistencePassed',
]) requireTrue(key);
for (const key of ['secureBootClaim', 'physicalHardwareQualificationClaim', 'graphicalInstallerClaim']) requireFalse(key);
if (Number.isNaN(Date.parse(data.generatedAt))) fail('generatedAt is not an ISO timestamp');
console.log('SWIR Live USB/install evidence is valid');
