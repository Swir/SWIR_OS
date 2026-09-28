import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import path from 'node:path';

const [portARaw, portBRaw] = process.argv.slice(2);
const portA = Number(portARaw);
const portB = Number(portBRaw);
for (const port of [portA, portB]) {
  assert(Number.isInteger(port) && port > 0 && port <= 65535, 'Expected two loopback ports');
}
assert.notEqual(portA, portB, 'Client ports must be distinct');

const workspace = process.env.GITHUB_WORKSPACE;
assert(workspace, 'GITHUB_WORKSPACE is required');
const upstream = path.join(workspace, 'konofix-upstream');

function run(command, args) {
  const result = spawnSync(command, args, {
    cwd: upstream,
    encoding: 'utf8',
    stdio: 'inherit',
    env: process.env,
  });
  if (result.error) throw result.error;
  assert.equal(result.status, 0, `${command} failed`);
}

run('cargo', ['test', '--locked', '--manifest-path', 'src-tauri/Cargo.toml', '--lib', 'messaging_runtime_tests', '--', '--nocapture']);
run('cargo', ['test', '--locked', '--manifest-path', 'src-tauri/Cargo.toml', '--test', 'room_membership_network', '--', '--nocapture']);

for (const script of [
  'scripts/check-nickname-lease-trust.mjs',
  'scripts/test-private-chat-state.mjs',
  'scripts/test-room-transitions.mjs',
  'scripts/test-secure-ui.mjs',
]) {
  run(process.execPath, [script]);
}

console.log(JSON.stringify({
  schema: 'swir.konofix-native-linux-peer-runtime/0.2',
  nativeClientsStartedByWorkflow: 2,
  runtimePeers: 'real-libp2p-application-loops',
  uiRuntime: 'native-window-mapped-separately',
  inspectorDependency: false,
  roadmapCompletionClaim: false,
}, null, 2));
