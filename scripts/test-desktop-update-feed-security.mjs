import assert from 'node:assert/strict';
import {
  constants,
  createHash,
  generateKeyPairSync,
  sign as signBytes,
  verify as verifyBytes,
} from 'node:crypto';

const ENVELOPE_SCHEMA = 'swir.update-envelope/0.1';
const PAYLOAD_SCHEMA = 'swir.desktop-update/0.1';
const SIGNATURE_ALGORITHM = 'RSA-PSS-SHA256';
const ALLOWED_CHANNELS = new Set(['stable', 'preview']);
const ALLOWED_POLICIES = new Set(['automatic', 'notify-only', 'manual']);
const GITHUB_RELEASE_PREFIX = '/Swir/SWIR_OS/releases/download/';
const MAX_PACKAGE_BYTES = 512 * 1024 * 1024;

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

function expectedPackageUrl(version, channel) {
  const tag = `desktop-v${version}-${channel}`;
  const file = `SWIR-Desktop-${version}-${channel}.zip`;
  return `https://github.com${GITHUB_RELEASE_PREFIX}${tag}/${file}`;
}

function createPayload({ version, channel, artifact }) {
  assert.ok(ALLOWED_CHANNELS.has(channel), 'unsupported update channel');
  return {
    Schema: PAYLOAD_SCHEMA,
    Version: version,
    Channel: channel,
    PublishedAt: '2026-09-21T00:00:00Z',
    Package: {
      Url: expectedPackageUrl(version, channel),
      Sha256: sha256(artifact),
      Size: artifact.length,
    },
  };
}

function signPayload(payloadBytes, privateKey) {
  return signBytes('sha256', payloadBytes, {
    key: privateKey,
    padding: constants.RSA_PKCS1_PSS_PADDING,
    saltLength: constants.RSA_PSS_SALTLEN_DIGEST,
  });
}

function createEnvelope(payload, privateKey, { algorithm = SIGNATURE_ALGORITHM, keyId = 'test-release-rsa-2026' } = {}) {
  const payloadBytes = Buffer.from(JSON.stringify(payload), 'utf8');
  const signature = signPayload(payloadBytes, privateKey);
  return {
    Schema: ENVELOPE_SCHEMA,
    Algorithm: algorithm,
    KeyId: keyId,
    Payload: payloadBytes.toString('base64'),
    Signature: signature.toString('base64'),
  };
}

function validateOfficialReleaseUrl(url, version, channel) {
  let parsed;
  try { parsed = new URL(url); }
  catch { throw new Error('update package URL is invalid'); }

  assert.equal(parsed.protocol, 'https:', 'update package URL must use HTTPS');
  assert.equal(parsed.hostname.toLowerCase(), 'github.com', 'update package URL must use github.com');
  assert.equal(parsed.port, '', 'update package URL must use the default HTTPS port');
  assert.equal(parsed.username, '', 'update package URL must not contain credentials');
  assert.equal(parsed.password, '', 'update package URL must not contain credentials');
  assert.equal(parsed.search, '', 'update package URL must not contain a query');
  assert.equal(parsed.hash, '', 'update package URL must not contain a fragment');
  assert.ok(parsed.pathname.startsWith(GITHUB_RELEASE_PREFIX), 'update package URL is outside the canonical SWIR GitHub Release path');
  assert.ok(!/%2f|%5c/iu.test(parsed.pathname), 'update package URL contains an encoded path separator');
  assert.equal(url, expectedPackageUrl(version, channel), 'update package URL does not match the immutable release asset');
}

function decodeAndVerifyEnvelope(envelope, publicKey, expectedChannel) {
  assert.equal(envelope?.Schema, ENVELOPE_SCHEMA, 'unsupported update envelope schema');
  assert.equal(envelope?.Algorithm, SIGNATURE_ALGORITHM, 'unsupported update signature algorithm');
  assert.equal(typeof envelope?.KeyId, 'string', 'missing update key id');
  assert.ok(envelope.KeyId.trim().length > 0 && envelope.KeyId.length <= 128, 'invalid update key id');
  assert.equal(typeof envelope?.Payload, 'string', 'missing signed payload');
  assert.equal(typeof envelope?.Signature, 'string', 'missing update signature');

  const payloadBytes = Buffer.from(envelope.Payload, 'base64');
  const signatureBytes = Buffer.from(envelope.Signature, 'base64');
  assert.ok(payloadBytes.length >= 2 && payloadBytes.length <= 128 * 1024, 'signed payload size is outside the allowed range');
  assert.ok(signatureBytes.length > 0, 'missing update signature');

  const verified = verifyBytes('sha256', payloadBytes, {
    key: publicKey,
    padding: constants.RSA_PKCS1_PSS_PADDING,
    saltLength: constants.RSA_PSS_SALTLEN_DIGEST,
  }, signatureBytes);
  assert.equal(verified, true, 'update signature verification failed');

  const payload = JSON.parse(payloadBytes.toString('utf8'));
  assert.equal(payload?.Schema, PAYLOAD_SCHEMA, 'unsupported signed update payload schema');
  assert.equal(payload?.Channel, expectedChannel, 'update manifest channel mismatch');
  assert.ok(ALLOWED_CHANNELS.has(payload.Channel), 'unsupported update channel');
  assert.match(payload?.Version ?? '', /^\d+\.\d+\.\d+(?:\.\d+)?$/u, 'invalid update version');
  assert.ok(!Number.isNaN(Date.parse(payload?.PublishedAt ?? '')), 'invalid update publication timestamp');
  assert.ok(payload?.Package && typeof payload.Package === 'object', 'missing update package metadata');
  assert.match(payload.Package.Sha256 ?? '', /^[a-f0-9]{64}$/u, 'invalid update package SHA-256');
  assert.ok(Number.isSafeInteger(payload.Package.Size) && payload.Package.Size > 0 && payload.Package.Size <= MAX_PACKAGE_BYTES, 'invalid update package size');
  validateOfficialReleaseUrl(payload.Package.Url, payload.Version, payload.Channel);
  return payload;
}

function verifyArtifact(payload, artifactBytes) {
  assert.equal(artifactBytes.length, payload.Package.Size, 'update artifact size verification failed');
  assert.equal(sha256(artifactBytes), payload.Package.Sha256, 'update artifact integrity verification failed');
}

function decideUpdatePolicy({ policy, feedVerified, artifactVerified }) {
  assert.ok(ALLOWED_POLICIES.has(policy), 'unsupported update policy');
  if (!(feedVerified && artifactVerified)) {
    return { action: 'blocked', autoInstall: false, notify: false };
  }
  if (policy === 'automatic') return { action: 'install', autoInstall: true, notify: false };
  if (policy === 'notify-only') return { action: 'notify', autoInstall: false, notify: true };
  return { action: 'manual', autoInstall: false, notify: false };
}

function expectReject(label, fn, pattern) {
  assert.throws(fn, pattern, label);
}

const stableArtifact = Buffer.from('SWIR stable desktop payload fixture\n', 'utf8');
const previewArtifact = Buffer.from('SWIR preview desktop payload fixture\n', 'utf8');
const keys = generateKeyPairSync('rsa', { modulusLength: 2048 });
const attackerKeys = generateKeyPairSync('rsa', { modulusLength: 2048 });
const stablePayload = createPayload({ version: '1.7.13', channel: 'stable', artifact: stableArtifact });
const previewPayload = createPayload({ version: '0.5.7', channel: 'preview', artifact: previewArtifact });
const stableEnvelope = createEnvelope(stablePayload, keys.privateKey);
const previewEnvelope = createEnvelope(previewPayload, keys.privateKey);

const verifiedStable = decodeAndVerifyEnvelope(stableEnvelope, keys.publicKey, 'stable');
const verifiedPreview = decodeAndVerifyEnvelope(previewEnvelope, keys.publicKey, 'preview');
verifyArtifact(verifiedStable, stableArtifact);
verifyArtifact(verifiedPreview, previewArtifact);

assert.deepEqual(
  decideUpdatePolicy({ policy: 'automatic', feedVerified: true, artifactVerified: true }),
  { action: 'install', autoInstall: true, notify: false },
  'automatic policy may install only fully verified updates',
);
assert.deepEqual(
  decideUpdatePolicy({ policy: 'notify-only', feedVerified: true, artifactVerified: true }),
  { action: 'notify', autoInstall: false, notify: true },
  'notify-only policy must never auto-install',
);
assert.deepEqual(
  decideUpdatePolicy({ policy: 'manual', feedVerified: true, artifactVerified: true }),
  { action: 'manual', autoInstall: false, notify: false },
  'manual policy must never auto-install',
);
for (const [feedVerified, artifactVerified] of [[false, true], [true, false], [false, false]]) {
  assert.deepEqual(
    decideUpdatePolicy({ policy: 'automatic', feedVerified, artifactVerified }),
    { action: 'blocked', autoInstall: false, notify: false },
    'automatic policy must fail closed before feed and artifact verification both succeed',
  );
}

const tamperedPayloadEnvelope = structuredClone(stableEnvelope);
const tamperedPayload = JSON.parse(Buffer.from(tamperedPayloadEnvelope.Payload, 'base64').toString('utf8'));
tamperedPayload.Version = '9.9.9';
tamperedPayloadEnvelope.Payload = Buffer.from(JSON.stringify(tamperedPayload), 'utf8').toString('base64');
expectReject(
  'tampered signed payload must fail RSA-PSS verification',
  () => decodeAndVerifyEnvelope(tamperedPayloadEnvelope, keys.publicKey, 'stable'),
  /signature verification failed/u,
);

expectReject(
  'wrong RSA public key must fail signature verification',
  () => decodeAndVerifyEnvelope(stableEnvelope, attackerKeys.publicKey, 'stable'),
  /signature verification failed/u,
);

const missingSignature = structuredClone(stableEnvelope);
missingSignature.Signature = '';
expectReject(
  'missing signature must fail closed',
  () => decodeAndVerifyEnvelope(missingSignature, keys.publicKey, 'stable'),
  /missing update signature/u,
);

const wrongAlgorithm = structuredClone(stableEnvelope);
wrongAlgorithm.Algorithm = 'RSA-PKCS1-SHA256';
expectReject(
  'algorithm downgrade must fail closed before signature acceptance',
  () => decodeAndVerifyEnvelope(wrongAlgorithm, keys.publicKey, 'stable'),
  /unsupported update signature algorithm/u,
);

const emptyKeyId = structuredClone(stableEnvelope);
emptyKeyId.KeyId = '   ';
expectReject(
  'empty key id must fail closed',
  () => decodeAndVerifyEnvelope(emptyKeyId, keys.publicKey, 'stable'),
  /invalid update key id/u,
);

expectReject(
  'channel mismatch must fail closed',
  () => decodeAndVerifyEnvelope(previewEnvelope, keys.publicKey, 'stable'),
  /channel mismatch/u,
);

expectReject(
  'tampered artifact must fail SHA-256 verification',
  () => verifyArtifact(verifiedStable, Buffer.from('tampered payload\n', 'utf8')),
  /size verification failed|integrity verification failed/u,
);

const rewrittenHashPayload = structuredClone(stablePayload);
const tamperedArtifact = Buffer.from('tampered payload with matching size!!!\n', 'utf8');
rewrittenHashPayload.Package.Sha256 = sha256(tamperedArtifact);
rewrittenHashPayload.Package.Size = tamperedArtifact.length;
const unsignedHashRewrite = structuredClone(stableEnvelope);
unsignedHashRewrite.Payload = Buffer.from(JSON.stringify(rewrittenHashPayload), 'utf8').toString('base64');
expectReject(
  'attacker cannot rewrite package integrity metadata without the release signing key',
  () => decodeAndVerifyEnvelope(unsignedHashRewrite, keys.publicKey, 'stable'),
  /signature verification failed/u,
);

const wrongOriginPayload = structuredClone(previewPayload);
wrongOriginPayload.Package.Url = 'https://example.invalid/SWIR-Desktop-0.5.7-preview.zip';
const wrongOriginEnvelope = createEnvelope(wrongOriginPayload, keys.privateKey);
expectReject(
  'even correctly signed metadata cannot redirect packages off canonical SWIR GitHub Releases',
  () => decodeAndVerifyEnvelope(wrongOriginEnvelope, keys.publicKey, 'preview'),
  /must use github\.com/u,
);

const queryPayload = structuredClone(previewPayload);
queryPayload.Package.Url += '?download=1';
const queryEnvelope = createEnvelope(queryPayload, keys.privateKey);
expectReject(
  'signed package URLs with query strings are not immutable canonical release asset URLs',
  () => decodeAndVerifyEnvelope(queryEnvelope, keys.publicKey, 'preview'),
  /must not contain a query/u,
);

const encodedSeparatorPayload = structuredClone(previewPayload);
encodedSeparatorPayload.Package.Url = `https://github.com${GITHUB_RELEASE_PREFIX}desktop-v0.5.7-preview%2fother/SWIR-Desktop-0.5.7-preview.zip`;
const encodedSeparatorEnvelope = createEnvelope(encodedSeparatorPayload, keys.privateKey);
expectReject(
  'signed package URLs with encoded separators fail closed',
  () => decodeAndVerifyEnvelope(encodedSeparatorEnvelope, keys.publicKey, 'preview'),
  /encoded path separator|immutable release asset/u,
);

expectReject(
  'unknown update policy must fail closed',
  () => decideUpdatePolicy({ policy: 'silent', feedVerified: true, artifactVerified: true }),
  /unsupported update policy/u,
);

console.log('Desktop RSA-PSS signed update-feed security regression tests: OK');
