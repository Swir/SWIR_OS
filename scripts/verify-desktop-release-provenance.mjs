import { spawnSync } from 'node:child_process';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

const TAG_RE = /^desktop-v([0-9]+\.[0-9]+\.[0-9]+)-(preview|stable)$/;
const SHA_RE = /^[a-f0-9]{40}$/i;

function requireValue(value, label) {
  if (typeof value !== 'string' || value.trim().length === 0) throw new Error(`${label} is required.`);
  return value.trim();
}

function parseBoolean(value, label) {
  if (value === true || value === 'true') return true;
  if (value === false || value === 'false') return false;
  throw new Error(`${label} must be true or false.`);
}

export function verifyReleaseProvenance({ repoDir = process.cwd(), tag, channel, tagCommit, mainRef = 'origin/main', isPrerelease }) {
  const normalizedTag = requireValue(tag, 'release tag');
  const normalizedChannel = requireValue(channel, 'release channel');
  const normalizedCommit = requireValue(tagCommit, 'release tag commit');
  const normalizedMainRef = requireValue(mainRef, 'main ref');
  const prerelease = parseBoolean(isPrerelease, 'release prerelease flag');

  const match = TAG_RE.exec(normalizedTag);
  if (!match) throw new Error('Desktop release tag must match desktop-v<major.minor.patch>-(preview|stable).');
  const [, version, tagChannel] = match;
  if (tagChannel !== normalizedChannel) throw new Error(`Release tag channel ${tagChannel} does not match ${normalizedChannel}.`);
  if (!SHA_RE.test(normalizedCommit)) throw new Error('Release tag commit must be a full 40-hex Git commit SHA.');

  const ancestry = spawnSync('git', ['merge-base', '--is-ancestor', normalizedCommit, normalizedMainRef], {
    cwd: path.resolve(repoDir),
    encoding: 'utf8',
  });
  if (ancestry.error) throw new Error(`Could not execute Git ancestry verification: ${ancestry.error.message}`);
  if (ancestry.status === 1) throw new Error(`Desktop release tag ${normalizedTag} is not reachable from canonical ${normalizedMainRef}.`);
  if (ancestry.status !== 0) {
    const detail = (ancestry.stderr || ancestry.stdout || '').trim();
    throw new Error(`Git ancestry verification failed${detail ? `: ${detail}` : '.'}`);
  }

  if (normalizedChannel === 'preview' && prerelease !== true) throw new Error('Desktop preview release must be marked prerelease.');
  if (normalizedChannel === 'stable' && prerelease !== false) throw new Error('Desktop stable release must not be marked prerelease.');

  return {
    schema: 'swir.desktop-release-provenance/1.0',
    valid: true,
    tag: normalizedTag,
    version,
    channel: normalizedChannel,
    tagCommit: normalizedCommit.toLowerCase(),
    mainRef: normalizedMainRef,
    prerelease,
  };
}

function arg(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`Missing ${name}.`);
  return process.argv[index + 1];
}

function main() {
  const result = verifyReleaseProvenance({
    repoDir: process.cwd(),
    tag: arg('--tag'),
    channel: arg('--channel'),
    tagCommit: arg('--tag-commit'),
    mainRef: arg('--main-ref'),
    isPrerelease: arg('--prerelease'),
  });
  console.log(JSON.stringify(result));
}

if (process.argv[1] && import.meta.url === pathToFileURL(path.resolve(process.argv[1])).href) {
  try { main(); } catch (error) { console.error(error instanceof Error ? error.message : String(error)); process.exit(1); }
}
