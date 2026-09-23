import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { execFileSync } from 'node:child_process';
import { verifyReleaseProvenance } from './verify-desktop-release-provenance.mjs';

function git(cwd, ...args) {
  return execFileSync('git', args, { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}

const repo = fs.mkdtempSync(path.join(os.tmpdir(), 'swir-release-provenance-'));
try {
  git(repo, 'init', '-b', 'main');
  git(repo, 'config', 'user.name', 'SWIR CI');
  git(repo, 'config', 'user.email', 'ci@swir.invalid');
  fs.writeFileSync(path.join(repo, 'main.txt'), 'main\n');
  git(repo, 'add', 'main.txt');
  git(repo, 'commit', '-m', 'main');
  const mainSha = git(repo, 'rev-parse', 'HEAD');

  const preview = verifyReleaseProvenance({
    repoDir: repo,
    tag: 'desktop-v0.5.8-preview',
    channel: 'preview',
    tagCommit: mainSha,
    mainRef: 'main',
    isPrerelease: true,
  });
  assert.equal(preview.valid, true);
  assert.equal(preview.version, '0.5.8');
  assert.equal(preview.channel, 'preview');

  const stable = verifyReleaseProvenance({
    repoDir: repo,
    tag: 'desktop-v1.0.0-stable',
    channel: 'stable',
    tagCommit: mainSha,
    mainRef: 'main',
    isPrerelease: false,
  });
  assert.equal(stable.valid, true);

  assert.throws(() => verifyReleaseProvenance({
    repoDir: repo,
    tag: 'desktop-v0.5.8-preview',
    channel: 'preview',
    tagCommit: mainSha,
    mainRef: 'main',
    isPrerelease: false,
  }), /preview release must be marked prerelease/i);

  assert.throws(() => verifyReleaseProvenance({
    repoDir: repo,
    tag: 'desktop-v1.0.0-stable',
    channel: 'stable',
    tagCommit: mainSha,
    mainRef: 'main',
    isPrerelease: true,
  }), /stable release must not be marked prerelease/i);

  assert.throws(() => verifyReleaseProvenance({
    repoDir: repo,
    tag: 'desktop-v0.5.8-stable',
    channel: 'preview',
    tagCommit: mainSha,
    mainRef: 'main',
    isPrerelease: true,
  }), /tag channel stable does not match preview/i);

  git(repo, 'checkout', '-b', 'untrusted-release');
  fs.writeFileSync(path.join(repo, 'branch.txt'), 'branch-only\n');
  git(repo, 'add', 'branch.txt');
  git(repo, 'commit', '-m', 'branch only');
  const branchSha = git(repo, 'rev-parse', 'HEAD');

  assert.throws(() => verifyReleaseProvenance({
    repoDir: repo,
    tag: 'desktop-v0.5.9-preview',
    channel: 'preview',
    tagCommit: branchSha,
    mainRef: 'main',
    isPrerelease: true,
  }), /not reachable from canonical main/i);

  assert.throws(() => verifyReleaseProvenance({
    repoDir: repo,
    tag: 'desktop-v0.5-preview',
    channel: 'preview',
    tagCommit: mainSha,
    mainRef: 'main',
    isPrerelease: true,
  }), /must match desktop-v/i);

  assert.throws(() => verifyReleaseProvenance({
    repoDir: repo,
    tag: 'desktop-v0.5.8-preview',
    channel: 'preview',
    tagCommit: 'abc',
    mainRef: 'main',
    isPrerelease: true,
  }), /full 40-hex Git commit SHA/i);

  console.log(JSON.stringify({ schema: 'swir.desktop-release-provenance-tests/1.0', valid: true, cases: 8 }));
} finally {
  fs.rmSync(repo, { recursive: true, force: true });
}
