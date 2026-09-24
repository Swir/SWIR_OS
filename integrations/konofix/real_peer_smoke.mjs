import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';

const [portARaw, portBRaw] = process.argv.slice(2);
const portA = Number(portARaw);
const portB = Number(portBRaw);
for (const port of [portA, portB]) {
  assert(Number.isInteger(port) && port > 0 && port <= 65535, 'Expected two loopback WebView2 debug ports');
}
assert.notEqual(portA, portB, 'Client debug ports must be distinct');

const DEADLINE_MS = 55_000;
const nickA = `SwirCI_A_${process.pid}`;
const nickB = `SwirCI_B_${process.pid}`;
const nickB2 = `SwirCI_R_${process.pid}`;
const publicTokenA = `swir-public-a-${Date.now()}-${process.pid}`;
const publicTokenB = `swir-public-b-${Date.now()}-${process.pid}`;
const roomToken = `swir-room-${Date.now()}-${process.pid}`;
const privateTokenA = `swir-private-a-${Date.now()}-${process.pid}`;
const privateTokenB = `swir-private-b-${Date.now()}-${process.pid}`;
const reconnectToken = `swir-reconnect-${Date.now()}-${process.pid}`;
const roomName = `SWIR_CI_${process.pid}`;
const roomPassword = `swir-ci-${process.pid}-protected`;

function assertLoopbackUrl(raw, expectedPort) {
  const url = new URL(raw);
  assert(['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname), `Refusing non-loopback DevTools URL: ${url.hostname}`);
  if (url.port) assert.equal(Number(url.port), expectedPort, 'Unexpected DevTools port');
  return url;
}

async function pages(port) {
  const response = await fetch(`http://127.0.0.1:${port}/json/list`, { signal: AbortSignal.timeout(2000) });
  assert(response.ok, `DevTools discovery HTTP ${response.status}`);
  const list = await response.json();
  assert(Array.isArray(list), 'DevTools page list is not an array');
  return list.filter(item => item?.type === 'page' && item.webSocketDebuggerUrl);
}

async function page(port) {
  const list = await pages(port);
  const preferred = list.find(item => /^https?:\/\/tauri\.localhost(?:\/|$)/.test(item.url ?? '')) ?? list[0];
  if (!preferred) throw new Error(`No page target exposed on debug port ${port}`);
  assertLoopbackUrl(preferred.webSocketDebuggerUrl, port);
  return preferred;
}

async function evaluate(port, expression) {
  const target = await page(port);
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(target.webSocketDebuggerUrl);
    const requestId = Math.floor(Math.random() * 1_000_000_000) + 1;
    const timer = setTimeout(() => finish(new Error(`Runtime.evaluate timed out on ${port}`)), 3500);
    let finished = false;
    function finish(error, value) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      try { socket.close(); } catch {}
      if (error) reject(error); else resolve(value);
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

async function eventually(port, expression, description, { timeout = DEADLINE_MS, interval = 350 } = {}) {
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

async function waitForLogin(port) {
  return eventually(port, `document.readyState === 'complete' && !!document.querySelector('#nick') && !!document.querySelector('#connectBtn')`, 'Konofix login UI');
}

async function connect(port, nick, bootstraps) {
  await waitForLogin(port);
  const setup = `(() => {
    localStorage.setItem('konofix.bootstraps', ${JSON.stringify(JSON.stringify(bootstraps))});
    const input = document.querySelector('#nick');
    const button = document.querySelector('#connectBtn');
    if (!input || !button) return false;
    input.value = ${JSON.stringify(nick)};
    input.dispatchEvent(new Event('input', { bubbles: true }));
    button.click();
    return true;
  })()`;
  assert.equal(await evaluate(port, setup), true, `Failed to start ${nick}`);
  await eventually(port, `!!document.querySelector('.chat-shell') && document.querySelector('.me-info strong')?.textContent?.trim() === ${JSON.stringify(nick)}`, `${nick} chat shell`);
}

async function listenAddresses(port) {
  await evaluate(port, `(() => { document.querySelector('#networkCard')?.click(); return true; })()`);
  const addresses = await eventually(port, `(() => {
    const values = [...document.querySelectorAll('#networkModal [data-copy-address]')].map(node => node.dataset.copyAddress).filter(Boolean);
    return values.length ? values : false;
  })()`, 'listen addresses');
  await evaluate(port, `(() => { document.querySelector('#closeModal')?.click(); return true; })()`);
  return addresses;
}

function loopbackBootstrap(addresses) {
  const candidates = addresses.filter(value => typeof value === 'string' && value.includes('/p2p/'));
  const preferred = candidates.find(value => value.includes('/tcp/')) ?? candidates.find(value => value.includes('/quic-v1')) ?? candidates[0];
  assert(preferred, `No dialable P2P listen address: ${JSON.stringify(addresses)}`);
  let result = preferred
    .replace('/ip4/0.0.0.0/', '/ip4/127.0.0.1/')
    .replace('/ip6/::/', '/ip6/::1/');
  assert(result.includes('/p2p/'), 'Bootstrap must be bound to the exact peer id');
  assert(!result.includes('/ip4/0.0.0.0/'), 'Wildcard IPv4 address was not normalized');
  return result;
}

async function waitForPeer(port, nick) {
  return eventually(port, `(() => [...document.querySelectorAll('#peerList .user strong')].some(node => node.textContent?.trim() === ${JSON.stringify(nick)}))()`, `${nick} peer presence`);
}

async function sendPublic(port, token) {
  const sent = await evaluate(port, `(() => {
    const input = document.querySelector('#msg');
    const button = document.querySelector('#send');
    if (!input || !button) return false;
    input.value = ${JSON.stringify(token)};
    input.dispatchEvent(new Event('input', { bubbles: true }));
    button.click();
    return true;
  })()`);
  assert.equal(sent, true, 'Public message composer was unavailable');
}

async function waitForMessage(port, token, selector = '#messages') {
  return eventually(port, `document.querySelector(${JSON.stringify(selector)})?.textContent?.includes(${JSON.stringify(token)}) === true`, `message ${token}`);
}

async function createProtectedRoom(port) {
  assert.equal(await evaluate(port, `(() => { document.querySelector('#newRoom')?.click(); return !!document.querySelector('#secureRoomCreateModal'); })()`), true,
    'Secure room dialog did not open');
  const submitted = await evaluate(port, `(() => {
    const name = document.querySelector('#secureRoomName');
    const password = document.querySelector('#secureRoomPassword');
    const submit = document.querySelector('[data-room-create-submit]');
    if (!name || !password || !submit) return false;
    name.value = ${JSON.stringify(roomName)};
    password.value = ${JSON.stringify(roomPassword)};
    name.dispatchEvent(new Event('input', { bubbles: true }));
    password.dispatchEvent(new Event('input', { bubbles: true }));
    submit.click();
    return true;
  })()`);
  assert.equal(submitted, true, 'Secure room form was unavailable');
  return eventually(port, `(() => {
    const button = [...document.querySelectorAll('button[data-room]')].find(node => node.dataset.room !== 'world' && node.textContent?.includes(${JSON.stringify(roomName)}));
    return button?.dataset.room || false;
  })()`, 'protected room creation');
}

async function enterProtectedRoom(port, roomId) {
  const entered = await evaluate(port, `(() => {
    const button = document.querySelector('button[data-room=${JSON.stringify(roomId)}]');
    if (!button) return false;
    const originalPrompt = window.prompt;
    window.prompt = () => ${JSON.stringify(roomPassword)};
    try { button.click(); } finally { setTimeout(() => { window.prompt = originalPrompt; }, 0); }
    return true;
  })()`);
  assert.equal(entered, true, 'Protected room button was unavailable');
  await eventually(port, `document.querySelector('.chat-header h2')?.textContent?.includes(${JSON.stringify(roomName)}) === true`, 'protected room entry');
}

async function openPrivate(port, nick) {
  const opened = await evaluate(port, `(() => {
    const row = [...document.querySelectorAll('#peerList .user')].find(node => node.querySelector('strong')?.textContent?.trim() === ${JSON.stringify(nick)});
    const button = row?.querySelector('[data-private-peer]');
    if (!button) return false;
    button.click();
    return true;
  })()`);
  assert.equal(opened, true, `Private-chat button for ${nick} is unavailable`);
  await eventually(port, `!!document.querySelector('#privateChatModal [data-private-input]')`, 'private-chat composer');
}

async function sendPrivate(port, token) {
  const sent = await evaluate(port, `(() => {
    const input = document.querySelector('#privateChatModal [data-private-input]');
    const button = document.querySelector('#privateChatModal [data-private-send]');
    if (!input || !button) return false;
    input.value = ${JSON.stringify(token)};
    input.dispatchEvent(new Event('input', { bubbles: true }));
    button.click();
    return true;
  })()`);
  assert.equal(sent, true, 'Private message composer was unavailable');
}

async function disconnect(port) {
  await evaluate(port, `(() => { document.querySelector('#disconnect')?.click(); return true; })()`);
  await waitForLogin(port);
}

await Promise.all([waitForLogin(portA), waitForLogin(portB)]);
await connect(portA, nickA, []);
const address = loopbackBootstrap(await listenAddresses(portA));
await connect(portB, nickB, [address]);
await Promise.all([waitForPeer(portA, nickB), waitForPeer(portB, nickA)]);

await sendPublic(portA, publicTokenA);
await waitForMessage(portB, publicTokenA);
await sendPublic(portB, publicTokenB);
await waitForMessage(portA, publicTokenB);

const roomId = await createProtectedRoom(portA);
await eventually(portB, `!!document.querySelector('button[data-room=${JSON.stringify(roomId)}]')`, 'protected room propagation');
await enterProtectedRoom(portB, roomId);
await eventually(portA, `document.querySelector('.chat-header h2')?.textContent?.includes(${JSON.stringify(roomName)}) === true`, 'owner protected room entry');
await sendPublic(portB, roomToken);
await waitForMessage(portA, roomToken);

await openPrivate(portA, nickB);
await sendPrivate(portA, privateTokenA);
await eventually(portB, `document.querySelector('.private-notice-preview')?.textContent?.includes(${JSON.stringify(privateTokenA)}) === true`, 'incoming private notification');
assert.equal(await evaluate(portB, `(() => { document.querySelector('[data-private-open-notice]')?.click(); return !!document.querySelector('#privateChatModal'); })()`), true,
  'Incoming private notification could not be opened');
await waitForMessage(portB, privateTokenA, '#privateChatModal');
await sendPrivate(portB, privateTokenB);
await waitForMessage(portA, privateTokenB, '#privateChatModal');

await disconnect(portB);
await connect(portB, nickB2, [address]);
await waitForPeer(portA, nickB2);
await sendPublic(portB, reconnectToken);
await waitForMessage(portA, reconnectToken);

console.log(JSON.stringify({
  schema: 'swir.konofix-real-peer-smoke/0.1',
  clients: 2,
  transport: address.includes('/tcp/') ? 'tcp-loopback-direct' : 'quic-loopback-direct',
  publicMessages: 3,
  protectedRoom: true,
  protectedRoomMessage: true,
  privateMessages: 2,
  reconnect: true,
  fileTransfer: 'not-qualified-by-this-smoke',
  remoteNetworkPromotionEvidence: false,
}, null, 2));
