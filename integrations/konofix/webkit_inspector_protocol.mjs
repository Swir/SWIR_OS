import assert from 'node:assert/strict';

export function parseWebKitTargetCreated(message) {
  if (message?.method !== 'Target.targetCreated') return null;
  const targetId = message?.params?.targetInfo?.targetId;
  return typeof targetId === 'string' && targetId.length > 0 ? targetId : null;
}

export function parseWebKitTargetDispatch(message) {
  if (message?.method !== 'Target.dispatchMessageFromTarget') return null;
  const targetId = message?.params?.targetId;
  const raw = message?.params?.message;
  if (typeof targetId !== 'string' || targetId.length === 0 || typeof raw !== 'string') return null;
  try {
    const inner = JSON.parse(raw);
    return inner && typeof inner === 'object' ? { targetId, message: inner } : null;
  } catch {
    return null;
  }
}

export function wrapWebKitTargetCommand(targetId, message) {
  assert.equal(typeof targetId, 'string', 'WebKit target id must be text');
  assert(targetId.length > 0, 'WebKit target id must not be empty');
  assert(message && typeof message === 'object' && !Array.isArray(message), 'WebKit target message must be an object');
  assert(Number.isInteger(message.id), 'WebKit target message requires an integer id');
  assert.equal(typeof message.method, 'string', 'WebKit target message requires a method');
  assert(message.method.length > 0, 'WebKit target method must not be empty');
  return {
    method: 'Target.sendMessageToTarget',
    params: { targetId, message: JSON.stringify(message) },
  };
}
