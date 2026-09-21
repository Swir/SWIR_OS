import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';

const [evidenceArg, storeArg, trustArg, expectedKind = 'contract'] = process.argv.slice(2);
if (!evidenceArg || !storeArg || !trustArg) {
  throw new Error('Usage: node scripts/validate-package-signing-evidence.mjs <evidence.json> <store-dir> <trust-roots.json> [contract|production]');
}
if (!['contract', 'production'].includes(expectedKind)) throw new Error('Expected evidence kind must be contract or production.');

const evidencePath = path.resolve(evidenceArg);
const storeRoot = path.resolve(storeArg);
const trustPath = path.resolve(trustArg);
const readJson = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const sha256Bytes = data => crypto.createHash('sha256').update(data).digest('hex');
const sha256File = file => sha256Bytes(fs.readFileSync(file));
const isHex64 = value => typeof value === 'string' && /^[0-9a-f]{64}$/.test(value);
const safePackagePath = value => typeof value === 'string' && /^packages\/[A-Za-z0-9._-]+\.swirapp$/.test(value);

if (!fs.existsSync(evidencePath) || !fs.statSync(evidencePath).isFile()) throw new Error(`Evidence file is missing: ${evidencePath}`);
if (!fs.existsSync(storeRoot) || !fs.statSync(storeRoot).isDirectory()) throw new Error(`Store directory is missing: ${storeRoot}`);
if (!fs.existsSync(trustPath) || !fs.statSync(trustPath).isFile()) throw new Error(`Trust-root file is missing: ${trustPath}`);

const evidence = readJson(evidencePath);
const trustRaw = fs.readFileSync(trustPath);
const trust = JSON.parse(trustRaw.toString('utf8'));
const artifactMapPath = path.join(storeRoot, 'catalog-artifacts.json');
if (!fs.existsSync(artifactMapPath)) throw new Error('catalog-artifacts.json is missing from Store output.');
const artifactMap = readJson(artifactMapPath);

if (evidence.schema !== 'swir.package-signing-evidence/1.0') throw new Error('Unexpected package signing evidence schema.');
if (evidence.evidenceKind !== expectedKind) throw new Error(`Evidence kind mismatch: expected ${expectedKind}, got ${evidence.evidenceKind}`);
if (typeof evidence.sourceCommit !== 'string' || !/^[0-9a-f]{40}$/.test(evidence.sourceCommit)) throw new Error('Evidence sourceCommit must be exact lowercase 40-hex Git SHA.');
if (typeof evidence.keyId !== 'string' || !/^[A-Za-z0-9._-]{1,128}$/.test(evidence.keyId)) throw new Error('Evidence keyId is invalid.');
if (evidence.algorithm !== 'Ed25519') throw new Error('Evidence algorithm must be Ed25519.');
if (typeof evidence.generatedAt !== 'string' || Number.isNaN(Date.parse(evidence.generatedAt))) throw new Error('Evidence generatedAt is invalid.');

if (trust.schema !== 'swir.package-trust-roots/1.0' || trust.requireSignedPackages !== true || !Array.isArray(trust.roots) || trust.roots.length !== 1) {
  throw new Error('Package trust-root policy must be fail-closed with exactly one signing root for evidence generation.');
}
const root = trust.roots[0];
if (root.keyId !== evidence.keyId || root.algorithm !== 'Ed25519' || root.format !== 'raw' || root.enabled !== true) {
  throw new Error('Evidence key identity does not match enabled raw Ed25519 trust root.');
}
if (!Array.isArray(root.scope) || root.scope.length !== 1 || root.scope[0] !== 'package:swirapp') throw new Error('Package trust root scope must be exactly package:swirapp.');
if (typeof root.publicKey !== 'string') throw new Error('Package trust root publicKey is missing.');
let publicKey;
try { publicKey = Buffer.from(root.publicKey, 'base64'); } catch { throw new Error('Package trust root publicKey is not base64.'); }
if (publicKey.length !== 32 || publicKey.toString('base64') !== root.publicKey) throw new Error('Package trust root publicKey must be canonical 32-byte base64.');

const expectedPolicySha = sha256Bytes(trustRaw);
const expectedPublicKeySha = sha256Bytes(publicKey);
if (!evidence.trustRoot || evidence.trustRoot.policySha256 !== expectedPolicySha || evidence.trustRoot.publicKeySha256 !== expectedPublicKeySha) {
  throw new Error('Evidence trust-root fingerprints do not match supplied trust policy.');
}
if (evidence.trustRoot.scope !== 'package:swirapp' || evidence.trustRoot.requireSignedPackages !== true) throw new Error('Evidence trust-root safety contract is incomplete.');

if (artifactMap.schema !== 'swir.catalog-artifacts/1.0' || artifactMap.generatedFrom !== evidence.sourceCommit || !Array.isArray(artifactMap.artifacts)) {
  throw new Error('Artifact map does not bind to the evidence source commit.');
}
if (!Array.isArray(evidence.packages) || evidence.packages.length < 1 || evidence.packageCount !== evidence.packages.length) {
  throw new Error('Evidence package list/count is invalid.');
}
if (artifactMap.artifacts.length !== evidence.packages.length) throw new Error('Evidence package count differs from catalog artifact map.');

const mapped = new Map();
for (const artifact of artifactMap.artifacts) {
  const key = `${artifact?.packageId}@${artifact?.version}`;
  if (!artifact?.packageId || !artifact?.version || mapped.has(key)) throw new Error(`Invalid or duplicate artifact-map identity: ${key}`);
  mapped.set(key, artifact);
}

const seenPaths = new Set();
for (const item of evidence.packages) {
  const key = `${item?.packageId}@${item?.version}`;
  const artifact = mapped.get(key);
  if (!artifact) throw new Error(`Evidence package is absent from artifact map: ${key}`);
  if (item.keyId !== evidence.keyId || item.signatureVerified !== true) throw new Error(`Package evidence is not signature-verified under expected key: ${key}`);
  if (!isHex64(item.artifactSha256) || !isHex64(item.contentSha256)) throw new Error(`Package evidence hashes are invalid: ${key}`);
  if (!safePackagePath(item.path) || item.path !== artifact.desktop?.url) throw new Error(`Unsafe or mismatched package path: ${key}`);
  if (seenPaths.has(item.path)) throw new Error(`Duplicate package path in evidence: ${item.path}`);
  seenPaths.add(item.path);

  const resolved = path.resolve(storeRoot, item.path);
  const prefix = `${storeRoot}${path.sep}`;
  if (!resolved.startsWith(prefix)) throw new Error(`Package path escaped Store root: ${item.path}`);
  if (!fs.existsSync(resolved) || !fs.statSync(resolved).isFile()) throw new Error(`Package file is missing: ${item.path}`);
  const stat = fs.statSync(resolved);
  if (!Number.isSafeInteger(item.size) || item.size <= 0 || stat.size !== item.size) throw new Error(`Package size evidence mismatch: ${key}`);
  const actualSha = sha256File(resolved);
  if (actualSha !== item.artifactSha256 || actualSha !== artifact.desktop?.sha256) throw new Error(`Package artifact SHA-256 evidence mismatch: ${key}`);
}

if (!evidence.builder || typeof evidence.builder !== 'object') throw new Error('Evidence builder metadata is missing.');
if (expectedKind === 'production') {
  if (!evidence.builder.repository || !evidence.builder.runId || !evidence.builder.runAttempt) {
    throw new Error('Production evidence requires GitHub repository/run identity.');
  }
}

console.log(`Package signing evidence validated: ${evidence.packageCount} packages, ${evidence.keyId}, ${evidence.sourceCommit}, ${evidence.evidenceKind}.`);
