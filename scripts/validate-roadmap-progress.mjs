import fs from 'node:fs';
import path from 'node:path';

const roadmapPath = path.resolve(process.argv[2] || 'SWIR-OS-ARCHITECTURE.md');
const text = fs.readFileSync(roadmapPath, 'utf8');

function fail(message) {
  console.error(`ROADMAP CONTRACT FAIL: ${message}`);
  process.exit(1);
}

function countExact(haystack, needle) {
  return haystack.split(needle).length - 1;
}

const standardMarker = '<!-- SWIR-ROADMAP-STANDARD:v1 -->';
const startMarker = '<!-- ROADMAP-PROGRESS:START -->';
const endMarker = '<!-- ROADMAP-PROGRESS:END -->';

if (countExact(text, standardMarker) !== 1) fail('SWIR-ROADMAP-STANDARD:v1 marker must appear exactly once.');
if (countExact(text, startMarker) !== 1 || countExact(text, endMarker) !== 1) {
  fail('ROADMAP-PROGRESS start/end markers must each appear exactly once.');
}

const progressStart = text.indexOf(startMarker);
const progressEnd = text.indexOf(endMarker);
const roadmapStart = text.indexOf('## Version roadmap');
const developmentStart = text.indexOf('## Development rule', roadmapStart);
if (progressStart < 0 || progressEnd <= progressStart) fail('protected progress block ordering is invalid.');
if (roadmapStart < 0 || developmentStart <= roadmapStart) fail('Version roadmap or Development rule section is missing.');
if (progressEnd > roadmapStart) fail('protected progress dashboard must stay above Version roadmap.');

const block = text.slice(progressStart, progressEnd + endMarker.length);
for (const required of [
  'alt="CI"',
  'alt="Roadmap progress"',
  'alt="Completed"',
  'alt="Status"',
  'assets/readme/progress-mini.svg',
  '## 📊 Overall progress',
  '| ✅ Completed | ⏳ Remaining | 📦 Total | 🎯 Progress |',
]) {
  if (!block.includes(required)) fail(`required dashboard element missing: ${required}`);
}

const checklist = text.slice(roadmapStart, developmentStart);
const matches = [...checklist.matchAll(/^- \[(x| )\] .+$/gm)];
if (matches.length === 0) fail('Version roadmap contains no measurable checklist items.');
const completed = matches.filter(match => match[1] === 'x').length;
const total = matches.length;
const remaining = total - completed;
const percent = ((completed / total) * 100).toFixed(1);

if (!block.includes(`ROADMAP-${percent}%25-`)) fail(`ROADMAP badge does not match ${percent}%.`);
if (!block.includes(`DONE-${completed}%2F${total}-`)) fail(`DONE badge does not match ${completed}/${total}.`);
const expectedStatus = completed === total ? 'STATUS-COMPLETE-' : 'STATUS-IN%20PROGRESS-';
if (!block.includes(expectedStatus)) fail(`STATUS badge does not match completion state (${expectedStatus}).`);

const tableRow = `| **${completed}** | **${remaining}** | **${total}** | **${percent}%** |`;
if (!block.includes(tableRow)) fail(`progress table does not match checklist; expected: ${tableRow}`);

const repositoryRoot = path.dirname(roadmapPath);
const standardPath = path.resolve(repositoryRoot, 'SWIR-ROADMAP-STANDARD.md');
if (!fs.existsSync(standardPath)) fail('canonical SWIR-ROADMAP-STANDARD.md is missing.');
const standard = fs.readFileSync(standardPath, 'utf8');
for (const required of [
  'Every active project must have a roadmap containing one protected progress block.',
  'The historical 20-segment ASCII/Unicode bar is retired.',
  'If major scope is added, add it as unchecked deliverables first so the denominator remains honest.',
]) {
  if (!standard.includes(required)) fail(`canonical roadmap standard is missing required rule: ${required}`);
}

const svgOnlyPresentation = standard.includes('Presentation amendment — 2026-09-18');
if (!svgOnlyPresentation) fail('canonical roadmap standard is missing the SVG-only presentation amendment.');

const readmePath = path.resolve(repositoryRoot, 'README.md');
if (!fs.existsSync(readmePath)) fail('README.md is missing; visible project progress cannot be synchronized.');
const readme = fs.readFileSync(readmePath, 'utf8');
for (const [needle, message] of [
  [`ROADMAP-${percent}%25-`, 'README ROADMAP badge'],
  [`DONE-${completed}%2F${total}-`, 'README DONE badge'],
  [`**${completed} of ${total} measurable roadmap deliverables are complete.**`, 'README measurable-progress sentence'],
  ['assets/readme/progress-card.svg', 'README SWIR Progress SVG PRO card'],
]) {
  if (!readme.includes(needle)) fail(`${message} is stale; synchronize README.md with the authoritative roadmap.`);
}

const legacyMeterPattern = /```text\r?\n[█░▓▒#=\-]{8,}\s+[0-9]+(?:\.[0-9]+)?%\r?\n```/;
const roadmapHasLegacyMeter = legacyMeterPattern.test(block);
const readmeHasLegacyMeter = legacyMeterPattern.test(readme);
if (roadmapHasLegacyMeter || readmeHasLegacyMeter) {
  console.warn('ROADMAP CONTRACT WARN: legacy text progress meter remains; SVG-only cleanup is pending.');
}

for (const relativePath of [
  'assets/readme/progress-card.svg',
  'assets/readme/progress-mini.svg',
  'assets/readme/progress-template.svg',
  'scripts/generate-readme-progress.mjs',
]) {
  if (!fs.existsSync(path.resolve(repositoryRoot, relativePath))) {
    fail(`required SWIR Progress SVG PRO asset/tool is missing: ${relativePath}`);
  }
}

console.log(JSON.stringify({
  schema: 'swir.roadmap-contract/1.3',
  roadmap: path.basename(roadmapPath),
  completed,
  remaining,
  total,
  percent: Number(percent),
  readmeSynchronized: true,
  progressSvgEmbedded: true,
  svgOnlyPresentation,
  legacyMeterCleanupPending: roadmapHasLegacyMeter || readmeHasLegacyMeter,
  styleLock: 'SWIR-ROADMAP-STANDARD:v1+svg-only-amendment',
  valid: true,
}));
