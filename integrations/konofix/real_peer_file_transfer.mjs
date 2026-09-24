import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { spawn } from 'node:child_process';
import { readFile, stat, unlink, writeFile } from 'node:fs/promises';
import { basename, join, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';
import { setTimeout as delay } from 'node:timers/promises';

const [portARaw, portBRaw] = process.argv.slice(2);
const portA = Number(portARaw);
const portB = Number(portBRaw);
for (const port of [portA, portB]) {
  assert(Number.isInteger(port) && port > 0 && port <= 65535, 'Expected two loopback WebView2 debug ports');
}
assert.notEqual(portA, portB, 'Client debug ports must be distinct');
assert.equal(process.platform, 'win32', 'Real file-transfer E2E is Windows-only because it qualifies the published Windows client');
assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Real file-transfer E2E is restricted to disposable GitHub Actions');
assert(process.env.RUNNER_TEMP, 'RUNNER_TEMP is required for isolated transfer fixtures');

const DEADLINE_MS = 55_000;
const nickA = `SwirCI_A_${process.pid}`;
const nickB = `SwirCI_R_${process.pid}`;
const pickerScript = fileURLToPath(new URL('./select_file_dialog.ps1', import.meta.url));
const tempRoot = resolve(process.env.RUNNER_TEMP);
const fixtureRoot = resolve(tempRoot, `swir-konofix-transfer-${process.pid}-${Date.now()}`);
assert(fixtureRoot.startsWith(`${tempRoot}${sep}`), 'Fixture root escaped RUNNER_TEMP');

function assertLoopbackUrl(raw, expectedPort) {
  const url = new URL(raw);
  assert(['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname), `Refusing non-loopback DevTools URL: ${url.hostname}`);
  if (url.port) assert.equal(Number(url.port), expectedPort, 'Unexpected DevTools port');
  return url;
}

async function page(port) {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(2000) });
  assert(response.ok, `DevTools discovery HTTP ${response.status}`);
  const list = await response.json();
  assert(Array.isArray(list), 'DevTools page list is not an array');
  const preferred = list.find(item => item?.type === 'page' && /^https?:\/\/tauri\.localhost(?:\/|$)/.test(item.url ?? '') && item.webSocketDebuggerUrl)
    ?? list.find(item => item?.type === 'page' && item.webSocketDebuggerUrl);
  if (!preferred) throw new Error(`No page target exposed on debug port ${port}`);
  assertLoopbackUrl(preferred.webSocketDebuggerUrl, port);
  return preferred;
}

async function evaluate(port, expression) {
  const target = await page(port);
  return new Promise((resolveValue, reject) => {
    const socket = new WebSocket(target.webSocketDebuggerUrl);
    const requestId = Math.floor(Math.random() * 1_000_000_000) + 1;
    const timer = setTimeout(() => finish(new Error(`Runtime.evaluate timed out on ${port}`)), 3500);
    let finished = false;
    function finish(error, value) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      try { socket.close(); } catch {}
      if (error) reject(error); else resolveValue(value);
    }
    socket.addEventListener('error', () => finish(new Error(`DevTools WebSocket failed on ${port}`)), { once: true });
    socket.addEventListener('open', () => socket.send(JSON.stringify({
      id: requestId,
      method: 'Runtime.evaluate',
      params: { expression, awaitPromise: true, returnByValue: true },
    })), { once: true });
    socket.addEventListener('message', event => {
      let message;
      try { message = JSON.parse(event.data); } catch (error) { finish(error); return; }
      if (message.id !== requestId) return;
      if (message.error || message.result?.exceptionDetails) {
        finish(new Error(`Runtime.evaluate failed: ${JSON.stringify(message.error ?? message.result?.exceptionDetails)}`));
        return;
      }
      finish(null, message.result?.result?.value);
    });
  });
}

async function eventually(port, expression, description, { timeout = DEADLINE_MS, interval = 300 } = {}) {
  const deadline = Date.now() + timeout;
  let last;
  while (Date.now() < deadline) {
    try {
      const value = await evaluate(port, expression);
      if (value) return value;
      last = value;
    } catch (error) {
      last = error;
    }
    await delay(interval);
  }
  throw new Error(`${description} did not become true on ${port}; last=${last instanceof Error ? last.message : JSON.stringify(last)}`);
}

function runPicker(path) {
  return new Promise((resolveValue, reject) => {
    const child = spawn('powershell.exe', [
      '-NoLogo', '-NoProfile', '-NonInteractive', '-ExecutionPolicy', 'Bypass',
      '-File', pickerScript, '-Path', path, '-TimeoutSeconds', '20',
    ], { stdio: 'inherit', windowsHide: true });
    const timer = setTimeout(() => {
      child.kill();
      reject(new Error('Konofix native file picker automation timed out'));
    }, 25_000);
    child.once('error', error => {
      clearTimeout(timer);
      reject(error);
    });
    child.once('exit', code => {
      clearTimeout(timer);
      if (code === 0) resolveValue();
      else reject(new Error(`Konofix native file picker automation failed with exit code ${code}`));
    });
  });
}

async function waitForPeer(port, nick) {
  return eventually(port, `(() => [...document.querySelectorAll('#peerList .user strong')].some(node => node.textContent?.trim() === ${JSON.stringify(nick)}))()`, `${nick} peer presence`);
}

async function startOffer(filePath) {
  const fileName = basename(filePath);
  const clicked = await evaluate(portA, `(() => {
    const row = [...document.querySelectorAll('#peerList .user')].find(node => node.querySelector('strong')?.textContent?.trim() === ${JSON.stringify(nickB)});
    const button = row?.querySelector('[data-send-peer]');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  assert.equal(clicked, true, `File-transfer button for ${nickB} was unavailable`);
  await runPicker(filePath);
  const transferId = await eventually(portB, `(() => {
    const modal = [...document.querySelectorAll('.file-offer-wrap')].find(node => node.querySelector('.offer-file strong')?.textContent?.trim() === ${JSON.stringify(fileName)});
    return modal?.id?.startsWith('file-offer-') ? modal.id.slice('file-offer-'.length) : false;
  })()`, `incoming file offer ${fileName}`);
  await eventually(portA, `(() => [...document.querySelectorAll('.transfer-card')].some(card => card.querySelector('.transfer-title strong')?.textContent?.trim() === ${JSON.stringify(fileName)} && card.classList.contains('waiting')))()`, `outgoing waiting transfer ${fileName}`);
  return { transferId, fileName };
}

async function rejectOffer(filePath) {
  const { transferId, fileName } = await startOffer(filePath);
  const rejected = await evaluate(portB, `(() => {
    const modal = document.querySelector(${JSON.stringify(`#file-offer-${transferId}`)});
    const button = modal?.querySelector('#rejectOffer');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  assert.equal(rejected, true, 'Reject button was unavailable');
  await eventually(portA, `(() => [...document.querySelectorAll('.transfer-card.rejected')].some(card => card.querySelector('.transfer-title strong')?.textContent?.trim() === ${JSON.stringify(fileName)}))()`, `rejected transfer ${fileName}`);
  await eventually(portB, `!document.querySelector(${JSON.stringify(`#file-offer-${transferId}`)})`, `rejected offer modal close ${fileName}`);
}

async function cancelOffer(filePath) {
  const { transferId, fileName } = await startOffer(filePath);
  const cancelled = await evaluate(portA, `(() => {
    const button = document.querySelector(${JSON.stringify(`[data-cancel-transfer="${transferId}"]`)});
    if (!button) return false;
    button.click();
    return true;
  })()`);
  assert.equal(cancelled, true, 'Cancel button was unavailable');
  await eventually(portA, `(() => [...document.querySelectorAll('.transfer-card.cancelled')].some(card => card.querySelector('.transfer-title strong')?.textContent?.trim() === ${JSON.stringify(fileName)}))()`, `cancelled transfer ${fileName}`);
  await eventually(portB, `!document.querySelector(${JSON.stringify(`#file-offer-${transferId}`)})`, `cancelled offer modal close ${fileName}`);
}

async function acceptOffer(filePath, expectedBytes) {
  const { transferId, fileName } = await startOffer(filePath);
  const accepted = await evaluate(portB, `(() => {
    const modal = document.querySelector(${JSON.stringify(`#file-offer-${transferId}`)});
    const button = modal?.querySelector('#acceptOffer');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  assert.equal(accepted, true, 'Accept button was unavailable');
  for (const port of [portA, portB]) {
    await eventually(port, `(() => [...document.querySelectorAll('.transfer-card.completed')].some(card => card.querySelector('.transfer-title strong')?.textContent?.trim() === ${JSON.stringify(fileName)}))()`, `completed transfer ${fileName}`);
  }
  const receivedPath = await eventually(portB, `(() => {
    const card = [...document.querySelectorAll('.transfer-card.completed')].find(node => node.querySelector('.transfer-title strong')?.textContent?.trim() === ${JSON.stringify(fileName)});
    const detail = card?.querySelector('small[title]');
    return detail?.getAttribute('title') || false;
  })()`, `saved path for ${fileName}`);
  assert.equal(basename(receivedPath).toLowerCase(), fileName.toLowerCase(), 'Received path does not match the offered filename');
  assert.notEqual(resolve(receivedPath), resolve(filePath), 'Received file unexpectedly aliases the outgoing fixture');
  const receivedBytes = await readFile(receivedPath);
  assert.deepEqual(receivedBytes, expectedBytes, 'Accepted transfer bytes differ from the offered fixture');
  const expectedDigest = createHash('sha256').update(expectedBytes).digest('hex');
  const receivedDigest = createHash('sha256').update(receivedBytes).digest('hex');
  assert.equal(receivedDigest, expectedDigest, 'Accepted transfer SHA-256 differs from the offered fixture');
  await unlink(receivedPath);
  return { expectedDigest, bytes: expectedBytes.length };
}

await Promise.all([waitForPeer(portA, nickB), waitForPeer(portB, nickA)]);
await stat(tempRoot);

const acceptedBytes = Buffer.from(`SWIR Konofix accepted transfer\r\n${process.pid}\r\n${Date.now()}\r\n`, 'utf8');
const rejectedBytes = Buffer.from(`SWIR Konofix rejected transfer\r\n${process.pid}\r\n`, 'utf8');
const cancelledBytes = Buffer.from(`SWIR Konofix cancelled transfer\r\n${process.pid}\r\n`, 'utf8');
const fixtures = [
  [join(fixtureRoot, `swir-accept-${process.pid}.txt`), acceptedBytes],
  [join(fixtureRoot, `swir-reject-${process.pid}.txt`), rejectedBytes],
  [join(fixtureRoot, `swir-cancel-${process.pid}.txt`), cancelledBytes],
];

await import('node:fs/promises').then(({ mkdir }) => mkdir(fixtureRoot, { recursive: true }));
try {
  for (const [path, bytes] of fixtures) await writeFile(path, bytes, { flag: 'wx' });
  const accepted = await acceptOffer(fixtures[0][0], acceptedBytes);
  await rejectOffer(fixtures[1][0]);
  await cancelOffer(fixtures[2][0]);
  console.log(JSON.stringify({
    schema: 'swir.konofix-real-file-transfer-smoke/0.1',
    clients: 2,
    accepted: true,
    rejected: true,
    cancelled: true,
    acceptedBytes: accepted.bytes,
    acceptedSha256: accepted.expectedDigest,
    dialogAutomationScope: 'disposable-windows-ci-only',
  }, null, 2));
} finally {
  for (const [path] of fixtures) {
    try { await unlink(path); } catch (error) { if (error?.code !== 'ENOENT') throw error; }
  }
  try { await import('node:fs/promises').then(({ rmdir }) => rmdir(fixtureRoot)); } catch {}
}
