import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { promoteFeed } from './promote-desktop-update-feed.mjs';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-feed-test-'));
let passed = 0;
const expect = (condition, message) => { if (!condition) throw new Error(message); passed += 1; console.log(`PASS ${message}`); };
const expectThrow = (fn, fragment) => { try { fn(); } catch (error) { expect(String(error.message).includes(fragment), `rejects: ${fragment}`); return; } throw new Error(`Expected rejection containing ${fragment}`); };
const makeEnvelope = (version, channel = 'preview', suffix = '') => {
  const tag = `desktop-v${version}-${channel}`;
  const payload = { Schema: 'swir.desktop-update/0.1', Version: version, Channel: channel, PublishedAt: '2026-09-16T12:00:00Z', Package: { Url: `https://github.com/Swir/SWIR_OS/releases/download/${tag}/SWIR-Desktop-${version}-${channel}.zip`, Sha256: 'a'.repeat(64), Size: 123456 } };
  return JSON.stringify({ Schema: 'swir.update-envelope/0.1', Algorithm: 'RSA-PSS-SHA256', KeyId: `test${suffix}`, Payload: Buffer.from(JSON.stringify(payload)).toString('base64'), Signature: Buffer.from(`signature${suffix}`).toString('base64') });
};

try {
  const output = path.join(root, 'updates', 'preview', 'desktop-update-preview.json');
  const incoming57 = path.join(root, '057.json');
  fs.writeFileSync(incoming57, makeEnvelope('0.5.7'));
  let result = promoteFeed({ incomingPath: incoming57, outputPath: output, channel: 'preview', tag: 'desktop-v0.5.7-preview' });
  expect(result.changed && result.version === '0.5.7', 'first release creates feed');
  result = promoteFeed({ incomingPath: incoming57, outputPath: output, channel: 'preview', tag: 'desktop-v0.5.7-preview' });
  expect(!result.changed, 'same envelope is idempotent');

  const incoming58 = path.join(root, '058.json');
  fs.writeFileSync(incoming58, makeEnvelope('0.5.8'));
  result = promoteFeed({ incomingPath: incoming58, outputPath: output, channel: 'preview', tag: 'desktop-v0.5.8-preview' });
  expect(result.changed && result.version === '0.5.8', 'newer release advances feed');
  expectThrow(() => promoteFeed({ incomingPath: incoming57, outputPath: output, channel: 'preview', tag: 'desktop-v0.5.7-preview' }), 'Refusing feed downgrade');

  const conflict = path.join(root, 'conflict.json');
  fs.writeFileSync(conflict, makeEnvelope('0.5.8', 'preview', '-other'));
  expectThrow(() => promoteFeed({ incomingPath: conflict, outputPath: output, channel: 'preview', tag: 'desktop-v0.5.8-preview' }), 'Refusing conflicting envelope');

  const badUrl = path.join(root, 'bad-url.json');
  const badEnvelope = JSON.parse(makeEnvelope('0.5.9'));
  const badPayload = JSON.parse(Buffer.from(badEnvelope.Payload, 'base64').toString('utf8'));
  badPayload.Package.Url = 'https://github.com/Swir/SWIR_OS/releases/download/desktop-v0.5.9-preview/wrong.zip';
  badEnvelope.Payload = Buffer.from(JSON.stringify(badPayload)).toString('base64');
  fs.writeFileSync(badUrl, JSON.stringify(badEnvelope));
  expectThrow(() => promoteFeed({ incomingPath: badUrl, outputPath: output, channel: 'preview', tag: 'desktop-v0.5.9-preview' }), 'does not match the immutable');

  console.log(`SWIR Desktop GitHub feed self-tests passed: ${passed}`);
} finally { fs.rmSync(root, { recursive: true, force: true }); }
