import crypto from 'node:crypto';
import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const ENVELOPE_SCHEMA = 'swir.update-envelope/0.1';
const PAYLOAD_SCHEMA = 'swir.desktop-update/0.1';
const ALGORITHM = 'RSA-PSS-SHA256';
const VERSION_RE = /^([0-9]+)\.([0-9]+)\.([0-9]+)$/;
const SHA256_RE = /^[a-f0-9]{64}$/;
const BASE64_RE = /^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/;

function decodeBase64(value, label) {
  if (typeof value !== 'string' || value.length === 0 || !BASE64_RE.test(value)) {
    throw new Error(`${label} is not valid canonical base64.`);
  }
  return Buffer.from(value, 'base64');
}

export function parseEnvelope(text, expectedChannel, expectedTag) {
  let envelope;
  try { envelope = JSON.parse(text); } catch { throw new Error('Incoming update envelope is not valid JSON.'); }
  if (!envelope || envelope.Schema !== ENVELOPE_SCHEMA || envelope.Algorithm !== ALGORITHM) throw new Error('Incoming update envelope schema/algorithm mismatch.');
  if (typeof envelope.KeyId !== 'string' || envelope.KeyId.length < 1 || envelope.KeyId.length > 128) throw new Error('Incoming update envelope key id is invalid.');
  const payloadBytes = decodeBase64(envelope.Payload, 'Incoming signed update payload');
  decodeBase64(envelope.Signature, 'Incoming update signature');
  let payload;
  try { payload = JSON.parse(payloadBytes.toString('utf8')); } catch { throw new Error('Incoming signed update payload is not valid base64 JSON.'); }
  if (!payload || payload.Schema !== PAYLOAD_SCHEMA) throw new Error('Incoming signed update payload schema mismatch.');
  if (payload.Channel !== expectedChannel) throw new Error(`Incoming update channel ${payload.Channel ?? '<missing>'} does not match ${expectedChannel}.`);
  const match = VERSION_RE.exec(payload.Version ?? '');
  if (!match) throw new Error('Incoming update version must be a three-part numeric version.');
  const version = match.slice(1).map(Number);
  const tag = `desktop-v${payload.Version}-${expectedChannel}`;
  if (tag !== expectedTag) throw new Error(`Release tag ${expectedTag} does not match signed payload ${tag}.`);
  const expectedPackage = `https://github.com/Swir/SWIR_OS/releases/download/${tag}/SWIR-Desktop-${payload.Version}-${expectedChannel}.zip`;
  if (payload.Package?.Url !== expectedPackage) throw new Error('Signed package URL does not match the immutable SWIR_OS GitHub Release asset.');
  if (!SHA256_RE.test(payload.Package?.Sha256 ?? '')) throw new Error('Signed package SHA-256 is invalid.');
  if (!Number.isSafeInteger(payload.Package?.Size) || payload.Package.Size <= 0) throw new Error('Signed package size is invalid.');
  return { envelope, payload, payloadBytes, version };
}

export function verifyEnvelopeSignature(incoming, publicKeyPem, expectedKeyId) {
  if (typeof expectedKeyId !== 'string' || expectedKeyId.length < 1 || expectedKeyId.length > 128) throw new Error('Pinned update key id is missing or invalid.');
  if (incoming.envelope.KeyId !== expectedKeyId) throw new Error(`Incoming update key id ${incoming.envelope.KeyId} does not match pinned key id ${expectedKeyId}.`);
  let publicKey;
  try { publicKey = crypto.createPublicKey(publicKeyPem); } catch { throw new Error('Pinned update verification public key is invalid.'); }
  if (publicKey.asymmetricKeyType !== 'rsa') throw new Error('Pinned update verification key must be RSA.');
  const signature = decodeBase64(incoming.envelope.Signature, 'Incoming update signature');
  const verified = crypto.verify('sha256', incoming.payloadBytes, {
    key: publicKey,
    padding: crypto.constants.RSA_PKCS1_PSS_PADDING,
    saltLength: crypto.constants.RSA_PSS_SALTLEN_DIGEST,
  }, signature);
  if (!verified) throw new Error('Incoming update envelope RSA-PSS signature verification failed.');
}

export function verifyPackageArtifact(payload, packagePath) {
  const expectedName = path.posix.basename(new URL(payload.Package.Url).pathname);
  if (path.basename(packagePath) !== expectedName) throw new Error(`Release package filename does not match signed payload: expected ${expectedName}.`);
  const stat = fs.statSync(packagePath);
  if (!stat.isFile()) throw new Error('Release package path is not a regular file.');
  if (stat.size !== payload.Package.Size) throw new Error(`Release package size does not match signed payload: expected ${payload.Package.Size}, got ${stat.size}.`);
  const actualSha256 = crypto.createHash('sha256').update(fs.readFileSync(packagePath)).digest('hex');
  const expectedSha256 = payload.Package.Sha256;
  if (!crypto.timingSafeEqual(Buffer.from(actualSha256, 'ascii'), Buffer.from(expectedSha256, 'ascii'))) {
    throw new Error('Release package SHA-256 does not match signed payload.');
  }
  return { sha256: actualSha256, size: stat.size };
}

export function compareVersions(a, b) {
  for (let i = 0; i < 3; i += 1) if (a[i] !== b[i]) return a[i] < b[i] ? -1 : 1;
  return 0;
}

export function promoteFeed({ incomingPath, outputPath, channel, tag, publicKeyPath, expectedKeyId, packagePath }) {
  const incomingText = fs.readFileSync(incomingPath, 'utf8').trim();
  const incoming = parseEnvelope(incomingText, channel, tag);
  const publicKeyPem = fs.readFileSync(publicKeyPath, 'utf8');
  verifyEnvelopeSignature(incoming, publicKeyPem, expectedKeyId);
  const artifact = verifyPackageArtifact(incoming.payload, packagePath);

  if (fs.existsSync(outputPath)) {
    const currentText = fs.readFileSync(outputPath, 'utf8').trim();
    const currentEnvelope = JSON.parse(currentText);
    const currentPayload = JSON.parse(Buffer.from(currentEnvelope.Payload ?? '', 'base64').toString('utf8'));
    const currentMatch = VERSION_RE.exec(currentPayload.Version ?? '');
    if (!currentMatch) throw new Error('Existing feed has an invalid version and must be repaired manually.');
    const currentVersion = currentMatch.slice(1).map(Number);
    const ordering = compareVersions(incoming.version, currentVersion);
    if (ordering < 0) throw new Error(`Refusing feed downgrade ${currentPayload.Version} -> ${incoming.payload.Version}.`);
    if (ordering === 0 && currentText !== incomingText) throw new Error(`Refusing conflicting envelope for already-published version ${incoming.payload.Version}.`);
    if (ordering === 0) return { changed: false, version: incoming.payload.Version, keyId: incoming.envelope.KeyId, sha256: artifact.sha256 };
  }
  fs.mkdirSync(path.dirname(outputPath), { recursive: true });
  fs.writeFileSync(outputPath, `${incomingText}\n`, 'utf8');
  return { changed: true, version: incoming.payload.Version, keyId: incoming.envelope.KeyId, sha256: artifact.sha256 };
}

function arg(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`Missing ${name}.`);
  return process.argv[index + 1];
}

function main() {
  const result = promoteFeed({
    incomingPath: path.resolve(arg('--incoming')),
    outputPath: path.resolve(arg('--output')),
    channel: arg('--channel'),
    tag: arg('--tag'),
    publicKeyPath: path.resolve(arg('--public-key')),
    expectedKeyId: arg('--key-id'),
    packagePath: path.resolve(arg('--package')),
  });
  console.log(JSON.stringify({ schema: 'swir.github-update-feed-promotion/0.2', ...result }));
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { main(); } catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exit(1); }
}
