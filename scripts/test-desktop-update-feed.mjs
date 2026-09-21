import crypto from 'node:crypto';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { promoteFeed } from './promote-desktop-update-feed.mjs';

const root = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-feed-test-'));
let passed = 0;
const expect = (condition, message) => { if (!condition) throw new Error(message); passed += 1; console.log(`PASS ${message}`); };
const expectThrow = (fn, fragment) => { try { fn(); } catch (error) { expect(String(error.message).includes(fragment), `rejects: ${fragment}`); return; } throw new Error(`Expected rejection containing ${fragment}`); };

const keyPair = crypto.generateKeyPairSync('rsa', {
  modulusLength: 2048,
  publicKeyEncoding: { type: 'spki', format: 'pem' },
  privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
});
const otherKeyPair = crypto.generateKeyPairSync('rsa', {
  modulusLength: 2048,
  publicKeyEncoding: { type: 'spki', format: 'pem' },
  privateKeyEncoding: { type: 'pkcs8', format: 'pem' },
});
const keyId = 'test-release-key';
const publicKeyPath = path.join(root, 'release-public.pem');
const otherPublicKeyPath = path.join(root, 'other-public.pem');
fs.writeFileSync(publicKeyPath, keyPair.publicKey);
fs.writeFileSync(otherPublicKeyPath, otherKeyPair.publicKey);

const packageBytes = Buffer.from('SWIR-DESKTOP-TEST-PACKAGE-v1', 'utf8');
const packagePathFor = (version, channel = 'preview') => path.join(root, `SWIR-Desktop-${version}-${channel}.zip`);

const makeEnvelope = (version, channel = 'preview', options = {}) => {
  const tag = `desktop-v${version}-${channel}`;
  const packageBytesForEnvelope = options.packageBytes ?? packageBytes;
  const payload = {
    Schema: 'swir.desktop-update/0.1',
    Version: version,
    Channel: channel,
    PublishedAt: options.publishedAt ?? '2026-09-16T12:00:00Z',
    Package: {
      Url: options.packageUrl ?? `https://github.com/Swir/SWIR_OS/releases/download/${tag}/SWIR-Desktop-${version}-${channel}.zip`,
      Sha256: crypto.createHash('sha256').update(packageBytesForEnvelope).digest('hex'),
      Size: packageBytesForEnvelope.length,
    },
  };
  const payloadBytes = Buffer.from(JSON.stringify(payload), 'utf8');
  const signer = options.privateKey ?? keyPair.privateKey;
  const signature = crypto.sign('sha256', payloadBytes, {
    key: signer,
    padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
    saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
  });
  return JSON.stringify({
    Schema: 'swir.update-envelope/0.1',
    Algorithm: 'RSA-PSS-SHA256',
    KeyId: options.keyId ?? keyId,
    Payload: payloadBytes.toString('base64'),
    Signature: signature.toString('base64'),
  });
};

const writeCandidate = (version, options = {}) => {
  const channel = options.channel ?? 'preview';
  const packagePath = packagePathFor(version, channel);
  fs.writeFileSync(packagePath, options.actualPackageBytes ?? options.packageBytes ?? packageBytes);
  const incomingPath = path.join(root, `${version}-${channel}-${Math.random().toString(16).slice(2)}.json`);
  fs.writeFileSync(incomingPath, makeEnvelope(version, channel, options));
  return { incomingPath, packagePath, tag: `desktop-v${version}-${channel}`, channel };
};

const promote = (candidate, outputPath, overrides = {}) => promoteFeed({
  incomingPath: candidate.incomingPath,
  outputPath,
  channel: candidate.channel,
  tag: candidate.tag,
  publicKeyPath: overrides.publicKeyPath ?? publicKeyPath,
  expectedKeyId: overrides.expectedKeyId ?? keyId,
  packagePath: candidate.packagePath,
});

try {
  const output = path.join(root, 'updates', 'preview', 'desktop-update-preview.json');

  const candidate57 = writeCandidate('0.5.7');
  let result = promote(candidate57, output);
  expect(result.changed && result.version === '0.5.7', 'first cryptographically verified release creates feed');
  result = promote(candidate57, output);
  expect(!result.changed, 'same verified envelope is idempotent');

  const candidate58 = writeCandidate('0.5.8');
  result = promote(candidate58, output);
  expect(result.changed && result.version === '0.5.8', 'newer verified release advances feed');
  expectThrow(() => promote(candidate57, output), 'Refusing feed downgrade');

  const trustedCurrent = fs.readFileSync(output, 'utf8');
  const candidate59ForCurrentTrust = writeCandidate('0.5.9');
  const tamperedCurrent = JSON.parse(trustedCurrent);
  const tamperedCurrentPayload = JSON.parse(Buffer.from(tamperedCurrent.Payload, 'base64').toString('utf8'));
  tamperedCurrentPayload.PublishedAt = '2026-09-18T00:00:00Z';
  tamperedCurrent.Payload = Buffer.from(JSON.stringify(tamperedCurrentPayload)).toString('base64');
  fs.writeFileSync(output, `${JSON.stringify(tamperedCurrent)}\n`);
  const tamperedCurrentSnapshot = fs.readFileSync(output, 'utf8');
  expectThrow(() => promote(candidate59ForCurrentTrust, output), 'Existing published feed trust verification failed');
  expect(fs.readFileSync(output, 'utf8') === tamperedCurrentSnapshot, 'tampered existing feed is never overwritten automatically');
  fs.writeFileSync(output, trustedCurrent);

  fs.writeFileSync(output, '{"Schema":"broken-current-feed"}\n');
  const malformedCurrentSnapshot = fs.readFileSync(output, 'utf8');
  expectThrow(() => promote(candidate59ForCurrentTrust, output), 'Existing published feed is invalid');
  expect(fs.readFileSync(output, 'utf8') === malformedCurrentSnapshot, 'malformed existing feed is never overwritten automatically');
  fs.writeFileSync(output, trustedCurrent);

  const conflict = writeCandidate('0.5.8', { publishedAt: '2026-09-16T12:01:00Z' });
  expectThrow(() => promote(conflict, output), 'Refusing conflicting envelope');

  const badUrl = writeCandidate('0.5.9', { packageUrl: 'https://github.com/Swir/SWIR_OS/releases/download/desktop-v0.5.9-preview/wrong.zip' });
  expectThrow(() => promote(badUrl, output), 'does not match the immutable');

  const tampered = writeCandidate('0.5.9');
  const tamperedEnvelope = JSON.parse(fs.readFileSync(tampered.incomingPath, 'utf8'));
  const tamperedPayload = JSON.parse(Buffer.from(tamperedEnvelope.Payload, 'base64').toString('utf8'));
  tamperedPayload.PublishedAt = '2026-09-17T00:00:00Z';
  tamperedEnvelope.Payload = Buffer.from(JSON.stringify(tamperedPayload)).toString('base64');
  fs.writeFileSync(tampered.incomingPath, JSON.stringify(tamperedEnvelope));
  const beforeTamper = fs.readFileSync(output, 'utf8');
  expectThrow(() => promote(tampered, output), 'RSA-PSS signature verification failed');
  expect(fs.readFileSync(output, 'utf8') === beforeTamper, 'signature failure leaves published feed unchanged');

  const wrongKey = writeCandidate('0.5.9');
  expectThrow(() => promote(wrongKey, output, { publicKeyPath: otherPublicKeyPath }), 'RSA-PSS signature verification failed');

  const wrongKeyId = writeCandidate('0.5.9', { keyId: 'unexpected-key' });
  expectThrow(() => promote(wrongKeyId, output), 'does not match pinned key id');

  const missingSignature = writeCandidate('0.5.9');
  const unsignedEnvelope = JSON.parse(fs.readFileSync(missingSignature.incomingPath, 'utf8'));
  unsignedEnvelope.Signature = '';
  fs.writeFileSync(missingSignature.incomingPath, JSON.stringify(unsignedEnvelope));
  expectThrow(() => promote(missingSignature, output), 'not valid canonical base64');

  const hashMismatch = writeCandidate('0.5.9', { actualPackageBytes: Buffer.from('TAMPERED-RELEASE-ASSET', 'utf8') });
  const beforeHashFailure = fs.readFileSync(output, 'utf8');
  expectThrow(() => promote(hashMismatch, output), 'size does not match signed payload');
  expect(fs.readFileSync(output, 'utf8') === beforeHashFailure, 'artifact verification failure leaves published feed unchanged');

  const sameSizeTamper = Buffer.from(packageBytes);
  sameSizeTamper[0] ^= 0x01;
  const sameSizeHashMismatch = writeCandidate('0.5.9', { actualPackageBytes: sameSizeTamper });
  expectThrow(() => promote(sameSizeHashMismatch, output), 'SHA-256 does not match signed payload');

  console.log(`SWIR Desktop GitHub feed self-tests passed: ${passed}`);
} finally { fs.rmSync(root, { recursive: true, force: true }); }
