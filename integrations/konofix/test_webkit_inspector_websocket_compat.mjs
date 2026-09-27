import assert from 'node:assert/strict';
import test from 'node:test';
import { installWebKitInspectorWebSocketCompat } from './webkit_inspector_websocket_compat.mjs';

class MockWebSocket extends EventTarget {
  static CONNECTING = 0;
  static OPEN = 1;
  static CLOSING = 2;
  static CLOSED = 3;
  static latest = null;

  constructor(url) {
    super();
    this.url = url;
    this.readyState = MockWebSocket.CONNECTING;
    this.sent = [];
    MockWebSocket.latest = this;
  }

  send(raw) { this.sent.push(JSON.parse(raw)); }

  close() {
    this.readyState = MockWebSocket.CLOSED;
    this.dispatchEvent(new Event('close'));
  }

  open() {
    this.readyState = MockWebSocket.OPEN;
    this.dispatchEvent(new Event('open'));
  }

  receive(message) {
    this.dispatchEvent(new MessageEvent('message', { data: JSON.stringify(message) }));
  }
}

test('adapts Runtime.evaluate through WebKit Target control plane', () => {
  const restore = installWebKitInspectorWebSocketCompat({ WebSocketImpl: MockWebSocket });
  try {
    const socket = new WebSocket('ws://127.0.0.1:9331/socket/1/7/WebPage');
    const received = [];
    socket.addEventListener('message', event => received.push(JSON.parse(event.data)));
    MockWebSocket.latest.open();

    socket.send(JSON.stringify({
      id: 41,
      method: 'Runtime.evaluate',
      params: { expression: '1 + 1', returnByValue: true },
    }));
    assert.equal(MockWebSocket.latest.sent[0].method, 'Target.setPauseOnStart');

    MockWebSocket.latest.receive({
      method: 'Target.targetCreated',
      params: { targetInfo: { targetId: 'page-7', isProvisional: false, isPaused: false } },
    });

    const envelope = MockWebSocket.latest.sent.find(message => {
      if (message.method !== 'Target.sendMessageToTarget') return false;
      return JSON.parse(message.params.message).id === 41;
    });
    assert(envelope, 'queued Runtime command was not forwarded to the page target');
    assert.equal(envelope.params.targetId, 'page-7');
    assert.deepEqual(JSON.parse(envelope.params.message), {
      id: 41,
      method: 'Runtime.evaluate',
      params: { expression: '1 + 1', returnByValue: true },
    });

    MockWebSocket.latest.receive({
      method: 'Target.dispatchMessageFromTarget',
      params: {
        targetId: 'page-7',
        message: JSON.stringify({ id: 41, result: { result: { value: 2 } } }),
      },
    });
    assert.deepEqual(received, [{ id: 41, result: { result: { value: 2 } } }]);
  } finally {
    restore();
  }
});
