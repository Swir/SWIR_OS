import assert from 'node:assert/strict';
import {
  createHash,
  generateKeyPairSync,
  sign as signBytes,
  verify as verifyBytes,
} from 'node:crypto';

const ALLOWED_CHANNELS = new Set(['stable', 'preview']);
const ALLOWED_POLICIES = new Set(['automatic', 'notify-only', 'manual']);
const GITHUB_RELEASE_PREFIX = 'https://github.com/Swir/SWIR_OS/releases/download/';

function canonicalize(value) {
  if (Array.isArray(value)) return `[${value.map(canonicalize).join(',')}]`;
  if (value && typeof value === 'object') {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonicalize(value[key])}`).join(',')}}`;
  }
  return JSON.stringify(value);
}

function sha256(buffer) {
  return createHash('sha256').update(buffer).digest('hex');
}

function createFeed({ stableArtifact, previewArtifact }) {
  return {
    schemaVersion: 1,
    repository: 'Swir/SWIR_OS',
    generatedAt: '2026-09-21T00:00:00Z',
    channels: {
      stable: {
        version: '1.7.13',
        url: `${GITHUB_RELEASE_PREFIX}desktop-v1.7.13/SWIR-OS-Desktop.exe`,
        sha256: sha256(stableArtifact),
      },
      preview: {
        version: '0.5.7-preview',
        url: `${GITHUB_RELEASE_PREFIX}desktop-preview-v0.5.7/SWIR-OS-Desktop-preview.exe`,
        sha256: sha256(previewArtifact),
      },
    },
  };
}

function signFeed(feed, privateKey) {
  return signBytes(null, Buffer.from(canonicalize(feed), 'utf8'), privateKey).toString('base64');
}

function assertFeedShape(feed) {
  assert.equal(feed?.schemaVersion, 1, 'unsupported update-feed schema');
  assert.equal(feed?.repository, 'Swir/SWIR_OS', 'unexpected update-feed repository');
  assert.equal(typeof feed?.generatedAt, 'string', 'missing generatedAt');
  assert.ok(!Number.isNaN(Date.parse(feed.generatedAt)), 'invalid generatedAt');

  for (const channel of ALLOWED_CHANNELS) {
    const entry = feed.channels?.[channel];
    assert.ok(entry, `missing ${channel} channel`);
    assert.equal(typeof entry.version, 'string', `missing ${channel} version`);
    assert.ok(entry.version.length > 0, `empty ${channel} version`);
    assert.equal(typeof entry.url, 'string', `missing ${channel} URL`);
    assert.ok(entry.url.startsWith(GITHUB_RELEASE_PREFIX), `${channel} URL must use the canonical GitHub Releases origin`);
    assert.match(entry.sha256 ?? '', /^[a-f0-9]{64}$/u, `${channel} artifact SHA-256 must be lowercase hex`);
  }
}

function verifySignedFeed({ feed, signature, publicKey }) {
  assertFeedShape(feed);
  assert.equal(typeof signature, 'string', 'missing update-feed signature');
  const signatureBytes = Buffer.from(signature, 'base64');
  assert.equal(signatureBytes.length, 64, 'invalid Ed25519 signature length');
  const ok = verifyBytes(null, Buffer.from(canonicalize(feed), 'utf8'), publicKey, signatureBytes);
  assert.equal(ok, true, 'update-feed signature verification failed');
}

function verifyArtifact(feed, channel, artifactBytes) {
  assert.ok(ALLOWED_CHANNELS.has(channel), 'unsupported update channel');
  const expected = feed.channels[channel].sha256;
  const actual = sha256(artifactBytes);
  assert.equal(actual, expected, `${channel} artifact integrity verification failed`);
}

function decideUpdatePolicy({ policy, feedVerified, artifactVerified }) {
  assert.ok(ALLOWED_POLICIES.has(policy), 'unsupported update policy');
  const trusted = feedVerified && artifactVerified;
  if (!trusted) {
    return { action: 'blocked', autoInstall: false, notify: false };
  }
  if (policy === 'automatic') {
    return { action: 'install', autoInstall: true, notify: false };
  }
  if (policy === 'notify-only') {
    return { action: 'notify', autoInstall: false, notify: true };
  }
  return { action: 'manual', autoInstall: false, notify: false };
}

function expectReject(label, fn, pattern) {
  assert.throws(fn, pattern, label);
}

const stableArtifact = Buffer.from('SWIR stable desktop payload fixture\n', 'utf8');
const previewArtifact = Buffer.from('SWIR preview desktop payload fixture\n', 'utf8');
const keys = generateKeyPairSync('ed25519');
const attackerKeys = generateKeyPairSync('ed25519');
const feed = createFeed({ stableArtifact, previewArtifact });
const signature = signFeed(feed, keys.privateKey);

verifySignedFeed({ feed, signature, publicKey: keys.publicKey });
verifyArtifact(feed, 'stable', stableArtifact);
verifyArtifact(feed, 'preview', previewArtifact);

assert.deepEqual(
  decideUpdatePolicy({ policy: 'automatic', feedVerified: true, artifactVerified: true }),
  { action: 'install', autoInstall: true, notify: false },
  'automatic policy may install only verified updates',
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
assert.deepEqual(
  decideUpdatePolicy({ policy: 'automatic', feedVerified: false, artifactVerified: true }),
  { action: 'blocked', autoInstall: false, notify: false },
  'unverified feed must block automatic installation',
);
assert.deepEqual(
  decideUpdatePolicy({ policy: 'automatic', feedVerified: true, artifactVerified: false }),
  { action: 'blocked', autoInstall: false, notify: false },
  'hash mismatch must block automatic installation',
);

const tamperedFeed = structuredClone(feed);
tamperedFeed.channels.stable.version = '9.9.9-attacker';
expectReject(
  'tampered feed must fail signature verification',
  () => verifySignedFeed({ feed: tamperedFeed, signature, publicKey: keys.publicKey }),
  /signature verification failed/u,
);

expectReject(
  'wrong public key must fail signature verification',
  () => verifySignedFeed({ feed, signature, publicKey: attackerKeys.publicKey }),
  /signature verification failed/u,
);

expectReject(
  'missing signature must fail closed',
  () => verifySignedFeed({ feed, signature: '', publicKey: keys.publicKey }),
  /signature length/u,
);

expectReject(
  'tampered artifact must fail SHA-256 verification',
  () => verifyArtifact(feed, 'stable', Buffer.from('tampered payload\n', 'utf8')),
  /artifact integrity verification failed/u,
);

const rewrittenHashFeed = structuredClone(feed);
rewrittenHashFeed.channels.stable.sha256 = sha256(Buffer.from('tampered payload\n', 'utf8'));
expectReject(
  'attacker cannot rewrite artifact hash without invalidating feed signature',
  () => verifySignedFeed({ feed: rewrittenHashFeed, signature, publicKey: keys.publicKey }),
  /signature verification failed/u,
);

const wrongOriginFeed = structuredClone(feed);
wrongOriginFeed.channels.preview.url = 'https://example.invalid/SWIR-OS-Desktop-preview.exe';
const wrongOriginSignature = signFeed(wrongOriginFeed, keys.privateKey);
expectReject(
  'feed signed by a trusted key still must use the canonical GitHub Releases origin',
  () => verifySignedFeed({ feed: wrongOriginFeed, signature: wrongOriginSignature, publicKey: keys.publicKey }),
  /canonical GitHub Releases origin/u,
);

expectReject(
  'unknown channel must fail closed',
  () => verifyArtifact(feed, 'nightly', previewArtifact),
  /unsupported update channel/u,
);

expectReject(
  'unknown update policy must fail closed',
  () => decideUpdatePolicy({ policy: 'silent', feedVerified: true, artifactVerified: true }),
  /unsupported update policy/u,
);

console.log('Desktop signed update-feed security regression tests: OK');
