import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';

const [portARaw] = process.argv.slice(2);
const portA = Number(portARaw);
assert(Number.isInteger(portA) && portA > 0 && portA <= 65535, 'Expected loopback WebView2 debug port A');

let stopped = false;

function assertLoopbackUrl(raw) {
  const url = new URL(raw);
  assert(['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname), `Refusing non-loopback DevTools URL: ${url.hostname}`);
  if (url.port) assert.equal(Number(url.port), portA, 'Unexpected DevTools port');
  return url;
}

async function currentPage() {
  const response = await fetch(`http://127.0.0.1:${portA}/json/list`, { signal: AbortSignal.timeout(1500) });
  if (!response.ok) return null;
  const list = await response.json();
  if (!Array.isArray(list)) return null;
  const page = list.find(item => item?.type === 'page' && /^https?:\/\/tauri\.localhost(?:\/|$)/.test(item.url ?? '') && item.webSocketDebuggerUrl)
    ?? list.find(item => item?.type === 'page' && item.webSocketDebuggerUrl);
  if (!page) return null;
  assertLoopbackUrl(page.webSocketDebuggerUrl);
  return page;
}

async function evaluate(expression) {
  const page = await currentPage();
  if (!page) return false;
  return new Promise((resolve, reject) => {
    const socket = new WebSocket(page.webSocketDebuggerUrl);
    const id = Math.floor(Math.random() * 1_000_000_000) + 1;
    const timer = setTimeout(() => finish(new Error('DevTools refresh probe timed out')), 1200);
    let finished = false;
    function finish(error, value) {
      if (finished) return;
      finished = true;
      clearTimeout(timer);
      try { socket.close(); } catch {}
      if (error) reject(error); else resolve(value);
    }
    socket.addEventListener('error', () => finish(new Error('DevTools refresh probe failed')), { once: true });
    socket.addEventListener('open', () => socket.send(JSON.stringify({
      id,
      method: 'Runtime.evaluate',
      params: { expression, returnByValue: true },
    })), { once: true });
    socket.addEventListener('message', event => {
      let message;
      try { message = JSON.parse(event.data); } catch (error) { finish(error); return; }
      if (message.id !== id) return;
      if (message.error || message.result?.exceptionDetails) {
        finish(new Error('DevTools refresh expression failed'));
        return;
      }
      finish(null, message.result?.result?.value);
    });
  });
}

async function refreshStaleNetworkModal() {
  while (!stopped) {
    try {
      await evaluate(`(() => {
        const modal = document.querySelector('#networkModal');
        if (!modal || modal.querySelector('[data-copy-address]') || !document.querySelector('.chat-shell')) return false;
        document.querySelector('#closeModal')?.click();
        document.querySelector('#networkCard')?.click();
        return true;
      })()`);
    } catch {
      // The client may still be starting, re-rendering, or closing. The core
      // smoke owns the actual timeout/failure decision; this helper only keeps
      // its network-modal snapshot fresh while listen addresses are pending.
    }
    await delay(500);
  }
}

const refresher = refreshStaleNetworkModal();
try {
  await import('./real_peer_smoke_core.mjs');
  // Keep the same two published clients alive and qualify real file-transfer
  // outcomes after the messaging/reconnect smoke has established a healthy P2P session.
  await import('./real_peer_file_transfer.mjs');
  // Finish the acceptance surface on the same published clients: real private
  // notification/ignore policy, user-controlled private-message mute, keyboard
  // and dialog accessibility, Konofix branding, Polish locale, and English
  // fallback for an unsupported locale.
  await import('./real_peer_experience.mjs');
} finally {
  stopped = true;
  await refresher;
}
