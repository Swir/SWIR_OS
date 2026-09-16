import fs from 'node:fs';
import path from 'node:path';

const roadmapPath = path.resolve(process.argv[2] || 'SWIR-OS-ARCHITECTURE.md');
const text = fs.readFileSync(roadmapPath, 'utf8');

function fail(message) {
  console.error(`ROADMAP CONTRACT FAIL: ${message}`);
  process.exit(1);
}

function countExact(needle) {
  return text.split(needle).length - 1;
}

const standardMarker = '<!-- SWIR-ROADMAP-STANDARD:v1 -->';
const startMarker = '<!-- ROADMAP-PROGRESS:START -->';
const endMarker = '<!-- ROADMAP-PROGRESS:END -->';

if (countExact(standardMarker) !== 1) fail('SWIR-ROADMAP-STANDARD:v1 marker must appear exactly once.');
if (countExact(startMarker) !== 1 || countExact(endMarker) !== 1) fail('ROADMAP-PROGRESS start/end markers must each appear exactly once.');

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
const expectedFilled = Math.round((completed / total) * 20);
const expectedBar = '█'.repeat(expectedFilled) + '░'.repeat(20 - expectedFilled);

const barMatch = block.match(/```text\r?\n([█░]+) ([0-9]+\.[0-9])%\r?\n```/);
if (!barMatch) fail('20-segment progress text bar is missing or malformed.');
if ([...barMatch[1]].length !== 20) fail(`progress bar has ${[...barMatch[1]].length} segments instead of 20.`);
if (barMatch[1] !== expectedBar) fail(`progress bar mismatch: expected ${expectedBar}.`);
if (barMatch[2] !== percent) fail(`progress bar percent ${barMatch[2]} does not match checklist ${percent}.`);

if (!block.includes(`ROADMAP-${percent}%25-`)) fail(`ROADMAP badge does not match ${percent}%.`);
if (!block.includes(`DONE-${completed}%2F${total}-`)) fail(`DONE badge does not match ${completed}/${total}.`);
const expectedStatus = completed === total ? 'STATUS-COMPLETE-' : 'STATUS-IN%20PROGRESS-';
if (!block.includes(expectedStatus)) fail(`STATUS badge does not match completion state (${expectedStatus}).`);

const tableRow = `| **${completed}** | **${remaining}** | **${total}** | **${percent}%** |`;
if (!block.includes(tableRow)) fail(`progress table does not match checklist; expected: ${tableRow}`);

const canonicalRequired = [
  'Every active project must have a roadmap containing one protected progress block:',
  'The text bar always has exactly 20 segments.',
  'If major scope is added, add it as unchecked deliverables first so the denominator remains honest.',
];
const repositoryRoot = path.dirname(roadmapPath);
const standardPath = path.resolve(repositoryRoot, 'SWIR-ROADMAP-STANDARD.md');
if (!fs.existsSync(standardPath)) fail('canonical SWIR-ROADMAP-STANDARD.md is missing.');
const standard = fs.readFileSync(standardPath, 'utf8');
for (const required of canonicalRequired) {
  if (!standard.includes(required)) fail(`canonical roadmap standard is missing required rule: ${required}`);
}

const readmePath = path.resolve(repositoryRoot, 'README.md');
if (!fs.existsSync(readmePath)) fail('README.md is missing; visible project progress cannot be synchronized.');
const readme = fs.readFileSync(readmePath, 'utf8');
for (const [needle, message] of [
  [`ROADMAP-${percent}%25-`, 'README ROADMAP badge'],
  [`DONE-${completed}%2F${total}-`, 'README DONE badge'],
  [`${expectedBar} ${percent}%`, 'README 20-segment progress bar'],
  [`**${completed} of ${total} measurable roadmap deliverables are complete.**`, 'README measurable-progress sentence'],
]) {
  if (!readme.includes(needle)) fail(`${message} is stale; synchronize README.md with the authoritative roadmap.`);
}

console.log(JSON.stringify({
  schema: 'swir.roadmap-contract/1.1',
  roadmap: path.basename(roadmapPath),
  completed,
  remaining,
  total,
  percent: Number(percent),
  bar: expectedBar,
  readmeSynchronized: true,
  styleLock: 'SWIR-ROADMAP-STANDARD:v1',
  valid: true,
}));
