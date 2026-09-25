import assert from 'node:assert/strict';
import { setTimeout as delay } from 'node:timers/promises';
import { parseWebKitTargetCreated, parseWebKitTargetDispatch, wrapWebKitTargetCommand } from './webkit_inspector_protocol.mjs';

export async function connectWebKitTarget(webSocketUrl, port, { WebSocketImpl = WebSocket, timeoutMs = 5000 } = {}) {
  const socket = new WebSocketImpl(webSocketUrl);
  const outerPending = new Map();
  const innerPending = new Map();
  const outerToInner = new Map();
  let nextOuterId = 1;
  let nextInnerId = 1;
  let targetId = null;
  let targetInfo = null;
  let closed = false;
  let resolveTarget;
  let rejectTarget;
  const targetReady = new Promise((resolve, reject) => { resolveTarget = resolve; rejectTarget = reject; });

  const failAll = error => {
    for (const map of [outerPending, innerPending]) {
      for (const waiter of map.values()) {
        clearTimeout(waiter.timer);
        waiter.reject(error);
      }
      map.clear();
    }
    outerToInner.clear();
  };

  const close = () => {
    if (closed) return;
    closed = true;
    const error = new Error(`WebKit inspector closed on ${port}`);
    failAll(error);
    rejectTarget(error);
    try { socket.close(); } catch {}
  };

  const requestOuter = (method, params = {}, requestTimeoutMs = timeoutMs) => {
    assert(!closed && socket.readyState === WebSocketImpl.OPEN, `WebKit inspector is not open on ${port}`);
    const id = nextOuterId++;
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        outerPending.delete(id);
        reject(new Error(`${method} timed out on ${port}`));
      }, requestTimeoutMs);
      outerPending.set(id, { resolve, reject, timer, method });
      socket.send(JSON.stringify({ id, method, params }));
    });
  };

  const request = (method, params = {}, requestTimeoutMs = timeoutMs) => {
    assert(!closed && socket.readyState === WebSocketImpl.OPEN, `WebKit inspector is not open on ${port}`);
    assert(targetId, `WebKit page target is not attached on ${port}`);
    const innerId = nextInnerId++;
    const outerId = nextOuterId++;
    const envelope = wrapWebKitTargetCommand(targetId, { id: innerId, method, params });
    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        innerPending.delete(innerId);
        outerToInner.delete(outerId);
        reject(new Error(`${method} timed out on target ${targetId} via ${port}`));
      }, requestTimeoutMs);
      innerPending.set(innerId, { resolve, reject, timer, method });
      outerToInner.set(outerId, innerId);
      socket.send(JSON.stringify({ id: outerId, ...envelope }));
    });
  };

  socket.addEventListener('message', event => {
    let message;
    try { message = JSON.parse(event.data); } catch { return; }

    const created = parseWebKitTargetCreated(message);
    if (created) {
      const info = message.params?.targetInfo ?? {};
      if (!targetId || info.isProvisional !== true) {
        targetId = created;
        targetInfo = info;
        resolveTarget(created);
      }
      return;
    }

    if (message?.method === 'Target.didCommitProvisionalTarget') {
      const { oldTargetId, newTargetId } = message.params ?? {};
      if (targetId === oldTargetId && typeof newTargetId === 'string' && newTargetId) {
        targetId = newTargetId;
        targetInfo = { ...targetInfo, targetId: newTargetId, isProvisional: false, isPaused: false };
      }
      return;
    }

    const dispatched = parseWebKitTargetDispatch(message);
    if (dispatched && Number.isInteger(dispatched.message?.id)) {
      const waiter = innerPending.get(dispatched.message.id);
      if (!waiter) return;
      innerPending.delete(dispatched.message.id);
      clearTimeout(waiter.timer);
      if (dispatched.message.error || dispatched.message.result?.exceptionDetails || dispatched.message.result?.wasThrown) {
        waiter.reject(new Error(`${waiter.method} failed: ${JSON.stringify(dispatched.message.error ?? dispatched.message.result?.exceptionDetails ?? dispatched.message.result)}`));
      } else {
        waiter.resolve(dispatched.message.result);
      }
      return;
    }

    if (!Number.isInteger(message?.id)) return;
    const linked = outerToInner.get(message.id);
    if (linked !== undefined) {
      outerToInner.delete(message.id);
      if (message.error) {
        const waiter = innerPending.get(linked);
        if (waiter) {
          innerPending.delete(linked);
          clearTimeout(waiter.timer);
          waiter.reject(new Error(`Target.sendMessageToTarget failed: ${JSON.stringify(message.error)}`));
        }
      }
      return;
    }

    const waiter = outerPending.get(message.id);
    if (!waiter) return;
    outerPending.delete(message.id);
    clearTimeout(waiter.timer);
    if (message.error) waiter.reject(new Error(`${waiter.method} failed: ${JSON.stringify(message.error)}`));
    else waiter.resolve(message.result);
  });

  socket.addEventListener('close', () => {
    if (closed) return;
    closed = true;
    const error = new Error(`WebKit inspector disconnected on ${port}`);
    failAll(error);
    rejectTarget(error);
  });
  socket.addEventListener('error', () => {
    const error = new Error(`WebKit inspector WebSocket failed on ${port}`);
    failAll(error);
    rejectTarget(error);
  });

  await new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`WebKit inspector open timed out on ${port}`)), timeoutMs);
    socket.addEventListener('open', () => { clearTimeout(timer); resolve(); }, { once: true });
    socket.addEventListener('error', () => { clearTimeout(timer); reject(new Error(`WebKit inspector open failed on ${port}`)); }, { once: true });
  });

  await Promise.race([
    targetReady,
    delay(timeoutMs).then(() => { throw new Error(`WebKit page target did not appear on ${port}`); }),
  ]);

  await requestOuter('Target.setPauseOnStart', { pauseOnStart: false });
  await request('Inspector.enable', {});
  if (targetInfo?.isPaused === true) {
    await requestOuter('Target.resume', { targetId });
    targetInfo = { ...targetInfo, isPaused: false };
  }

  return { socket, request, close };
}
