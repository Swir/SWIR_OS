import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const source = fs.readFileSync(new URL('../swir-notifications.js', import.meta.url), 'utf8');

function createHarness(initial = {}) {
  const store = new Map(Object.entries(initial));
  const events = [];
  const nativeCalls = [];
  const localStorage = {
    getItem(key) { return store.has(key) ? store.get(key) : null; },
    setItem(key, value) { store.set(key, String(value)); },
    removeItem(key) { store.delete(key); }
  };
  class CustomEvent {
    constructor(type, init = {}) { this.type = type; this.detail = init.detail; }
  }
  const window = {
    SWIR_PACKAGE_CATALOG: [],
    SWIR_NATIVE_HOST: {
      notifications: {
        async show(...args) { nativeCalls.push(['show', ...args]); return { delivered: true }; },
        async showWithActions(...args) { nativeCalls.push(['showWithActions', ...args]); return { delivered: true, actions: true }; },
        async invokeAction(detail) { nativeCalls.push(['invokeAction', detail]); return { handled: true }; }
      }
    },
    SwirOS: { toast() { throw new Error('native delivery should suppress Web toast'); } },
    dispatchEvent(event) { events.push(event); return true; }
  };
  const context = vm.createContext({ window, localStorage, CustomEvent, Date, Math, JSON, Object, Array, String, TypeError, Error, Set, Promise, console });
  vm.runInContext(source, context, { filename: 'swir-notifications.js' });
  return { api: window.SwirNotifications, window, store, events, nativeCalls };
}

const HISTORY_KEY = 'swir-app-notifications-v1';
const recent = new Date().toISOString();

// Legacy v1 arrays remain readable, are validated and never replay actions during restore.
{
  const legacy = [{
    id: 'legacy-1', appId: 'system', packageId: 'swir.system', appName: 'SWIR OS',
    title: 'Restored', message: 'Legacy row', time: recent,
    actions: [{ id: 'danger', label: 'Danger', type: 'event' }]
  }];
  const h = createHarness({ [HISTORY_KEY]: JSON.stringify(legacy) });
  const rows = h.api.list();
  assert.equal(rows.length, 1);
  assert.equal(rows[0].id, 'legacy-1');
  assert.equal(rows[0].actions[0].id, 'danger');
  assert.equal(h.events.length, 0, 'history restoration must not dispatch actions/events');
  assert.equal(h.nativeCalls.length, 0, 'history restoration must not invoke native actions');
}

// Sending persists schema v2, passes bounded declarative actions to a capable native provider and emits no executable payload.
{
  const h = createHarness();
  const result = await h.api.send('system', {
    title: 'Update ready',
    message: 'A verified update can be reviewed.',
    actions: [
      { id: 'review', label: 'Review', type: 'event', callback: () => { throw new Error('must never persist'); } },
      { id: 'open-settings', label: 'Open Settings', type: 'open-app', targetApp: 'settings' },
      { id: 'review', label: 'Duplicate', type: 'event' },
      { id: 'bad id', label: 'Rejected', type: 'event' },
      { id: 'fourth', label: 'Bounded', type: 'event' }
    ]
  });
  assert.equal(result.actions.length, 3);
  assert.equal(Array.from(result.actions, a => a.id).join(','), 'review,open-settings,fourth');
  assert.equal(h.nativeCalls[0][0], 'showWithActions');
  assert.equal(h.nativeCalls[0][5].length, 3);
  const persisted = JSON.parse(h.store.get(HISTORY_KEY));
  assert.equal(persisted.version, 2);
  assert.equal(persisted.notifications.length, 1);
  assert.equal(JSON.stringify(persisted).includes('callback'), false);
  assert.equal(JSON.stringify(persisted).includes('must never persist'), false);

  const actionResult = await h.api.invokeAction(result.id, 'open-settings');
  assert.equal(actionResult.actionType, 'open-app');
  assert.equal(actionResult.targetApp, 'settings');
  assert.equal(h.nativeCalls.at(-1)[0], 'invokeAction');
  assert.equal(h.events.at(-1).type, 'swir:notification-action');
}

// Providers that only implement the shipping four-argument show contract remain compatible even when Web actions are present.
{
  const h = createHarness();
  delete h.window.SWIR_NATIVE_HOST.notifications.showWithActions;
  await h.api.send('system', { message: 'Legacy provider', actions: [{ id: 'review', label: 'Review', type: 'event' }] });
  assert.equal(h.nativeCalls[0][0], 'show');
  assert.equal(h.nativeCalls[0].length, 5, 'legacy native show receives exactly four notification arguments');
}

// Tag replacement and the history cap are deterministic.
{
  const h = createHarness();
  await h.api.send('system', { tag: 'sync', message: 'old' });
  await h.api.send('system', { tag: 'sync', message: 'new' });
  assert.equal(h.api.list().filter(x => x.tag === 'sync').length, 1);
  assert.equal(h.api.list().find(x => x.tag === 'sync').message, 'new');
  for (let i = 0; i < 60; i += 1) await h.api.send('system', { message: `row-${i}` });
  assert.equal(h.api.list().length, 50);
  assert.equal(JSON.parse(h.store.get(HISTORY_KEY)).notifications.length, 50);
}

// Invalid/stale persisted data is discarded rather than trusted.
{
  const stale = new Date(Date.now() - 31 * 24 * 60 * 60 * 1000).toISOString();
  const rows = [
    { id: 'stale', appId: 'system', title: 'stale', message: 'stale', time: stale },
    { id: '', appId: 'system', title: 'bad', message: 'bad', time: recent },
    { id: 'good', appId: 'system', title: 'good', message: 'good', time: recent }
  ];
  const h = createHarness({ [HISTORY_KEY]: JSON.stringify({ version: 2, notifications: rows }) });
  assert.equal(Array.from(h.api.list(), x => x.id).join(','), 'good');
}

// A native/desktop persistence bridge can replace localStorage without changing the public API.
{
  const h = createHarness();
  let saved = null;
  const adapter = {
    async load() {
      return { version: 2, notifications: [{ id: 'native-row', appId: 'system', packageId: 'swir.system', appName: 'SWIR OS', title: 'Native', message: 'Restored from adapter', time: recent, actions: [] }] };
    },
    async save(value) { saved = value; }
  };
  await h.api.setPersistenceAdapter(adapter);
  assert.equal(h.api.list()[0].id, 'native-row');
  await h.api.send('system', { message: 'Persist through bridge' });
  assert.equal(saved.version, 2);
  assert.equal(saved.notifications.length, 2);
}

// Persistence failure keeps the validated in-memory history usable.
{
  const h = createHarness();
  await h.api.setPersistenceAdapter({ load: () => [], save: () => { throw new Error('offline'); } });
  await h.api.send('system', { message: 'Memory fallback' });
  assert.equal(h.api.list().length, 1);
}

console.log('web notification actions + persistence contract: ok');
