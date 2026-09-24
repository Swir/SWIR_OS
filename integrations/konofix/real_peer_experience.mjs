import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';

const [portARaw, portBRaw] = process.argv.slice(2);
const portA = Number(portARaw);
const portB = Number(portBRaw);
for (const port of [portA, portB]) {
  assert(Number.isInteger(port) && port > 0 && port <= 65535, 'Expected two loopback WebView2 debug ports');
}
assert.notEqual(portA, portB, 'Client debug ports must be distinct');
assert.equal(process.platform, 'win32', 'Published-client experience E2E is Windows-only');
assert.equal(process.env.GITHUB_ACTIONS, 'true', 'Published-client experience E2E is restricted to disposable GitHub Actions');

const DEADLINE_MS = 35_000;
const nickA = `SwirCI_A_${process.pid}`;
const nickB = `SwirCI_R_${process.pid}`;
const ignoredToken = `swir-ignore-first-${Date.now()}-${process.pid}`;
const silentToken = `swir-ignore-silent-${Date.now()}-${process.pid}`;
const blockedToken = `swir-private-block-${Date.now()}-${process.pid}`;

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

async function closePrivate(port) {
  await evaluate(port, `(() => { document.querySelector('#privateChatModal [data-private-close]')?.click(); return true; })()`);
  await eventually(port, `!document.querySelector('#privateChatModal')`, 'private chat close', { timeout: 5000 });
}

async function openPrivate(port, nick) {
  await closePrivate(port);
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
  assert.equal(sent, true, `Private message composer unavailable for ${token}`);
}

async function openNetworkSettings(port) {
  const opened = await evaluate(port, `(() => { document.querySelector('#networkSettings')?.click(); return true; })()`);
  assert.equal(opened, true, 'Network settings button was unavailable');
  await eventually(port, `!!document.querySelector('#networkModal [data-private-enabled]')`, 'private-message policy control');
}

async function setPrivateMessages(port, enabled) {
  await openNetworkSettings(port);
  const changed = await evaluate(port, `(() => {
    const control = document.querySelector('#networkModal [data-private-enabled]');
    if (!control) return false;
    control.checked = ${enabled ? 'true' : 'false'};
    control.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  })()`);
  assert.equal(changed, true, 'Private-message policy control could not be changed');
  await eventually(port, `localStorage.getItem('konofix.privateMessagesEnabled') === ${JSON.stringify(enabled ? '1' : '0')}`, 'private-message policy persistence');
  await evaluate(port, `(() => { document.querySelector('#closeModal')?.click(); return true; })()`);
  await eventually(port, `!document.querySelector('#networkModal')`, 'network settings close', { timeout: 5000 });
}

await Promise.all([
  eventually(portA, `!!document.querySelector('.chat-shell')`, 'client A chat shell'),
  eventually(portB, `!!document.querySelector('.chat-shell')`, 'client B chat shell'),
]);

for (const port of [portA, portB]) {
  assert.equal(await evaluate(port, `(() => {
    const shell = document.querySelector('.chat-shell');
    const brand = document.querySelector('.logo-row strong')?.textContent?.trim();
    const settings = document.querySelector('#networkSettings');
    const composer = document.querySelector('#msg');
    return !!shell && brand === 'Konofix Chat' && !!settings?.getAttribute('title') && !!composer?.getAttribute('placeholder');
  })()`), true, 'Konofix branding or accessible chat controls are missing');
}

// Session ignore: a genuine incoming private notification is an accessible modal.
// Ignoring suppresses later notices from that peer but does not delete messages;
// manually reopening the conversation restores access to its session history.
await openPrivate(portA, nickB);
await sendPrivate(portA, ignoredToken);
await eventually(portB, `document.querySelector('.private-notice-preview')?.textContent?.includes(${JSON.stringify(ignoredToken)}) === true`, 'incoming private notice');
assert.equal(await evaluate(portB, `(() => {
  const modal = document.querySelector('.private-notice-modal');
  const titleId = modal?.getAttribute('aria-labelledby');
  return modal?.getAttribute('role') === 'dialog' && modal?.getAttribute('aria-modal') === 'true' && !!titleId && !!document.getElementById(titleId) && !!modal.querySelector('[data-private-ignore]') && !!modal.querySelector('[data-private-open-notice]');
})()`), true, 'Incoming private notice is missing dialog accessibility semantics');
assert.equal(await evaluate(portB, `(() => { document.querySelector('[data-private-ignore]')?.click(); return !document.querySelector('.private-notice-wrap'); })()`), true,
  'Session ignore did not close the current private notice');

await sendPrivate(portA, silentToken);
await delay(1400);
assert.equal(await evaluate(portB, `!document.querySelector('.private-notice-wrap')`), true,
  'Ignored peer unexpectedly opened another private notification');
await openPrivate(portB, nickA);
for (const token of [ignoredToken, silentToken]) {
  await eventually(portB, `document.querySelector('#privateChatModal')?.textContent?.includes(${JSON.stringify(token)}) === true`, `ignored conversation retention ${token}`);
}
assert.equal(await evaluate(portB, `(() => {
  const modal = document.querySelector('#privateChatModal .private-chat-modal');
  const input = modal?.querySelector('[data-private-input]');
  const send = modal?.querySelector('[data-private-send]');
  return modal?.getAttribute('role') === 'dialog' && modal?.getAttribute('aria-modal') === 'true' && document.activeElement === input && !!input?.getAttribute('aria-label') && !!send?.getAttribute('aria-label');
})()`), true, 'Private chat focus or accessibility semantics are missing');

// User-controlled private-message mute: the runtime rejects a new private message
// while disabled, gives localized sender feedback and stores no rejected payload.
await closePrivate(portB);
await setPrivateMessages(portB, false);
await evaluate(portA, `(() => { globalThis.__swirPrivateAlert = ''; window.alert = message => { globalThis.__swirPrivateAlert = String(message); }; return true; })()`);
await sendPrivate(portA, blockedToken);
await eventually(portA, `typeof globalThis.__swirPrivateAlert === 'string' && globalThis.__swirPrivateAlert.length > 0`, 'blocked private-message sender feedback');
assert.equal(await evaluate(portA, `globalThis.__swirPrivateAlert.includes('not accepting') || globalThis.__swirPrivateAlert.includes('nie przyjmuje')`), true,
  'Blocked private-message feedback was not localized to the published client');
await openPrivate(portB, nickA);
assert.equal(await evaluate(portB, `!document.querySelector('#privateChatModal')?.textContent?.includes(${JSON.stringify(blockedToken)})`), true,
  'Disabled private-message policy still stored a rejected incoming message');
await closePrivate(portB);
await setPrivateMessages(portB, true);

// Locale selection/fallback is verified last because reload intentionally resets
// B's rendered UI. Branding remains Konofix and login regains keyboard focus.
assert.equal(await evaluate(portB, `(() => { localStorage.setItem('konofix.locale', 'pl'); location.reload(); return true; })()`), true, 'Polish locale reload failed');
await eventually(portB, `document.querySelector('#connectBtn')?.textContent?.trim() === 'Połącz z siecią'`, 'Polish locale rendering');
assert.equal(await evaluate(portB, `document.querySelector('.brand-panel h1')?.textContent?.includes('Konofix Chat') === true`), true, 'Konofix branding changed under Polish locale');
assert.equal(await evaluate(portB, `(() => { localStorage.setItem('konofix.locale', 'zz-ZZ'); location.reload(); return true; })()`), true, 'Unsupported locale reload failed');
await eventually(portB, `document.querySelector('#connectBtn')?.textContent?.trim() === 'Connect to network'`, 'English locale fallback');
assert.equal(await evaluate(portB, `(() => {
  const nick = document.querySelector('#nick');
  const group = document.querySelector('.nick-color-picker');
  const radios = [...document.querySelectorAll('.nick-color-swatch')];
  return document.activeElement === nick && group?.getAttribute('role') === 'radiogroup' && radios.length > 1 && radios.every(node => node.getAttribute('role') === 'radio' && node.hasAttribute('aria-checked'));
})()`), true, 'Login keyboard focus or radio accessibility semantics are missing after locale fallback');

console.log(JSON.stringify({
  schema: 'swir.konofix-real-experience-smoke/0.1',
  clients: 2,
  branding: true,
  privateNotification: true,
  privateIgnore: true,
  privateMessageMute: true,
  privateConversationRetention: true,
  dialogAccessibility: true,
  keyboardFocus: true,
  localePolish: true,
  unsupportedLocaleEnglishFallback: true,
  audioVideoQualified: false,
}, null, 2));
