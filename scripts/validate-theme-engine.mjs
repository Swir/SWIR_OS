import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..');
const enginePath = path.join(root, 'swir-theme-engine.js');
const centerPath = path.join(root, 'swir-themes.html');
const loaderPath = path.join(root, 'swir-v11.js');
const appsPath = path.join(root, 'swir-apps.js');
const workerPath = path.join(root, 'sw.js');

const engineSource = fs.readFileSync(enginePath, 'utf8');
const center = fs.readFileSync(centerPath, 'utf8');
const loader = fs.readFileSync(loaderPath, 'utf8');
const apps = fs.readFileSync(appsPath, 'utf8');
const worker = fs.readFileSync(workerPath, 'utf8');

function requireText(source, needle, message) {
  if (!source.includes(needle)) throw new Error(message);
}
function expect(condition, message) {
  if (!condition) throw new Error(message);
  console.log(`PASS ${message}`);
}
function expectThrows(action, message) {
  try { action(); } catch { console.log(`PASS ${message}`); return; }
  throw new Error(`Expected rejection: ${message}`);
}

const storage = new Map();
const styleValues = new Map();
const style = {
  setProperty(key, value) { styleValues.set(key, value); },
  removeProperty(key) { styleValues.delete(key); }
};
const documentElement = { dataset:{}, style };
const head = { appendChild() {} };
const document = {
  documentElement,
  head,
  getElementById() { return null; },
  createElement(tag) { return { tagName:String(tag).toUpperCase(), id:'', textContent:'' }; }
};
const localStorage = {
  getItem(key) { return storage.has(key) ? storage.get(key) : null; },
  setItem(key, value) { storage.set(key, String(value)); },
  removeItem(key) { storage.delete(key); }
};
class CustomEvent { constructor(type, options = {}) { this.type = type; this.detail = options.detail; } }
const emitted = [];
const window = { dispatchEvent(event) { emitted.push(event); return true; } };
const context = vm.createContext({ window, document, localStorage, CustomEvent, console, Map, Set, Object, Array, String, TypeError, RegExp });
vm.runInContext(engineSource, context, { filename:'swir-theme-engine.js' });
const api = window.SwirThemeEngine;

expect(api?.schema === 'swir.theme-engine/1.0', 'appearance engine schema is exposed');
expect(api.profiles().map(item => item.id).join(',') === 'neon,glass,minimal,classic,contrast', 'five reviewed built-in shell profiles are registered');
expect(api.state().profile === 'neon' && api.state().accent === 'blue', 'safe default is Neon Core / blue');
api.setProfile('classic');
expect(documentElement.dataset.swirProfile === 'classic' && storage.get('swir-theme-profile') === 'classic', 'profile selection persists');
api.setAccent('green');
expect(documentElement.dataset.theme === 'green' && storage.get('swir-theme') === 'green', 'accent selection persists');
api.setProfile('does-not-exist');
expect(api.state().profile === 'neon', 'unknown profile fails safely to Neon Core');

const custom = api.registerPack({ id:'swir-test', label:'SWIR Test', description:'Safe token test.', tokens:{ '--panel':'#111827', '--radius':'12px' } });
expect(custom.id === 'swir-test' && api.profiles().some(item => item.id === 'swir-test'), 'safe token-only theme pack can register');
api.setProfile('swir-test');
expect(styleValues.get('--panel') === '#111827' && styleValues.get('--radius') === '12px', 'safe custom theme tokens are applied');
expectThrows(() => api.registerPack({ id:'bad-css', label:'Bad', description:'x', cssText:'body{}', tokens:{ '--panel':'#000' } }), 'arbitrary CSS injection is rejected');
expectThrows(() => api.registerPack({ id:'bad-script', label:'Bad', description:'x', script:'alert(1)', tokens:{ '--panel':'#000' } }), 'script injection is rejected');
expectThrows(() => api.registerPack({ id:'bad-token', label:'Bad', description:'x', tokens:{ '--not-allowed':'red' } }), 'unallowlisted design token is rejected');
expectThrows(() => api.registerPack({ id:'bad-url', label:'Bad', description:'x', tokens:{ '--panel':'url(https://evil.example/a)' } }), 'remote URL token is rejected');
expectThrows(() => api.registerPack({ id:'neon', label:'Replace', description:'x', tokens:{ '--panel':'#000' } }), 'built-in recovery profile cannot be replaced');
expect(api.unregisterPack('swir-test') === true && api.state().profile === 'neon', 'removing active custom theme recovers to Neon Core');
expect(!styleValues.has('--panel') && !styleValues.has('--radius'), 'custom tokens are removed during recovery');
expect(emitted.some(event => event.type === 'swir:theme-change'), 'theme changes emit a shell event');

const themeLoader = loader.indexOf('./swir-theme-engine.js?v=1.0.0');
const coreLoader = loader.indexOf('./swir-v11-fixed.js?v=1.1.1');
expect(themeLoader >= 0 && coreLoader > themeLoader, 'appearance engine loads before the enhanced shell runtime');
requireText(apps, 'id:"themes"', 'Theme Center must be registered as a system app.');
requireText(apps, 'url:"./swir-themes.html"', 'Theme Center must use the reviewed local page.');
requireText(worker, "'./swir-theme-engine.js'", 'Appearance Engine must be available offline.');
requireText(worker, "'./swir-themes.html'", 'Theme Center must be available offline.');
requireText(worker, 'theme-engine-1.0.0', 'Service Worker cache must invalidate for Appearance Engine 1.0.');
requireText(center, 'parent.SwirThemeEngine', 'Theme Center must use the parent-owned Appearance Engine.');
requireText(center, 'cannot inject JavaScript, arbitrary CSS, remote URLs or native calls', 'Theme Center must disclose the safe pack boundary.');

const scripts = [...center.matchAll(/<script(?:\s[^>]*)?>([\s\S]*?)<\/script>/gi)].map(match => match[1]).filter(Boolean);
expect(scripts.length > 0, 'Theme Center includes executable UI integration');
for (const [index, script] of scripts.entries()) {
  try { new Function(script); }
  catch (error) { throw new Error(`Theme Center inline script ${index + 1} failed parse validation: ${error.message}`); }
}

console.log('SWIR Appearance Engine contract validated: safe profiles, token-only theme packs, recovery, registry and offline integration.');
