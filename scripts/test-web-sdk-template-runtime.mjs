import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..');
const source = fs.readFileSync(path.join(root, 'examples', 'swir-app-template', 'app.js'), 'utf8');

const handlers = new Map();
function element(initial = {}) {
  return {
    textContent: '',
    value: '',
    classList: { toggle() {} },
    addEventListener(type, handler) { handlers.set(`${initial.id}:${type}`, handler); },
    ...initial
  };
}

const elements = new Map([
  ['#status', element({ id: 'status' })],
  ['#note', element({ id: 'note' })],
  ['#package-id', element({ id: 'package-id' })],
  ['#edition', element({ id: 'edition' })],
  ['#locale', element({ id: 'locale' })],
  ['#launches', element({ id: 'launches' })],
  ['#save', element({ id: 'save' })],
  ['#clear', element({ id: 'clear' })]
]);

const writes = [];
const removals = [];
const bridge = {
  packageId: 'example.hello',
  sdk: {
    bridge: { info: async () => ({ packageId: 'example.hello', edition: 'WEB' }) },
    locale: {
      info: async () => ({ locale: 'pl-PL', direction: 'ltr' }),
      formatNumber: async value => `PL:${value}`
    }
  },
  storage: {
    get: async (key, fallback) => key === 'starter.launchCount' ? 2 : key === 'starter.note' ? 'fixture note' : fallback,
    set: async (key, value) => { writes.push([key, value]); return true; },
    remove: async key => { removals.push(key); return true; }
  }
};

const document = {
  documentElement: { lang: 'en', dir: 'ltr' },
  querySelector(selector) {
    const node = elements.get(selector);
    if (!node) throw new Error(`Missing fixture element ${selector}`);
    return node;
  }
};

const context = vm.createContext({
  window: { SwirAppBridge: bridge },
  document,
  addEventListener() {},
  console,
  Number,
  Error,
  Promise,
  setTimeout,
  clearTimeout
});

vm.runInContext(source, context, { filename: 'examples/swir-app-template/app.js' });
await new Promise(resolve => setTimeout(resolve, 0));

function expect(condition, message) {
  if (!condition) throw new Error(`WEB SDK TEMPLATE RUNTIME FAIL: ${message}`);
}

expect(document.documentElement.lang === 'pl-PL', 'locale was not applied');
expect(document.documentElement.dir === 'ltr', 'text direction was not applied');
expect(elements.get('#package-id').textContent === 'example.hello', 'bridge package identity was not rendered');
expect(elements.get('#edition').textContent === 'WEB', 'edition was not rendered');
expect(elements.get('#launches').textContent === 'PL:3', 'locale formatter was not used for launch count');
expect(elements.get('#note').value === 'fixture note', 'private storage note was not restored');
expect(writes.some(([key, value]) => key === 'starter.launchCount' && value === 3), 'launch count was not persisted through bridge storage');

const save = handlers.get('save:click');
expect(typeof save === 'function', 'save handler was not registered');
elements.get('#note').value = '  saved through fixture  ';
await save();
expect(writes.some(([key, value]) => key === 'starter.note' && value === 'saved through fixture'), 'save did not use bridge storage');

const clear = handlers.get('clear:click');
expect(typeof clear === 'function', 'clear handler was not registered');
await clear();
expect(removals.includes('starter.note'), 'clear did not use bridge storage remove');
expect(elements.get('#note').value === '', 'clear did not update the visible note');

console.log(JSON.stringify({ schema: 'swir.web-sdk-template-runtime/1.0', valid: true, writes: writes.length, removals: removals.length }));
