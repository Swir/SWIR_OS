import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { RecoveryModeProvisioningPolicy, stageRecoveryModeFoundation, verifyRecoveryModeFoundation } from './recovery-mode-provisioning.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const sourceRoot = path.resolve(here, '../..');
const rootfs = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-recovery-provisioning-'));
fs.chmodSync(rootfs, 0o700);

const staged = await stageRecoveryModeFoundation({ rootfs, sourceRoot, production: false, clock: () => '2026-09-17T16:10:00.000Z' });
assert.equal(staged.schema, 'swir.recovery-mode-provisioning/0.1');
assert.equal(staged.ready, true);
assert.equal(staged.recoveryBootVerified, false);
assert.equal(staged.filesystemRepairClaim, false);
assert.equal(staged.automaticMutationAllowed, false);
assert.equal(staged.artifacts.length, 3);
for (const artifact of staged.artifacts) {
  assert.match(artifact.sha256, /^[0-9a-f]{64}$/);
  assert.equal(artifact.mode, 0o644);
}

const verified = await verifyRecoveryModeFoundation({ rootfs, production: false });
assert.equal(verified.ready, true);
assert.equal(verified.blockers.length, 0);
assert.equal(RecoveryModeProvisioningPolicy.symlinkDestinationsAllowed, false);
assert.equal(RecoveryModeProvisioningPolicy.automaticFilesystemRepair, false);
assert.equal(RecoveryModeProvisioningPolicy.automaticPackageMutation, false);
assert.equal(RecoveryModeProvisioningPolicy.automaticFirmwareMutation, false);

const servicePath = path.join(rootfs, 'etc/systemd/system/swir-recovery.service');
const serviceUnit = fs.readFileSync(servicePath, 'utf8');
assert.match(serviceUnit, /^RuntimeDirectory=swir\/recovery$/m);
assert.match(serviceUnit, /^RuntimeDirectoryMode=0700$/m);
assert.match(serviceUnit, /^RuntimeDirectoryPreserve=yes$/m);
assert.match(serviceUnit, /^ReadWritePaths=\/run\/swir\/recovery$/m);
assert.doesNotMatch(serviceUnit, /^ReadWritePaths=-/m);

const targetPath = path.join(rootfs, 'etc/systemd/system/swir-recovery.target');
fs.rmSync(targetPath);
fs.symlinkSync('/tmp/evil-target', targetPath);
const tampered = await verifyRecoveryModeFoundation({ rootfs, production: false });
assert.equal(tampered.ready, false);
assert.ok(tampered.blockers.includes('recovery-target'));

fs.rmSync(rootfs, { recursive: true, force: true });
console.log('recovery-mode-provisioning self-test passed');
