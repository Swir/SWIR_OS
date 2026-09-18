import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  PackageUiRuntimeProvisioningPolicy,
  stagePackageUiRuntime,
  verifyPackageUiRuntime,
} from './system-package-ui-runtime-provisioning.mjs';

const here = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(here, '..', '..');
const temp = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-package-ui-runtime-'));
const rootfs = path.join(temp, 'rootfs');
fs.mkdirSync(rootfs, { recursive: true, mode: 0o700 });

const staged = await stagePackageUiRuntime({
  rootfs,
  sourceRoot: repoRoot,
  production: false,
  clock: () => '2026-09-18T02:00:00.000Z',
});
assert.equal(staged.ready, true);
assert.equal(staged.staged, true);
assert.equal(staged.packageBrokerServiceEnabled, true);
assert.equal(staged.runtimeKeyEmbeddedInImage, false);
assert.equal(staged.directUiPackageToolsAllowed, false);
assert.equal(staged.bootableImageClaim, false);
assert.equal(fs.existsSync(path.join(rootfs, 'run/swir/peer-authorization.key')), false);
assert.equal(fs.existsSync(path.join(rootfs, 'usr/lib/swir/package-broker/ipc/swir-package-transaction-broker.mjs')), true);
assert.equal(fs.existsSync(path.join(rootfs, 'etc/swir/repository-trust-policy.json')), true);
assert.equal(
  fs.readlinkSync(path.join(rootfs, 'etc/systemd/system/multi-user.target.wants/swir-package-transaction.service')),
  '/usr/lib/systemd/system/swir-package-transaction.service',
);

const verified = await verifyPackageUiRuntime({ rootfs, production: false });
assert.equal(verified.ready, true);
assert.deepEqual(verified.blockers, []);

const broker = path.join(rootfs, 'usr/lib/swir/package-broker/ipc/swir-package-transaction-broker.mjs');
fs.appendFileSync(broker, '\n// tamper\n');
const tampered = await verifyPackageUiRuntime({ rootfs, production: false });
assert.equal(tampered.ready, false);
assert(tampered.blockers.includes('file:package-broker'));

const symlinkRoot = path.join(temp, 'rootfs-link');
fs.symlinkSync(rootfs, symlinkRoot);
await assert.rejects(
  () => verifyPackageUiRuntime({ rootfs: symlinkRoot, production: false }),
  error => error.code === 'ROOTFS_INVALID',
);
await assert.rejects(
  () => verifyPackageUiRuntime({ rootfs: path.parse(rootfs).root, production: false }),
  error => error.code === 'REAL_ROOT_TARGET_FORBIDDEN',
);

assert.equal(PackageUiRuntimeProvisioningPolicy.peerAuthorizationRequired, true);
assert.equal(PackageUiRuntimeProvisioningPolicy.runtimeKeyEmbeddedInImage, false);
assert.equal(PackageUiRuntimeProvisioningPolicy.directUiPackageToolsAllowed, false);
assert.equal(PackageUiRuntimeProvisioningPolicy.bootableImageClaim, false);
fs.rmSync(temp, { recursive: true, force: true });
console.log('Package UI runtime image provisioning self-test: OK');
