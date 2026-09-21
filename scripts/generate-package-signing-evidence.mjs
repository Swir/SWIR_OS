import fs from 'node:fs';
import path from 'node:path';
import crypto from 'node:crypto';
import { spawnSync } from 'node:child_process';

const [storeArg, trustArg, signerArg, sourceCommit, expectedKeyId, outputArg, evidenceKind = 'contract', repository = '', runId = '', runAttempt = ''] = process.argv.slice(2);
if (!storeArg || !trustArg || !signerArg || !sourceCommit || !expectedKeyId || !outputArg) {
  throw new Error('Usage: node scripts/generate-package-signing-evidence.mjs <store-dir> <trust-roots.json> <signer.dll> <source-commit> <key-id> <output.json> [contract|production] [repository] [run-id] [run-attempt]');
}
if (!['contract', 'production'].includes(evidenceKind)) throw new Error('Evidence kind must be contract or production.');
if (!/^[0-9a-fA-F]{40}$/.test(sourceCommit)) throw new Error('Source commit must be an exact 40-hex Git SHA.');
if (!/^[A-Za-z0-9._-]{1,128}$/.test(expectedKeyId)) throw new Error('Expected package signing key id is invalid.');

const storeRoot = path.resolve(storeArg);
const trustPath = path.resolve(trustArg);
const signerPath = path.resolve(signerArg);
const outputPath = path.resolve(outputArg);
const readJson = file => JSON.parse(fs.readFileSync(file, 'utf8'));
const sha256Bytes = data => crypto.createHash('sha256').update(data).digest('hex');
const sha256File = file => sha256Bytes(fs.readFileSync(file));
const sourceSha = sourceCommit.toLowerCase();

for (const [label, file] of [['trust roots', trustPath], ['signature verifier', signerPath]]) {
  if (!fs.existsSync(file) || !fs.statSync(file).isFile()) throw new Error(`${label} file is missing: ${file}`);
}
if (!fs.existsSync(storeRoot) || !fs.statSync(storeRoot).isDirectory()) throw new Error(`Signed Store directory is missing: ${storeRoot}`);

const trustRaw = fs.readFileSync(trustPath);
const trust = JSON.parse(trustRaw.toString('utf8'));
if (trust.schema !== 'swir.package-trust-roots/1.0' || trust.requireSignedPackages !== true || !Array.isArray(trust.roots) || trust.roots.length !== 1) {
  throw new Error('Package trust-root policy must be fail-closed with exactly one root.');
}
const root = trust.roots[0];
if (root.keyId !== expectedKeyId || root.algorithm !== 'Ed25519' || root.format !== 'raw' || root.enabled !== true) {
  throw new Error('Package trust root does not match the expected enabled raw Ed25519 key.');
}
if (!Array.isArray(root.scope) || root.scope.length !== 1 || root.scope[0] !== 'package:swirapp') throw new Error('Package trust root scope must be exactly package:swirapp.');
if (typeof root.publicKey !== 'string') throw new Error('Package trust-root public key is missing.');
const publicKey = Buffer.from(root.publicKey, 'base64');
if (publicKey.length !== 32 || publicKey.toString('base64') !== root.publicKey) throw new Error('Package trust-root public key must be canonical 32-byte base64.');

const artifactMapPath = path.join(storeRoot, 'catalog-artifacts.json');
if (!fs.existsSync(artifactMapPath) || !fs.statSync(artifactMapPath).isFile()) throw new Error(`Catalog artifact map is missing: ${artifactMapPath}`);
const artifactMap = readJson(artifactMapPath);
if (artifactMap.schema !== 'swir.catalog-artifacts/1.0' || artifactMap.generatedFrom !== sourceSha || !Array.isArray(artifactMap.artifacts) || artifactMap.artifacts.length < 1) {
  throw new Error('Catalog artifact map is invalid or is not bound to the expected source commit.');
}

const seenIdentity = new Set();
const seenPath = new Set();
const packages = [];
for (const artifact of [...artifactMap.artifacts].sort((a, b) => `${a.packageId}@${a.version}`.localeCompare(`${b.packageId}@${b.version}`))) {
  const packageId = artifact?.packageId;
  const version = artifact?.version;
  const relativePath = artifact?.desktop?.url;
  const mappedSha = artifact?.desktop?.sha256;
  if (typeof packageId !== 'string' || !packageId || typeof version !== 'string' || !version) throw new Error('Artifact map contains an incomplete package identity.');
  const identity = `${packageId}@${version}`;
  if (seenIdentity.has(identity)) throw new Error(`Duplicate package identity: ${identity}`);
  seenIdentity.add(identity);
  if (typeof relativePath !== 'string' || !/^packages\/[A-Za-z0-9._-]+\.swirapp$/.test(relativePath)) throw new Error(`Unsafe signed package artifact path: ${relativePath}`);
  if (seenPath.has(relativePath)) throw new Error(`Duplicate package artifact path: ${relativePath}`);
  seenPath.add(relativePath);

  const artifactPath = path.resolve(storeRoot, relativePath);
  const relCheck = path.relative(storeRoot, artifactPath);
  if (!relCheck || relCheck.startsWith(`..${path.sep}`) || relCheck === '..' || path.isAbsolute(relCheck)) throw new Error(`Package artifact escaped Store root: ${relativePath}`);
  if (!fs.existsSync(artifactPath)) throw new Error(`Signed package artifact is missing: ${relativePath}`);
  const stat = fs.lstatSync(artifactPath);
  if (!stat.isFile() || stat.isSymbolicLink() || stat.size <= 0) throw new Error(`Signed package artifact must be a non-empty regular file: ${relativePath}`);
  const artifactSha256 = sha256File(artifactPath);
  if (typeof mappedSha !== 'string' || !/^[0-9a-f]{64}$/.test(mappedSha) || artifactSha256 !== mappedSha) throw new Error(`Signed package artifact SHA-256 mismatch: ${identity}`);

  const verify = spawnSync('dotnet', [signerPath, 'verify', artifactPath, trustPath], { encoding: 'utf8', windowsHide: true });
  if (verify.error) throw new Error(`Could not execute package verifier for ${identity}: ${verify.error.message}`);
  if (verify.status !== 0) throw new Error(`Independent package signature verification failed for ${identity}: ${(verify.stderr || verify.stdout || '').trim()}`);
  const jsonLine = (verify.stdout || '').split(/\r?\n/).map(line => line.trim()).filter(Boolean).at(-1);
  let verified;
  try { verified = JSON.parse(jsonLine); } catch { throw new Error(`Package verifier did not emit JSON provenance for ${identity}.`); }
  if (verified?.verified !== true || verified.KeyId !== expectedKeyId || verified.PackageId !== packageId || verified.Version !== version || !/^[0-9a-f]{64}$/.test(verified.ContentSha256 || '')) {
    throw new Error(`Verified package provenance does not match expected identity/key for ${identity}.`);
  }

  packages.push({
    packageId,
    version,
    path: relativePath,
    size: stat.size,
    artifactSha256,
    contentSha256: verified.ContentSha256,
    keyId: expectedKeyId,
    signatureVerified: true
  });
}

const evidence = {
  schema: 'swir.package-signing-evidence/1.0',
  evidenceKind,
  sourceCommit: sourceSha,
  keyId: expectedKeyId,
  algorithm: 'Ed25519',
  generatedAt: new Date().toISOString(),
  trustRoot: {
    policySha256: sha256Bytes(trustRaw),
    publicKeySha256: sha256Bytes(publicKey),
    scope: 'package:swirapp',
    requireSignedPackages: true
  },
  builder: { repository, runId, runAttempt },
  packageCount: packages.length,
  packages
};

fs.mkdirSync(path.dirname(outputPath), { recursive: true });
fs.writeFileSync(outputPath, `${JSON.stringify(evidence, null, 2)}\n`, { encoding: 'utf8', mode: 0o600 });
console.log(`Package signing evidence written: ${outputPath}`);
console.log(`Source commit: ${sourceSha}`);
console.log(`Package key id: ${expectedKeyId}`);
console.log(`Public trust-root SHA-256: ${evidence.trustRoot.publicKeySha256}`);
console.log(`Verified package count: ${packages.length}`);
