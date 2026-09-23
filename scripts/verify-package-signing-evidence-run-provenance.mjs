import fs from 'node:fs';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const SHA_RE = /^[0-9a-f]{40}$/;
const RUN_RE = /^[1-9][0-9]*$/;
const KINDS = new Set(['contract', 'production']);

function requiredString(value, label) {
  if (typeof value !== 'string' || value.trim().length === 0) throw new Error(`${label} is required.`);
  return value.trim();
}

function requiredRunNumber(value, label) {
  const normalized = requiredString(String(value ?? ''), label);
  if (!RUN_RE.test(normalized)) throw new Error(`${label} must be a positive decimal integer.`);
  return normalized;
}

export function verifyPackageSigningEvidenceRunProvenance({
  evidence,
  expectedKind,
  expectedRepository,
  expectedSourceCommit,
  expectedRunId,
  expectedRunAttempt,
}) {
  if (!evidence || typeof evidence !== 'object' || Array.isArray(evidence)) throw new Error('Package signing evidence must be an object.');
  if (evidence.schema !== 'swir.package-signing-evidence/1.0') throw new Error('Unexpected package signing evidence schema.');

  const kind = requiredString(expectedKind, 'expected evidence kind');
  if (!KINDS.has(kind)) throw new Error('Expected evidence kind must be contract or production.');
  if (evidence.evidenceKind !== kind) throw new Error(`Evidence kind mismatch: expected ${kind}, got ${evidence.evidenceKind}.`);

  const repository = requiredString(expectedRepository, 'expected GitHub repository');
  if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) throw new Error('Expected GitHub repository must be owner/name.');

  const sourceCommit = requiredString(expectedSourceCommit, 'expected source commit').toLowerCase();
  if (!SHA_RE.test(sourceCommit)) throw new Error('Expected source commit must be lowercase 40-hex Git SHA.');
  if (evidence.sourceCommit !== sourceCommit) throw new Error(`Evidence source commit mismatch: expected ${sourceCommit}, got ${evidence.sourceCommit}.`);

  const runId = requiredRunNumber(expectedRunId, 'expected GitHub run id');
  const runAttempt = requiredRunNumber(expectedRunAttempt, 'expected GitHub run attempt');
  if (!evidence.builder || typeof evidence.builder !== 'object' || Array.isArray(evidence.builder)) throw new Error('Evidence builder metadata is missing.');
  if (evidence.builder.repository !== repository) throw new Error(`Evidence repository mismatch: expected ${repository}, got ${evidence.builder.repository}.`);
  if (String(evidence.builder.runId ?? '') !== runId) throw new Error(`Evidence GitHub run id mismatch: expected ${runId}, got ${evidence.builder.runId}.`);
  if (String(evidence.builder.runAttempt ?? '') !== runAttempt) throw new Error(`Evidence GitHub run attempt mismatch: expected ${runAttempt}, got ${evidence.builder.runAttempt}.`);

  return {
    schema: 'swir.package-signing-evidence-run-provenance/1.0',
    valid: true,
    evidenceKind: kind,
    repository,
    sourceCommit,
    runId,
    runAttempt,
  };
}

function main() {
  const [evidenceArg, expectedKind, expectedRepository, expectedSourceCommit, expectedRunId, expectedRunAttempt] = process.argv.slice(2);
  if (!evidenceArg || !expectedKind || !expectedRepository || !expectedSourceCommit || !expectedRunId || !expectedRunAttempt) {
    throw new Error('Usage: node scripts/verify-package-signing-evidence-run-provenance.mjs <evidence.json> <contract|production> <repository> <source-commit> <run-id> <run-attempt>');
  }
  const evidencePath = path.resolve(evidenceArg);
  if (!fs.existsSync(evidencePath) || !fs.statSync(evidencePath).isFile()) throw new Error(`Evidence file is missing: ${evidencePath}`);
  const evidence = JSON.parse(fs.readFileSync(evidencePath, 'utf8'));
  console.log(JSON.stringify(verifyPackageSigningEvidenceRunProvenance({
    evidence,
    expectedKind,
    expectedRepository,
    expectedSourceCommit,
    expectedRunId,
    expectedRunAttempt,
  })));
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { main(); } catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exit(1); }
}
