import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

const root = path.resolve(import.meta.dirname, '..');
const policyPath = path.join(root, 'swir-update-user-policy.js');
const framePath = path.join(root, 'swir-update-policy-frame.js');
const loaderPath = path.join(root, 'swir-v11.js');
const workerPath = path.join(root, 'sw.js');
const stagePath = path.join(root, 'desktop', 'windows', 'stage-desktop-runtime.ps1');
const productPath = path.join(root, 'SWIR-PRODUCT-BASELINE-1.0.md');

const policySource = fs.readFileSync(policyPath, 'utf8');
const frameSource = fs.readFileSync(framePath, 'utf8');
const loader = fs.readFileSync(loaderPath, 'utf8');
const worker = fs.readFileSync(workerPath, 'utf8');
const stage = fs.readFileSync(stagePath, 'utf8');
const product = fs.readFileSync(productPath, 'utf8');

function expect(condition, message) {
  if (!condition) throw new Error(message);
  console.log(`PASS ${message}`);
}
function requireText(source, needle, message) { expect(source.includes(needle), message); }
function rejectText(source, needle, message) { expect(!source.includes(needle), message); }

// Exercise the policy state contract without starting the shell automation loop.
const storage = new Map();
const localStorage = {
  getItem:key => storage.has(key) ? storage.get(key) : null,
  setItem:(key,value) => storage.set(key, String(value)),
  removeItem:key => storage.delete(key)
};
const sessionStorage = { getItem:()=>null, setItem:()=>{} };
class CustomEvent { constructor(type, options = {}) { this.type=type; this.detail=options.detail; } }
class MutationObserver { constructor(){} observe(){} }
const document = {
  readyState:'loading', documentElement:{},
  addEventListener(){}, querySelector(){ return null; }
};
const window = { dispatchEvent(){ return true; } };
const context = vm.createContext({
  window, document, localStorage, sessionStorage, CustomEvent, MutationObserver,
  HTMLIFrameElement:class {}, HTMLElement:class {}, URL, Date, JSON, Object, Array, String, Set, Map,
  setTimeout:()=>0, clearTimeout(){}, console
});
vm.runInContext(policySource, context, { filename:'swir-update-user-policy.js' });
const api = window.SwirUpdatePolicy;
expect(api?.schema === 'swir.desktop-update-user-policy/1.0', 'user update policy schema is exposed');
expect(api.modes.join(',') === 'automatic,notify,manual', 'policy exposes exactly Automatic / Notify only / Manual modes');
expect(api.state().mode === 'notify', 'safe default policy is Notify only');
expect(api.state().semantics.automatic === 'signed-check-and-prepare-no-restart', 'Automatic semantics explicitly stop before restart');
expect(api.state().semantics.notify === 'signed-check-only', 'Notify only semantics are check-only');
expect(api.state().semantics.manual === 'user-initiated-only', 'Manual semantics disable startup checks');
api.setMode('automatic');
expect(api.state().mode === 'automatic', 'Automatic policy persists');
api.setMode('manual');
expect(api.state().mode === 'manual', 'Manual policy persists');
api.setMode('invalid-value');
expect(api.state().mode === 'notify', 'invalid policy fails safely to Notify only');

// User intent is deliberately isolated from trust configuration.
for (const forbidden of ['PublicKeyPem', 'ManifestUrl', 'ManifestHosts', 'PackageHosts', 'catalog-trust-roots', 'trust root']) {
  rejectText(policySource, forbidden, `user policy cannot mutate release trust material (${forbidden})`);
  rejectText(frameSource, forbidden, `frame policy cannot mutate release trust material (${forbidden})`);
}

requireText(policySource, "policy.mode === 'manual'", 'Manual mode blocks automatic startup work');
requireText(policySource, "window.SwirOS.open('updates')", 'background policy uses the trusted Update Center surface');
requireText(policySource, "url.pathname !== '/swir-updates.html'", 'controller injection is pinned to the reviewed Update Center path');
requireText(policySource, "url.origin !== location.origin", 'controller injection is same-origin only');
requireText(policySource, "frame.contentDocument", 'controller is injected into the pinned system frame rather than a public app surface');
requireText(frameSource, "location.pathname !== '/swir-updates.html'", 'frame controller refuses any non-Update-Center document');
requireText(frameSource, "parent.postMessage({ type:'swir-system-update-command'", 'frame reuses the existing trusted private update bridge');
requireText(frameSource, "const check = await command('check'", 'startup modes use signed release check');
requireText(frameSource, "if (mode === 'notify')", 'Notify only has a dedicated non-download branch');
requireText(frameSource, "await command('prepare'", 'Automatic mode can queue verified Candidate preparation');
requireText(frameSource, "await waitForPreparation(targetVersion)", 'Automatic mode waits for preparation verification outcome');
requireText(frameSource, "status:'prepared'", 'prepared Candidate is reported to the shell/user');
rejectText(frameSource, "command('applyAndRestart'", 'startup policy never activates/restarts an update automatically');
rejectText(frameSource, "command(\"applyAndRestart\"", 'startup policy never activates/restarts an update automatically (double quotes)');
rejectText(policySource, 'applyAndRestart', 'parent user policy never owns update activation');

requireText(frameSource, 'AUTOMATIC — CHECK + PREPARE', 'Update Center gets an explicit Automatic selector');
requireText(frameSource, 'NOTIFY ONLY — CHECK, ASK BEFORE DOWNLOAD', 'Update Center gets an explicit Notify only selector');
requireText(frameSource, 'MANUAL — USER CHECK ONLY', 'Update Center gets an explicit Manual selector');
requireText(frameSource, 'restart remains explicit', 'Update Center explains the Automatic restart boundary');
requireText(loader, './swir-update-user-policy.js?v=1.0.0', 'shell loader includes the user policy runtime');
requireText(worker, "'./swir-update-user-policy.js'", 'user policy runtime is precached');
requireText(worker, "'./swir-update-policy-frame.js'", 'trusted frame controller is precached');
requireText(worker, 'update-policy-1.0.0', 'Service Worker cache invalidates for update policy 1.0');
requireText(stage, "'.js', '.mjs'", 'Desktop runtime staging admits tracked JS policy assets');
requireText(stage, '$tracked = @(& git -C $source ls-files)', 'Desktop runtime only stages tracked policy assets');
requireText(product, '**Automatic** — download/prepare trusted updates automatically and request restart when required.', 'implementation semantics match Product Baseline Automatic definition');
requireText(product, '**Notify only** — check automatically but require user approval before download/install.', 'implementation semantics match Product Baseline Notify definition');
requireText(product, '**Manual** — check only on user request', 'implementation semantics match Product Baseline Manual definition');

for (const [name, source] of [['policy',policySource],['frame',frameSource]]) {
  try { new Function(source); }
  catch (error) { throw new Error(`${name} update policy script failed JavaScript parse validation: ${error.message}`); }
}

console.log('SWIR Desktop update user policy validated: Automatic / Notify only / Manual, signed broker reuse, no trust mutation and no unattended restart.');
