import assert from 'node:assert/strict';
import test from 'node:test';
import { discoverWebKitInspectorTargets, parseWebKitInspectorTargets } from './webkit_inspector_targets.mjs';

test('parses current WebKit inspector target path variants and deduplicates them', () => {
  const html = `<a href="/socket/1/7/WebPage">A</a><a href='/socket/1/8/web-page'>B</a><a href="/socket/1/7/WebPage">dup</a>`;
  assert.deepEqual(parseWebKitInspectorTargets(html, 9331), [
    { type: 'page', url: 'tauri://localhost', webSocketDebuggerUrl: 'ws://127.0.0.1:9331/socket/1/7/WebPage' },
    { type: 'page', url: 'tauri://localhost', webSocketDebuggerUrl: 'ws://127.0.0.1:9331/socket/1/8/web-page' },
  ]);
});

test('ignores non-target and query suffixes when deriving the WebSocket endpoint', () => {
  const html = `<a href="/socket/1/2/Other">x</a><a href="/socket/1/3/WebPage?next=ignored">y</a>`;
  const targets = parseWebKitInspectorTargets(html, 9332);
  assert.equal(targets.length, 1);
  assert.equal(targets[0].webSocketDebuggerUrl, 'ws://127.0.0.1:9332/socket/1/3/WebPage');
});

test('discovery is loopback-only and uses a bounded request', async () => {
  let requested;
  const targets = await discoverWebKitInspectorTargets(9444, {
    timeoutMs: 321,
    fetchImpl: async (url, options) => {
      requested = { url, signal: options.signal };
      return { ok: true, status: 200, text: async () => `<a href="/socket/c/t/WebPage">Konofix</a>` };
    },
  });
  assert.equal(requested.url, 'http://127.0.0.1:9444/');
  assert(requested.signal instanceof AbortSignal);
  assert.equal(targets[0].webSocketDebuggerUrl, 'ws://127.0.0.1:9444/socket/c/t/WebPage');
});

test('invalid ports fail closed', () => {
  for (const port of [0, 65536, 1.5, NaN]) assert.throws(() => parseWebKitInspectorTargets('', port));
});
