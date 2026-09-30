import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';

const registrySource = fs.readFileSync(new URL('../../swir-apps.js', import.meta.url), 'utf8');
const shellSource = fs.readFileSync(new URL('../../swir-os.js', import.meta.url), 'utf8');

function loadApps(nativeHost) {
  const window = {
    SWIR_NATIVE_HOST: nativeHost,
    addEventListener() {},
    SwirRuntime: null
  };
  const context = {
    window,
    localStorage: {
      getItem(key) { return key === 'swir-installed-apps' ? '[]' : null; },
      setItem() {}
    },
    queueMicrotask() {},
    setTimeout() { return 1; },
    clearTimeout() {},
    console
  };
  vm.runInNewContext(registrySource, context, { filename: 'swir-apps.js' });
  return window.SWIR_APPS;
}

const desktop = loadApps({
  edition: 'DESKTOP',
  features: { nativeKonofixLaunch: true, appIsolationRouting: true }
});
const desktopChat = desktop.find(app => app.id === 'chat');
assert.ok(desktopChat, 'Desktop chat entry is missing');
assert.equal(desktopChat.title, 'Konofix Chat');
assert.equal(desktopChat.type, 'native');
assert.equal(desktopChat.nativeMethod, 'launchKonofix');
assert.equal(desktopChat.desktop, true);
assert.equal(desktopChat.system, false);
assert.equal('url' in desktopChat, false, 'Desktop Konofix route must not retain the legacy iframe URL');

const web = loadApps(null);
const webChat = web.find(app => app.id === 'chat');
assert.ok(webChat, 'Web compatibility chat entry is missing during cutover');
assert.equal(webChat.title, 'SWIR Chat (legacy Web)');
assert.equal(webChat.type, 'iframe');
assert.equal(webChat.url, './swir-chat.html');
assert.equal(webChat.system, false);

for (const required of [
  'if (app.type === "native")',
  'void launchNativeApp(app);',
  'window.SWIR_NATIVE_HOST?.shellIntegration',
  '"Konofix 0.5.1 is not installed yet. SWIR will not fall back to the old Desktop chat."'
]) {
  assert.ok(shellSource.includes(required), `Desktop shell is missing Konofix route invariant: ${required}`);
}
assert.equal(shellSource.includes('window.open("./swir-chat.html"'), false,
  'Desktop native launch path must not directly fall back to the legacy Web chat');

console.log('SWIR Desktop Konofix route contract passed.');
