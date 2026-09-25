import assert from 'node:assert/strict';
import test from 'node:test';
import { parseWebKitTargetCreated, parseWebKitTargetDispatch, wrapWebKitTargetCommand } from './webkit_inspector_protocol.mjs';

test('extracts WebKit page target id', () => {
  assert.equal(parseWebKitTargetCreated({ method: 'Target.targetCreated', params: { targetInfo: { targetId: 'page-7' } } }), 'page-7');
  assert.equal(parseWebKitTargetCreated({ method: 'Runtime.executionContextCreated' }), null);
});

test('wraps page commands in Target.sendMessageToTarget', () => {
  const envelope = wrapWebKitTargetCommand('page-7', {
    id: 41,
    method: 'Runtime.evaluate',
    params: { expression: '1 + 1' },
  });
  assert.equal(envelope.method, 'Target.sendMessageToTarget');
  assert.equal(envelope.params.targetId, 'page-7');
  assert.deepEqual(JSON.parse(envelope.params.message), {
    id: 41,
    method: 'Runtime.evaluate',
    params: { expression: '1 + 1' },
  });
});

test('unwraps Target.dispatchMessageFromTarget', () => {
  assert.deepEqual(parseWebKitTargetDispatch({
    method: 'Target.dispatchMessageFromTarget',
    params: {
      targetId: 'page-7',
      message: JSON.stringify({ id: 41, result: { result: { value: 2 } } }),
    },
  }), {
    targetId: 'page-7',
    message: { id: 41, result: { result: { value: 2 } } },
  });
  assert.equal(parseWebKitTargetDispatch({
    method: 'Target.dispatchMessageFromTarget',
    params: { targetId: 'page-7', message: '{' },
  }), null);
});

test('invalid outbound commands fail closed', () => {
  assert.throws(() => wrapWebKitTargetCommand('', { id: 1, method: 'Runtime.evaluate', params: {} }));
  assert.throws(() => wrapWebKitTargetCommand('page-7', { id: '1', method: 'Runtime.evaluate', params: {} }));
});
