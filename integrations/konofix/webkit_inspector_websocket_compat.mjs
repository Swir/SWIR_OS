import { wrapWebKitTargetCommand } from './webkit_inspector_protocol.mjs';

export function installWebKitInspectorWebSocketCompat({ WebSocketImpl = globalThis.WebSocket } = {}) {
  if (!WebSocketImpl) throw new Error('WebSocket implementation is unavailable');
  const previous = globalThis.WebSocket;
  const OPEN = WebSocketImpl.OPEN ?? 1;

  class WebKitTargetWebSocket {
    static CONNECTING = WebSocketImpl.CONNECTING ?? 0;
    static OPEN = OPEN;
    static CLOSING = WebSocketImpl.CLOSING ?? 2;
    static CLOSED = WebSocketImpl.CLOSED ?? 3;

    constructor(url) {
      this._socket = new WebSocketImpl(url);
      this._events = new EventTarget();
      this._targetId = null;
      this._targetInfo = null;
      this._queued = [];
      this._nextOuterId = 1_500_000_000;
      this._outerToInner = new Map();
      this._internalOuterIds = new Set();
      this._internalInnerIds = new Set();

      this._socket.addEventListener('open', () => this._events.dispatchEvent(new Event('open')));
      this._socket.addEventListener('error', () => this._events.dispatchEvent(new Event('error')));
      this._socket.addEventListener('close', () => this._events.dispatchEvent(new Event('close')));
      this._socket.addEventListener('message', event => this._onMessage(event.data));
    }

    get readyState() { return this._socket.readyState; }

    addEventListener(type, listener, options) { this._events.addEventListener(type, listener, options); }
    removeEventListener(type, listener, options) { this._events.removeEventListener(type, listener, options); }
    close(...args) { return this._socket.close(...args); }

    send(data) {
      let message;
      try { message = JSON.parse(data); } catch { return this._socket.send(data); }
      if (!Number.isInteger(message?.id) || typeof message?.method !== 'string') {
        return this._socket.send(data);
      }
      if (message.method.startsWith('Target.')) return this._socket.send(data);
      if (!this._targetId) {
        this._queued.push(message);
        return;
      }
      this._sendInner(message);
    }

    _sendOuter(method, params) {
      const id = this._nextOuterId++;
      this._internalOuterIds.add(id);
      this._socket.send(JSON.stringify({ id, method, params }));
      return id;
    }

    _sendInner(message, { internal = false } = {}) {
      const outerId = this._nextOuterId++;
      if (internal) {
        this._internalOuterIds.add(outerId);
        this._internalInnerIds.add(message.id);
      } else {
        this._outerToInner.set(outerId, message.id);
      }
      const envelope = wrapWebKitTargetCommand(this._targetId, message);
      this._socket.send(JSON.stringify({ id: outerId, ...envelope }));
    }

    _bootstrapTarget(info) {
      this._sendOuter('Target.setPauseOnStart', { pauseOnStart: false });
      this._sendInner({ id: 1_400_000_000, method: 'Inspector.enable', params: {} }, { internal: true });
      if (info?.isPaused === true) this._sendOuter('Target.resume', { targetId: this._targetId });
      const queued = this._queued.splice(0);
      for (const message of queued) this._sendInner(message);
    }

    _emitInner(inner) {
      if (this._internalInnerIds.delete(inner?.id)) return;
      this._events.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(inner) }));
    }

    _onMessage(raw) {
      let message;
      try { message = JSON.parse(raw); } catch {
        this._events.dispatchEvent(new MessageEvent('message', { data: raw }));
        return;
      }

      if (message?.method === 'Target.targetCreated') {
        const info = message.params?.targetInfo ?? {};
        const targetId = info.targetId;
        if (typeof targetId === 'string' && targetId && (!this._targetId || info.isProvisional !== true)) {
          this._targetId = targetId;
          this._targetInfo = info;
          this._bootstrapTarget(info);
        }
        return;
      }

      if (message?.method === 'Target.didCommitProvisionalTarget') {
        const { oldTargetId, newTargetId } = message.params ?? {};
        if (this._targetId === oldTargetId && typeof newTargetId === 'string' && newTargetId) {
          this._targetId = newTargetId;
          this._targetInfo = { ...this._targetInfo, targetId: newTargetId, isProvisional: false, isPaused: false };
        }
        return;
      }

      if (message?.method === 'Target.targetDestroyed' && message.params?.targetId === this._targetId) {
        this._targetId = null;
        this._targetInfo = null;
        return;
      }

      if (message?.method === 'Target.dispatchMessageFromTarget') {
        if (message.params?.targetId !== this._targetId || typeof message.params?.message !== 'string') return;
        try { this._emitInner(JSON.parse(message.params.message)); } catch {}
        return;
      }

      if (Number.isInteger(message?.id)) {
        if (this._internalOuterIds.delete(message.id)) return;
        const innerId = this._outerToInner.get(message.id);
        if (innerId !== undefined) {
          this._outerToInner.delete(message.id);
          if (message.error) this._emitInner({ id: innerId, error: message.error });
          return;
        }
      }

      this._events.dispatchEvent(new MessageEvent('message', { data: raw }));
    }
  }

  globalThis.WebSocket = WebKitTargetWebSocket;
  return () => { globalThis.WebSocket = previous; };
}
