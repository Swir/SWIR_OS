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

function sectionBetweenHeadings(document, heading) {
  const start = document.indexOf(heading);
  if (start < 0) return '';
  const rest = document.slice(start + heading.length);
  const nextHeading = rest.search(/^##\s+/m);
  return nextHeading < 0 ? document.slice(start) : document.slice(start, start + heading.length + nextHeading);
}

function containsLegacyTextMeter(document) {
  return document.split(/\r?\n/).some(line => {
    const trimmed = line.trim();
    if (!trimmed) return false;

    // Unicode/block meters, including mixed full/empty segments and optional labels.
    if (/[█▓▒░](?:\s*[█▓▒░]){3,}/u.test(trimmed)) return true;

    // Bracket-style meters such as [########--] 80% or [====....] 50%.
    if (/\[(?:[#=.\-]\s*){8,}\]\s*\d+(?:[.,]\d+)?%/u.test(trimmed)) return true;

    // Bare text meters are only considered meters when an explicit percentage is present,
    // so Markdown horizontal rules and normal punctuation are not rejected.
    if (/^(?:(?:progress|roadmap|done|status)\s*[:=-]?\s*)?(?:[#=.\-]\s*){8,}\s*\d+(?:[.,]\d+)?%$/iu.test(trimmed)) return true;

    return false;
  });
}

function verifyLegacyDetector() {
  const forbiddenFixtures = [
    '████████░░ 80.0%',
    '█ █ █ █ ░ ░ 66%',
    '[########--] 80%',
    'progress: ========-- 80%',
  ];
  for (const fixture of forbiddenFixtures) {
    if (!containsLegacyTextMeter(fixture)) fail(`legacy-meter detector missed fixture: ${fixture}`);
  }
  for (const fixture of ['---', '----------', '| Progress | 81.5% |', 'assets/readme/progress-card.svg']) {
    if (containsLegacyTextMeter(fixture)) fail(`legacy-meter detector false-positive fixture: ${fixture}`);
  }
}

verifyLegacyDetector();

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

if (countExact(block, 'assets/readme/progress-mini.svg') !== 1) {
  fail('canonical roadmap dashboard must embed exactly one progress-mini.svg.');
}
if (block.includes('assets/readme/progress-card.svg')) {
  fail('canonical roadmap dashboard must use progress-mini.svg, not duplicate the README card.');
}
if (block.includes('assets/readme/progress-template.svg')) {
  fail('progress-template.svg is TEMPLATE-only and must never be embedded as project data.');
}
if (containsLegacyTextMeter(block)) {
  fail('legacy text progress meter is forbidden in the canonical roadmap dashboard.');
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
if (containsLegacyTextMeter(standard)) {
  fail('canonical roadmap standard contains an active legacy text progress meter.');
}

const readmePath = path.resolve(repositoryRoot, 'README.md');
if (!fs.existsSync(readmePath)) fail('README.md is missing; visible project progress cannot be synchronized.');
const readme = fs.readFileSync(readmePath, 'utf8');
if (countExact(readme, '<!-- SWIR-README-STANDARD:v2 -->') !== 1) {
  fail('README must keep exactly one SWIR-README-STANDARD:v2 marker; do not downgrade to v1.');
}
for (const [needle, message] of [
  [`ROADMAP-${percent}%25-`, 'README ROADMAP badge'],
  [`DONE-${completed}%2F${total}-`, 'README DONE badge'],
  [`**${completed} of ${total} measurable roadmap deliverables are complete.**`, 'README measurable-progress sentence'],
  ['assets/readme/progress-card.svg', 'README SWIR Progress SVG PRO card'],
]) {
  if (!readme.includes(needle)) fail(`${message} is stale; synchronize README.md with the authoritative roadmap.`);
}

const readmeProgress = sectionBetweenHeadings(readme, '## 📊 Project status');
if (!readmeProgress) fail('README project status section is missing.');
if (countExact(readmeProgress, 'assets/readme/progress-card.svg') !== 1) {
  fail('README project status section must embed exactly one progress-card.svg.');
}
if (readmeProgress.includes('assets/readme/progress-mini.svg')) {
  fail('README project status section must use progress-card.svg, not duplicate the roadmap mini.');
}
if (readmeProgress.includes('assets/readme/progress-template.svg')) {
  fail('progress-template.svg is TEMPLATE-only and must never be embedded as project data.');
}
if (containsLegacyTextMeter(readmeProgress)) {
  fail('legacy text progress meter is forbidden in the maintained README project status section.');
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

const template = fs.readFileSync(path.resolve(repositoryRoot, 'assets/readme/progress-template.svg'), 'utf8');
if (!template.includes('TEMPLATE') || !template.includes('NOT PROJECT DATA')) {
  fail('progress-template.svg must be explicitly labelled TEMPLATE / NOT PROJECT DATA.');
}

console.log(JSON.stringify({
  schema: 'swir.roadmap-contract/1.4',
  roadmap: path.basename(roadmapPath),
  completed,
  remaining,
  total,
  percent: Number(percent),
  readmeSynchronized: true,
  progressSvgEmbedded: true,
  svgOnlyPresentation,
  legacyMeterClean: true,
  templateProjectData: false,
  styleLock: 'SWIR-ROADMAP-STANDARD:v1+svg-only-amendment',
  valid: true,
}));
