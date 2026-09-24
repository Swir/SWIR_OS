import assert from 'node:assert/strict';

export function parseWebKitInspectorTargets(html, port) {
  assert.equal(typeof html, 'string', 'WebKit inspector target page must be text');
  assert(Number.isInteger(port) && port > 0 && port <= 65535, 'Invalid WebKit inspector port');
  const paths = [...html.matchAll(/\/socket\/[^"'<>?\s/]+\/[^"'<>?\s/]+\/(?:WebPage|web-page)\b/g)]
    .map(match => match[0]);
  return [...new Set(paths)].map(path => ({
    type: 'page',
    url: 'tauri://localhost',
    webSocketDebuggerUrl: `ws://127.0.0.1:${port}${path}`,
  }));
}

export async function discoverWebKitInspectorTargets(port, { fetchImpl = fetch, timeoutMs = 2000 } = {}) {
  assert(Number.isInteger(port) && port > 0 && port <= 65535, 'Invalid WebKit inspector port');
  const response = await fetchImpl(`http://127.0.0.1:${port}/`, { signal: AbortSignal.timeout(timeoutMs) });
  assert(response.ok, `WebKit inspector discovery HTTP ${response.status}`);
  return parseWebKitInspectorTargets(await response.text(), port);
}
