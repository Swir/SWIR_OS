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
    assert.equal(MockWebSocket.latest.sent.length, 0, 'adapter must wait for Target.targetCreated');

    MockWebSocket.latest.receive({
      method: 'Target.targetCreated',
      params: { targetInfo: { targetId: 'page-7', isProvisional: false, isPaused: false } },
    });

    const outerMethods = MockWebSocket.latest.sent.map(message => message.method);
    assert.equal(outerMethods[0], 'Target.setPauseOnStart');

    const innerMessages = MockWebSocket.latest.sent
      .filter(message => message.method === 'Target.sendMessageToTarget')
      .map(message => JSON.parse(message.params.message));
    assert.deepEqual(
      innerMessages.slice(0, 3).map(message => message.method),
      ['Inspector.enable', 'Runtime.enable', 'Inspector.initialized'],
      'WebKit target must be initialized before caller Runtime commands',
    );
    assert.equal(new Set(innerMessages.slice(0, 3).map(message => message.id)).size, 3, 'internal ids must be unique');

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
