import assert from 'node:assert/strict';
import { verifyPackageSigningEvidenceRunProvenance } from './verify-package-signing-evidence-run-provenance.mjs';

const commit = '0123456789abcdef0123456789abcdef01234567';
const baseEvidence = {
  schema: 'swir.package-signing-evidence/1.0',
  evidenceKind: 'production',
  sourceCommit: commit,
  builder: {
    repository: 'Swir/SWIR_OS',
    runId: '35923322193',
    runAttempt: '1',
  },
};
const expected = {
  expectedKind: 'production',
  expectedRepository: 'Swir/SWIR_OS',
  expectedSourceCommit: commit,
  expectedRunId: '35923322193',
  expectedRunAttempt: '1',
};

const valid = verifyPackageSigningEvidenceRunProvenance({ evidence: baseEvidence, ...expected });
assert.equal(valid.valid, true);
assert.equal(valid.sourceCommit, commit);
assert.equal(valid.runId, '35923322193');

assert.throws(() => verifyPackageSigningEvidenceRunProvenance({ evidence: { ...baseEvidence, evidenceKind: 'contract' }, ...expected }), /Evidence kind mismatch/i);
assert.throws(() => verifyPackageSigningEvidenceRunProvenance({ evidence: { ...baseEvidence, sourceCommit: 'f'.repeat(40) }, ...expected }), /source commit mismatch/i);
assert.throws(() => verifyPackageSigningEvidenceRunProvenance({ evidence: { ...baseEvidence, builder: { ...baseEvidence.builder, repository: 'Other/SWIR_OS' } }, ...expected }), /repository mismatch/i);
assert.throws(() => verifyPackageSigningEvidenceRunProvenance({ evidence: { ...baseEvidence, builder: { ...baseEvidence.builder, runId: '999' } }, ...expected }), /run id mismatch/i);
assert.throws(() => verifyPackageSigningEvidenceRunProvenance({ evidence: { ...baseEvidence, builder: { ...baseEvidence.builder, runAttempt: '2' } }, ...expected }), /run attempt mismatch/i);
assert.throws(() => verifyPackageSigningEvidenceRunProvenance({ evidence: { ...baseEvidence, builder: null }, ...expected }), /builder metadata is missing/i);
assert.throws(() => verifyPackageSigningEvidenceRunProvenance({ evidence: baseEvidence, ...expected, expectedSourceCommit: 'ABC' }), /40-hex Git SHA/i);
assert.throws(() => verifyPackageSigningEvidenceRunProvenance({ evidence: baseEvidence, ...expected, expectedRunId: '0' }), /positive decimal integer/i);

console.log(JSON.stringify({ schema: 'swir.package-signing-evidence-run-provenance-tests/1.0', valid: true, cases: 9 }));
