import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  buildCompatibilityLaunchPlan,
  prepareManagedPrefix
} from '../../system/runtime/windows-compatibility-service.mjs';

const APP_ID = 'info.swir.konofixchat';
const PROVIDER = 'swir.compat.wine';
const root = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-konofix-system-contract-'));

try {
  const prefixRoot = path.join(root, 'prefixes');
  const runtimeRoot = path.join(root, 'runtime');
  fs.mkdirSync(runtimeRoot, { recursive: true, mode: 0o700 });
  const wine = path.join(runtimeRoot, 'wine');
  fs.writeFileSync(wine, '#!/bin/sh\nexit 0\n', { mode: 0o755 });

  const prefix = path.join(prefixRoot, APP_ID);
  const entryPoint = path.join(prefix, 'drive_c', 'users', 'swir', 'AppData', 'Local', 'Konofix Chat', 'konofix-chat.exe');
  const manifest = {
    schema: 'swir.package-provider/0.2',
    id: APP_ID,
    targetEditions: ['system'],
    executionClass: 'windows-compat',
    provider: PROVIDER,
    package: {
      name: 'Konofix Chat',
      version: '0.5.1',
      channel: 'stable',
      nativeEntryPoint: entryPoint
    },
    compatibility: {
      prefixPolicy: 'per-app',
      windowsArchitecture: 'win64',
      runtimeChannel: 'system-managed'
    },
    trust: {
      sourceClass: 'swir-signed',
      repositoryId: 'official',
      signatureRequired: true
    },
    permissions: [],
    rollback: true
  };

  const prepared = prepareManagedPrefix(manifest, { trustVerified: true, prefixRoot });
  assert.equal(prepared.prefix, fs.realpathSync(prefix));
  fs.mkdirSync(path.dirname(entryPoint), { recursive: true, mode: 0o700 });
  fs.writeFileSync(entryPoint, Buffer.from('MZ synthetic contract fixture; never executed'), { mode: 0o600 });

  const plan = buildCompatibilityLaunchPlan(manifest, {
    trustVerified: true,
    prefixRoot,
    runtimePaths: { [PROVIDER]: wine },
    runtimeRoots: [runtimeRoot],
    environment: {
      HOME: path.join(root, 'home'),
      USER: 'swir',
      LANG: 'C.UTF-8',
      LD_PRELOAD: '/tmp/forbidden.so',
      NODE_OPTIONS: '--require=/tmp/forbidden.js',
      WINEPREFIX: '/tmp/caller-prefix'
    }
  });

  assert.equal(plan.appId, APP_ID);
  assert.equal(plan.provider, PROVIDER);
  assert.equal(plan.executionClass, 'windows-compat');
  assert.equal(plan.prefixPolicy, 'per-app');
  assert.equal(plan.shell, false);
  assert.equal(plan.brokerRequired, true);
  assert.equal(plan.trust.verified, true);
  assert.equal(plan.trust.signatureRequired, true);
  assert.equal(plan.application.executable, fs.realpathSync(entryPoint));
  assert.equal(plan.runtime.executable, fs.realpathSync(wine));
  assert.deepEqual(plan.runtime.args, [fs.realpathSync(entryPoint)]);
  assert.equal(plan.environment.WINEPREFIX, fs.realpathSync(prefix));
  assert.equal(plan.environment.WINEARCH, 'win64');
  assert.equal('LD_PRELOAD' in plan.environment, false);
  assert.equal('NODE_OPTIONS' in plan.environment, false);

  assert.throws(() => buildCompatibilityLaunchPlan(manifest, {
    trustVerified: false,
    prefixRoot,
    runtimePaths: { [PROVIDER]: wine },
    runtimeRoots: [runtimeRoot]
  }), /trust must be verified/i);

  const installer = path.join(prefix, 'setup.msi');
  fs.writeFileSync(installer, Buffer.from('synthetic installer fixture'), { mode: 0o600 });
  assert.throws(() => buildCompatibilityLaunchPlan({
    ...manifest,
    package: { ...manifest.package, nativeEntryPoint: installer }
  }, {
    trustVerified: true,
    prefixRoot,
    runtimePaths: { [PROVIDER]: wine },
    runtimeRoots: [runtimeRoot]
  }), /accepts \.exe\/\.com user applications only/i);

  const escaped = path.join(root, 'outside', 'konofix-chat.exe');
  fs.mkdirSync(path.dirname(escaped), { recursive: true });
  fs.writeFileSync(escaped, Buffer.from('MZ outside fixture'), { mode: 0o600 });
  assert.throws(() => buildCompatibilityLaunchPlan({
    ...manifest,
    package: { ...manifest.package, nativeEntryPoint: escaped }
  }, {
    trustVerified: true,
    prefixRoot,
    runtimePaths: { [PROVIDER]: wine },
    runtimeRoots: [runtimeRoot]
  }), /outside its managed prefix/i);

  console.log('Konofix System Edition managed-Wine contract passed (structural only; real GUI qualification still required).');
} finally {
  fs.rmSync(root, { recursive: true, force: true });
}
