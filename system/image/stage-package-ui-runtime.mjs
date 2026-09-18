#!/usr/bin/env node
import path from 'node:path';
import { stagePackageUiRuntime } from './system-package-ui-runtime-provisioning.mjs';

function usage() {
  console.error('Usage: stage-package-ui-runtime.mjs --rootfs <absolute-path> --source-root <absolute-path> [--production]');
}

let rootfs = '';
let sourceRoot = '';
let production = false;
for (let index = 2; index < process.argv.length; index += 1) {
  const argument = process.argv[index];
  if (argument === '--rootfs') rootfs = process.argv[++index] || '';
  else if (argument === '--source-root') sourceRoot = process.argv[++index] || '';
  else if (argument === '--production') production = true;
  else { usage(); process.exit(64); }
}
if (!path.isAbsolute(rootfs) || rootfs === '/' || !path.isAbsolute(sourceRoot)) {
  usage();
  process.exit(64);
}

try {
  const result = await stagePackageUiRuntime({ rootfs, sourceRoot, production });
  console.log(JSON.stringify({
    schema: result.schema,
    ready: result.ready,
    production: result.production,
    packageBrokerServiceEnabled: result.packageBrokerServiceEnabled,
    peerAuthorizationRequired: true,
    runtimeKeyEmbeddedInImage: result.runtimeKeyEmbeddedInImage,
    directUiPackageToolsAllowed: result.directUiPackageToolsAllowed,
  }));
} catch (error) {
  console.error(`SWIR package UI runtime staging failed [${error?.code || error?.name || 'ERROR'}]: ${error?.message || error}`);
  process.exit(70);
}
